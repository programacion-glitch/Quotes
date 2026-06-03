# Progressive BasePage Hardening — Design

**Fecha:** 2026-06-02
**Autor:** Sesión Claude + Juan
**Estado:** Aprobado para writing-plans

## Contexto y motivación

El módulo `modules/progressive/` automatiza cotizaciones en el portal web de Progressive (UI ExtJS / Sencha). Tiene end-to-end LIVE validado con M&D CUSTOM FREIGHT LLC (Trucker, USDOT 2998569, precio $57,944/año, Quote # CA117031734). En la sesión 2026-06-02 se intentó cotizar RYD LLC (Beverage Distributor, USDOT 4427567) y se atascó en `more_business_page._answer_eld_required` con timeout de 30s — probablemente porque el radio "ELD required" no se renderiza para Beverage Distributor.

Durante esa sesión se cazaron ~30 bugs nuevos. El patrón dominante es: **ExtJS rompe selectores y comportamientos tradicionales de Playwright**, y las reglas para sortearlo viven solo en la memoria persistente del asistente y en hábitos del operador — no en código compartido. Cada page reimplementa su propia versión de Continue, fill, radio y combo, con variaciones sutiles. Cuando una page rompe, fixearla no previene que otra rompa por la misma causa.

`base_page.py` existe pero contiene helpers obsoletos (`fill_by_label`, `select_by_label`) que usan los patrones que la memoria explícitamente lista como NO funcionales con ExtJS. Es decir, BasePage está, pero está roto y nadie lo usa.

## Objetivo

Reescribir `base_page.py` como un **hub de primitivas ExtJS-safe obligatorias** que codifica todas las reglas validadas live, y migrar cada page object a llamar esas primitivas en lugar de reimplementarlas localmente. El paso-a-paso del flow (qué pages, qué orden, qué campos) NO cambia — solo el cómo se interactúa con cada widget.

Alcance: **mínimo / hardening**. No se reorganiza el árbol de archivos, no se parten archivos grandes, no se centralizan selectores en un registry. Esos son candidatos para PRs futuros.

## Decisiones tomadas

1. **Problema #1 elegido:** cada page falla distinto por falta de primitivas ExtJS-safe compartidas. Centralizar selectores en un registry NO es la prioridad (los selectores ya son mayormente `get_by_role` con nombres visibles, no GUIDs).
2. **Alcance:** hardening mínimo de BasePage. No se introduce abstracción `Field` ni split de archivos grandes.
3. **`safe_fill` verify=True por defecto.** Confiabilidad > 100ms.
4. **`safe_click_continue` levanta `ContinueStuckError` tras retries.** Fail-loud; la page no adivina.
5. **Ausencia de campo condicional → soft-skip con warning.** No crash. Pattern que arregla el bug RYD ELD.

## Arquitectura

### Estructura de archivos

```
modules/progressive/
├── client.py                    # sin cambios
├── quote_flow.py                # sin cambios (orquestador)
├── field_mapper.py              # sin cambios
├── otp_reader.py                # sin cambios
└── pages/
    ├── base_page.py             # REESCRITO: hub de primitivas ExtJS-safe
    ├── _interactions.py         # NUEVO: helpers internos (JS dispatch, polling)
    ├── _exceptions.py           # NUEVO: ExtJSInteractionError, FieldNotFoundError, ContinueStuckError
    ├── login_page.py            # migrado a primitivas
    ├── home_page.py             # migrado
    ├── business_info_page.py    # migrado: elimina _click_continue local, _fill_role_textbox, etc.
    ├── vehicles_page.py         # migrado
    ├── drivers_page.py          # migrado
    ├── more_business_page.py    # migrado: arregla bug RYD ELD
    ├── coverages_rates_page.py  # migrado: gana Continue robusto
    └── final_details_page.py    # migrado
```

### Principio rector

Ninguna página vuelve a llamar `page.click()`, `page.fill()`, `page.select_option()` o `get_by_role("button", name="Continue")` directamente. Todo pasa por una primitiva de `BasePage`.

### Responsabilidades por capa

| Capa | Qué hace | Qué NO hace |
|---|---|---|
| `quote_flow.py` | Orquesta steps, maneja result | No toca selectores ni Playwright directo |
| `pages/*.py` | Conoce QUÉ campos llenar, qué orden, variantes por commodity | No reimplementa CÓMO llenar/click; declara y delega |
| `base_page.py` | Provee CÓMO interactuar con ExtJS de forma segura | No conoce campos específicos de ninguna página |
| `_interactions.py` | Detalles internos (JS dispatch, polling, retry timing) | Importado solo por BasePage |
| `_exceptions.py` | Errores estructurados con contexto | — |

## Catálogo de primitivas en BasePage

### Familia A — Localización tolerante

```python
async def find_by_label_text(label: str, *, kind: str = "input", timeout_ms: int = 5000) -> Locator
async def find_by_placeholder(placeholder: str, *, timeout_ms: int = 5000) -> Locator
async def find_radiogroup(name: str, *, exact: bool = False, timeout_ms: int = 5000) -> Locator
async def find_combo(label_or_placeholder: str, *, timeout_ms: int = 5000) -> Locator
async def field_exists(locator_or_finder, *, wait_ms: int = 2000) -> bool
```

- `find_by_label_text` aplica el XPath traversal validado: `label.locator("xpath=following::input[@type='text'][1]")`.
- `field_exists` es la clave del bug RYD: short-poll (default 2s) que retorna `False` sin levantar excepción.

### Familia B — Interacción ExtJS-safe (obligatorias)

```python
async def safe_fill(locator: Locator, value: str, *, verify: bool = True, retries: int = 2) -> None
async def safe_radio(group: Locator, option: str, *, retries: int = 3) -> None
async def safe_checkbox(locator: Locator, *, check: bool = True) -> None
async def safe_select_combo(combo: Locator, option_text: str, *, retries: int = 2) -> None
async def safe_click_continue(*, expect_url_changes_from: str, retries: int = 3) -> None
```

Contrato de cada una:

| Primitiva | Hace siempre | Verifica | Levanta si |
|---|---|---|---|
| `safe_fill` | click → fill → Tab → `input_value()` | valor en DOM coincide | tras `retries` no coincide |
| `safe_radio` | click radio → `is_checked()` → reintenta con `force=True` → `check(force=True)` | radio queda checked | tras `retries` sigue unchecked |
| `safe_checkbox` | lee `is_checked()` → toggle solo si difiere | estado final coincide | tras `retries` no coincide |
| `safe_select_combo` | combo.click() → espera options → `get_by_role("option")` → click → verify input_value contiene texto | valor visible coincide | tras `retries` no coincide |
| `safe_click_continue` | blur active → `get_by_text("Continue", exact=True).last` → `force=True` → URL changed? → JS dispatch fallback walking-up el `.x-btn` | URL ya no contiene el token de la página actual | tras `retries` la URL sigue igual → `ContinueStuckError` con screenshot |

### Familia C — Esperas dinámicas

```python
async def wait_for_extjs_idle(*, timeout_ms: int = 10000) -> None
async def wait_for_field_revealed_by(trigger_fn, target_finder, *, timeout_ms: int = 5000) -> Locator
async def wait_for_page(page_name_token: str, *, timeout_ms: int = 30000) -> None
async def wait_for_currency_formatted(locator: Locator, *, timeout_ms: int = 3000) -> None
```

- `wait_for_extjs_idle` polea `Ext.Ajax.isLoading` + `document.readyState` + ausencia de `.x-mask` visibles. Se llama automáticamente al inicio de cada primitiva de Familia B.
- `wait_for_field_revealed_by` reemplaza el patrón "click + sleep(1500) + find".
- `wait_for_currency_formatted` espera que ExtJS formatee `50000` → `$50,000` antes de continuar.

### Familia D — Estado de página

```python
async def remove_overlays() -> None
async def blur_active_element() -> None
async def current_page_token() -> str  # extrae pageName del URL
```

### Familia E — Diagnóstico

```python
async def screenshot(name: str, *, include_html: bool = False) -> Path
async def dump_debug_context(label: str) -> dict  # URL, pageName, visible buttons, last error
```

Toda primitiva que levanta excepción captura screenshot + `dump_debug_context` automáticamente. El `ExtJSInteractionError` carga atributos `screenshot_path: Path`, `debug_context: dict`, `primitive: str`, `field: str | None`, `attempts: int` — el path apunta al archivo en `logs/`, no los bytes.

### Política de retries

Todos los `retries` configurables por llamada con defaults sanos. Backoff lineal: 500ms, 1500ms, 3000ms entre intentos (no exponencial — ExtJS es predecible).

## Esperas dinámicas: regla de oro

"No esperar tiempo, esperar condición". Los `wait_for_timeout(1500)` hardcoded se reemplazan por:

| Pattern hoy | Pattern nuevo |
|---|---|
| `click radio → sleep 1500 → buscar textbox` | `wait_for_field_revealed_by(trigger_fn=radio.click, target_finder=lambda: find_by_label_text("Business Name"))` |
| `fill → sleep 1500 → Tab → continue` | `safe_fill` ya hace verify; sin sleep |
| `safe_radio → sleep 300` | `safe_radio` ya verifica `is_checked`; sin sleep |
| `safe_fill currency → sleep 1500 → continue` | `wait_for_currency_formatted(input)` |
| `click continue → sleep 1500 → URL check` | `safe_click_continue` polea URL hasta cambio |

Los `wait_for_timeout` que sobreviven llevan comentario justificando por qué no se puede esperar a una condición.

### `wait_for_extjs_idle()` JS

```python
await self.page.wait_for_function(
    """() => {
        const extQuiet = typeof Ext === 'undefined' ||
                         !Ext.Ajax || !Ext.Ajax.isLoading();
        const noMask = !document.querySelector('.x-mask:not(.x-mask-fixed)');
        const ready = document.readyState === 'complete';
        return extQuiet && noMask && ready;
    }""",
    timeout=timeout_ms,
)
```

## Manejo de ausencia de campo (arregla bug RYD)

Hoy `more_business_page.py:138-146` busca el ELD radiogroup directamente y revienta con timeout si no existe. El nuevo pattern:

```python
async def fill_and_submit(self, *, currently_insured, other_coverages, eld_required, ...):
    await self.wait_for_extjs_idle()

    # Required:
    await self.safe_radio(
        await self.find_radiogroup("Is the customer currently insured?"),
        "Yes" if currently_insured else "No",
    )

    # Conditional (no render para Beverage Distributor):
    eld_group = await self.find_radiogroup(
        "Is an Electronic Logging Device (ELD) required",
        timeout_ms=2000,
    )
    if await self.field_exists(eld_group, wait_ms=500):
        await self.safe_radio(eld_group, "Yes" if eld_required else "No")
    else:
        print("    [Progressive] ELD radio not rendered for this commodity — skipped")
        self._log_skipped("eld_required", reason="field_not_present_for_commodity")

    await self.safe_click_continue(expect_url_changes_from="MoreAboutBusiness")
```

### Clasificación explícita de campos por página

Cada page declara al inicio:

```python
class MoreBusinessPage(BasePage):
    REQUIRED_FIELDS = ("currently_insured", "other_coverages")
    CONDITIONAL_FIELDS = ("eld_required", "federal_filings")  # may not render
    OPTIONAL_FIELDS = ("customer_email",)                      # render always, can leave blank
```

Procesamiento por tipo:
- REQUIRED → `find_*` con timeout normal + `safe_*` (revienta si falla)
- CONDITIONAL → `field_exists` primero, skip con log si ausente
- OPTIONAL → llenar si valor presente, ignorar si no

### Auditoría de skips

Cada CONDITIONAL skipeado se agrega a `QuoteResult.warnings`:

```
"more_business: skipped 'eld_required' — field_not_present_for_commodity"
```

## Plan de migración

### Orden de fases

| Fase | Qué se hace | Verificación |
|---|---|---|
| **0** | Snapshot baseline: correr simulador + M&D live, guardar logs y screenshot | `tests/simulate_progressive.py` pasa con 83 acciones; M&D live captura precio |
| **1** | Crear `_exceptions.py`, `_interactions.py`. Agregar las primitivas nuevas a `base_page.py` SIN borrar los helpers obsoletos (`by_label`, `fill_by_label`, `select_by_label`, `click_by_text`) — quedan con docstring `DEPRECATED — use safe_*` para que las pages aún sin migrar sigan funcionando. NO migrar pages. | Tests unitarios de primitivas (mocked Playwright). Simulador sigue pasando. |
| **2** | Migrar `more_business_page.py` (donde está el bug RYD, 178 líneas) | Simulador + `run_progressive_from_pdf.py RYD.pdf` pasa hasta capturar precio |
| **3** | Migrar `login_page.py`, `home_page.py`, `final_details_page.py` (los chicos) | Simulador + live RYD |
| **4** | Migrar `drivers_page.py` (271 líneas) | Simulador + live RYD |
| **5** | Migrar `coverages_rates_page.py` (408) y `vehicles_page.py` (639) | Simulador + live RYD + live M&D (regresión completa) |
| **6** | Migrar `business_info_page.py` (831 líneas, dejado al final cuando hay confianza) | Simulador + live M&D + live RYD |
| **7** | Borrar de `base_page.py` los helpers DEPRECATED (`by_label`, `fill_by_label`, `select_by_label`, `click_by_text`, `select_option_by_text`) — ya nadie los llama después de fase 6 | Simulador + `grep -rn "by_label\|fill_by_label\|select_by_label" modules/progressive/pages/` retorna vacío |

Cada fase es un commit separado en una rama nueva.

### Coexistencia primitiva nueva / código viejo

Durante fases 2-6 conviven. Para evitar confusión:
- Métodos locales viejos reciben docstring `DEPRECATED — use BasePage.safe_*`.
- Al migrar una page, se borran sus métodos privados ya no llamados.
- Fase 7 corre `grep -r "_click_continue\|wait_for_timeout(15" modules/progressive/pages/` y verifica que solo quedan los justificados.

### Tests antes del refactor

```
tests/progressive/test_base_page_primitives.py
  - test_safe_fill_verifies_value
  - test_safe_fill_retries_on_mismatch
  - test_safe_fill_raises_after_retries
  - test_safe_radio_retries_with_force
  - test_safe_radio_raises_if_unchecked_after_retries
  - test_safe_click_continue_verifies_url_changed
  - test_safe_click_continue_uses_js_fallback
  - test_safe_click_continue_raises_stuck
  - test_field_exists_returns_false_on_timeout
  - test_wait_for_extjs_idle_polls_until_quiet
  - test_wait_for_field_revealed_by_returns_locator
```

Sin Progressive vivo — mocks de `Playwright.Page`. Corren en CI / pre-commit.

### Rollback

- Rama independiente; `git checkout main` devuelve al estado actual.
- Cada fase es commit atómico; `git revert <fase-N>` devuelve a la N-1.
- Tests unitarios + simulador atrapan regresiones antes de live.

## Criterios de éxito

El refactor se considera exitoso cuando se cumplen TODOS:

| # | Criterio | Verificación |
|---|---|---|
| 1 | M&D sigue cotizando end-to-end live | `run_progressive_from_pdf.py M&D.pdf 06/15/2026` captura precio |
| 2 | RYD cotiza end-to-end live por primera vez | Mismo script con PDF RYD captura precio; warning ELD skipped aparece |
| 3 | Cero llamadas directas a `page.fill/click/select_option` desde `pages/*.py` | `grep -nE "self\.page\.(fill|click|select_option)" modules/progressive/pages/ | grep -v base_page.py` vacío |
| 4 | Cero `_click_continue` locales fuera de base_page | `grep -rn "_click_continue" modules/progressive/pages/ | grep -v base_page.py | grep -v safe_click_continue` vacío |
| 5 | Reducción ≥ 70% de `wait_for_timeout` "mágicos" (definidos como: cualquier `wait_for_timeout(N)` sin comentario en la línea anterior justificando por qué no se puede esperar a una condición) | conteo baseline vs post-refactor: `grep -B1 "wait_for_timeout" modules/progressive/pages/*.py | grep -B1 -v "^.*#"` |
| 6 | Simulador sigue pasando con su conteo de acciones | run en verde |
| 7 | Tests unitarios de primitivas pasan | `pytest tests/progressive/test_base_page_primitives.py -v` verde |
| 8 | Cuando una primitiva falla, el error nombra primitiva, campo, intento, screenshot | Test específico forzando fallo |

### Métricas de baseline en fase 0

```
baseline_metrics.md:
- Total wait_for_timeout calls en pages/*.py
- Total métodos _click_continue locales
- Líneas de pages/*.py tocadas por bug fixes 2026-06
- Tiempo end-to-end M&D live
- Tiempo end-to-end RYD live hasta donde llegue hoy
```

## Definición de "done"

- [ ] Las 7 fases commiteadas atómicamente
- [ ] Los 8 criterios verificados
- [ ] M&D + RYD corrieron live al menos una vez post-refactor
- [ ] `CLAUDE.md` actualizado: "Reglas para Progressive" pasa a "usar `safe_*` de BasePage; ver `base_page.py`"
- [ ] `docs/AGENTS_CONTEXT.md` actualizado
- [ ] Memorias persistentes `progressive_extjs_selector_patterns.md` y `progressive_state_2026_06_02.md` actualizadas: reglas → primitivas

## Fuera de alcance (PRs futuros)

- Add Trailer flow real
- Centralización de selectores en registry YAML
- Split de `business_info_page.py` y `vehicles_page.py`
- Telemetría estructurada (JSON logs)
- Tests de integración Playwright reales contra Progressive mockeado

## Riesgo residual

- **Progressive cambia su UI durante la migración.** Mitigación: screenshots baseline en fase 0 por página.
- **`wait_for_extjs_idle` peta si `Ext.Ajax` no está definido.** Mitigación: el JS maneja `typeof Ext === 'undefined'`. Test unitario cubre.
- **Bug RYD no es solo ELD — hay más fields condicionales escondidos.** Mitigación: `field_exists` + clasificación CONDITIONAL convierte descubrimiento de campos faltantes en log + skip, no crash.
