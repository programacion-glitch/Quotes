# Progressive — Fail-Loud Mapping (Resolver Central + Preflight)

**Fecha:** 2026-06-04
**Estado:** Diseño aprobado, pendiente plan de implementación
**Branch destino:** progressive-basepage-hardening (o branch nuevo)

## Problema

El RPA de Progressive cotiza bien con un cliente y rompe con el siguiente.
La causa no son bugs sueltos: es un patrón. Cuando el bot encuentra un valor
del Blue Quote que no sabe mapear a una opción de Progressive, **elige un
catch-all en silencio y sigue** — produciendo una cotización posiblemente
incorrecta sin ninguna señal, o rompiendo más adelante cuando el catch-all
ni siquiera existe en la página.

Las primitivas de `base_page.py` ya fallan fuerte (lanzan excepciones tipadas
con screenshot cuando una acción de Playwright falla). `field_mapper.py` ya
tiene preflight de campos críticos (`missing_critical`) y de precio
(`missing_for_accurate_price`). El hueco está en una **tercera categoría sin
política: el guess silencioso de valores**, disperso por `field_mapper` y las
8 pages.

### Guess-sites de mayor dolor (confirmados en código)

1. `business_info_page.py::_map_commodity_to_option` (~L490) — devuelve
   `(search_term, None)` cuando no mapea, y luego rutea a `"Trucker"` en
   silencio.
2. `business_info_page.py::_answer_type_of_trucker` (~L565) — prefiere
   `"General Freight / Other"`, y si no está, **clickea la primera opción
   no-vacía** (guess puro).
3. `vehicles_page.py::_map_to_button` (~L298) — devuelve `"Other / Not Listed"`
   cuando nada matchea; ese label **no existe** en el tile picker expandido
   para algunos commodities (rompe REPUBLIC AGGREGATE, sand & gravel).

Las tres comparten la misma firma del bug: una función de mapeo que, ante
no-match, devuelve un **catch-all silencioso** en vez de señalar "no sé".

## Decisiones de diseño (acordadas con el usuario)

1. **Foco:** atacar la fragilidad sistémica, no terminar el trailer flow.
2. **Política ante valor no mapeable:** detenerse y avisar (HALT con
   diagnóstico), nunca cotizar mal en silencio.
3. **Dónde se traza la línea del HALT:** solo HALT si el **valor estaba
   presente en el Blue Quote pero no matchea** ninguna opción. Si el campo
   simplemente **no vino** (GVW, radius), se aplica un default documentado y
   se sigue, registrando la suposición.
4. **Reporte de blockers:** preflight batch (valida todo lo validable offline
   y junta todos los blockers estáticos en un reporte) + in-flight fail-fast
   (para campos dinámicos cascada que solo aparecen live).
5. **Alcance de este spec:** construir el mecanismo central + aplicarlo SOLO a
   los 3 campos de mayor dolor. Las otras 5 pages se migran en specs
   posteriores.
6. **Enfoque:** resolver central (Enfoque A), no HALT inline disperso ni
   crawler automático de catálogos.

## Arquitectura

```
modules/progressive/
├── choice_resolver.py     # NUEVO — resolve_choice() + Resolution + UnmappableValueError
├── catalogs/              # NUEVO — JSON de opciones válidas, sembrado de DIAG dumps
│   ├── README.md          #   cómo refrescar un catálogo
│   ├── business_type.json
│   ├── type_of_trucker.json
│   └── vehicle_tiles.json
├── catalogs.py            # NUEVO — loader + cache de los JSON
├── preflight.py           # NUEVO — run_preflight(mapped_fields) -> PreflightReport
├── pages/
│   ├── _exceptions.py     # + UnmappableValueError (extiende familia existente)
│   ├── business_info_page.py  # refactor 2 sitios → resolve_choice
│   └── vehicles_page.py       # refactor 1 sitio → resolve_choice (tiles enumerados live)
└── quote_flow.py          # corre preflight antes del browser; AssumptionLog; except UnmappableValueError
```

## Componentes

### 1. Resolver central — `choice_resolver.py`

```python
@dataclass
class Resolution:
    field: str               # "Type of Trucker"
    value: str               # opción elegida de Progressive
    kind: str                # "MATCHED" | "DEFAULTED"
    source_value: str | None # lo que traía el Blue Quote (None si ausente)
    note: str = ""           # "exact" | "mapping" | "token" | "generic" | "default"

def resolve_choice(
    field: str,
    source_value: str | None,
    options: list[str],
    mapping: dict[str, str] | None = None,
    default: str | None = None,
    generic_aliases: frozenset[str] = frozenset(),
) -> Resolution:
    ...
```

**Lógica de decisión:**

1. `source_value` **presente**:
   - Match confiado contra `options`, en orden:
     1. entrada explícita en `mapping` (normalizada upper/trim),
     2. match exacto contra una opción,
     3. token fuerte: palabra clave de `source_value` (≥3 chars) que aparece
        en exactamente una opción.
   - Si `source_value` ∈ `generic_aliases` y hay catch-all en `options` →
     `MATCHED` nota "generic".
   - Si nada matchea con confianza → **`raise UnmappableValueError(field,
     source_value, options)`**. Nunca cae a catch-all silencioso.
2. `source_value` **ausente**:
   - `default` provisto → `Resolution(kind="DEFAULTED", value=default)`.
   - sin `default` (campo crítico) → `raise UnmappableValueError`.

**Regla clave (mata el whack-a-mole):** `"General Freight / Other"` y
`"Other / Not Listed"` dejan de ser cajón de sastre. Solo se eligen si el
`source_value` es genuinamente genérico (vía `generic_aliases`). Valores como
"PACKED CHARCOAL" o "sand & gravel" ya no caen ahí en silencio — HALT.

**Matching confiado vs guess:** un match es confiado si proviene de (a) tabla
explícita, (b) exacto, o (c) token único ≥3 chars. Un token que aparece en
≥2 opciones es ambiguo → NO es confiado → HALT (no se adivina cuál).

### 2. `UnmappableValueError` — en `pages/_exceptions.py`

Extiende la familia existente, por lo que ya trae
`field/attempts/screenshot_path/debug_context` y se integra con el reporte de
error actual. Campos propios: `source_value`, `available_options`. En uso
offline (preflight) `screenshot_path` es `None`.

### 3. Catálogos — `catalogs/*.json` + `catalogs.py`

Un JSON por campo, sembrado de los DIAG dumps existentes, con metadata de
captura:

```json
{
  "field": "Type of Trucker",
  "captured": "2026-06-04",
  "source": "DIAG JUAREZ run",
  "options": ["Agricultural", "Dirt, Sand and Gravel",
              "General Freight / Other", "Logging / Wood Chips"],
  "generic_aliases": ["general freight", "mixed", "other"]
}
```

`catalogs.py`: `load_catalog(name) -> Catalog` con cache. `catalogs/README.md`
documenta cómo refrescar un JSON a mano desde un nuevo DIAG dump cuando
Progressive cambia sus opciones. El fail-fast in-flight es el backstop si un
catálogo quedó stale.

Archivos iniciales: `business_type.json`, `type_of_trucker.json`,
`vehicle_tiles.json`.

### 4. Preflight — `preflight.py`

```python
def run_preflight(mapped: MappedFields) -> PreflightReport: ...

@dataclass
class PreflightReport:
    blockers: list[Blocker]        # UnmappableValueError capturados, NO propagados
    assumptions: list[Resolution]  # DEFAULTED
    def ok(self) -> bool: return not self.blockers
```

Corre **antes de abrir el browser**. Pasa cada campo de alto dolor por
`resolve_choice` con el catálogo como `options`, captura `UnmappableValueError`
(en vez de propagar) y **junta todos** los blockers en una pasada — no
fail-fast. Imprime a consola **y** escribe `logs/progressive_preflight_<business>.json`.

Formato del reporte:

```
PREFLIGHT — NOBLE LOGISTICS LLC
❌ 2 blockers (resolvé antes de re-correr):
  • commodity: "PACKED CHARCOAL" no matchea ninguna opción de Business Type.
      Candidatas cercanas: Garbage & Trash, General Freight / Other
      Acción: agregá un mapping o corregí el Blue Quote.
  • vehicle[2].type: "DUMP TRUCK - SAND" no matchea ningún tile.
      Tiles disponibles: Dump Truck, Truck Tractor, Pickup Truck, ...
⚠️ 3 suposiciones (campos ausentes, default aplicado):
  • gvw = "26,001 lbs or greater"   • radius = "Over 500 miles"
```

Si `not report.ok()`, `quote_flow` **no abre el browser** — entrega el reporte
y termina. Cero sesiones quemadas a mitad de camino.

Lo que el preflight NO valida offline (campos cascada que solo aparecen live,
p.ej. el límite MTC revelado post-commodity) queda para el fail-fast in-flight.

### 5. Integración en los 3 guess-sites

Cada sitio delega en `resolve_choice`. **In-flight, `options` se enumera en
vivo de la página**, no del catálogo — así nunca clickea un tile inexistente y
el diagnóstico muestra lo que realmente había en pantalla.

```python
# vehicles_page.py — DESPUÉS
async def select_vehicle_type(self, trailer_type):
    options = await self._enumerate_tiles()   # lo que REALMENTE hay en pantalla
    res = resolve_choice("vehicle tile", trailer_type, options,
                         mapping=VEHICLE_TILE_MAP)
    await self.page.get_by_text(res.value, exact=True).first.click(force=True)
```

Mismo patrón para `_map_commodity_to_option` y `_answer_type_of_trucker` (que
hoy clickea "la primera no-vacía"). Las tablas de mapeo pasan a ser datos
explícitos (`VEHICLE_TILE_MAP`, `COMMODITY_MAP`).

### 6. AssumptionLog (in-flight) — en `quote_flow.py`

Objeto liviano que se pasa por el flow. Cada `Resolution.kind == "DEFAULTED"`
se acumula. Al terminar el quote se adjunta al resultado:

```
✅ Quote CA117062906 — $107,431/yr
   Suposiciones aplicadas (revisá el precio):
     • gvw = 26,001 lbs or greater   • radius = Over 500 miles
```

Una cotización "verde" que descansó en 5 defaults ya no se ve idéntica a una
donde todo vino del Blue Quote.

### 7. HALT in-flight

`UnmappableValueError` se propaga a `quote_flow`, que ya maneja la familia de
excepciones (screenshot + debug_context → reporte de error). Solo hay que
registrar el nuevo tipo en el `except`.

## Testing

- `tests/progressive/test_choice_resolver.py` — lógica pura, sin browser:
  match exacto, por mapping, genérico+catch-all, presente-sin-match → HALT,
  ausente+default → DEFAULTED, ausente-crítico → HALT, token ambiguo → HALT.
- `tests/progressive/test_preflight.py` — MappedFields limpio → 0 blockers;
  commodity no mapeable → 1 blocker + browser no abre; mix → junta TODOS los
  blockers en una pasada, suposiciones aparte. Fixtures usan catálogos reales.
- `tests/progressive/test_catalogs.py` — cada JSON carga, `options` no vacío,
  metadata presente.
- **No-regresión:** 81 tests actuales verdes; simulador sigue dando
  `success=True $53,064/yr` (M&D no toca los 3 campos con valores no
  mapeables).

Por primera vez hay cobertura del matching **sin run live** — la raíz de por
qué hoy cada cliente nuevo es una sorpresa.

## Fuera de alcance (specs posteriores)

- Migrar los guess-sites de las otras 5 pages al resolver.
- Crawler automático de catálogos (las opciones son cascada/dinámicas — YAGNI).
- Bug UI de `_configure_non_owned_trailer_phys_damage` (combo de límite no se
  encuentra).
- Trailer flow real (PR-B Phase 1, Tasks 10-12) — independiente de este spec.

## Refs

- Spec basepage: `docs/superpowers/specs/2026-06-02-progressive-basepage-hardening-design.md`
- CLAUDE.md — reglas Progressive (primitivas obligatorias, CONDITIONAL fields)
