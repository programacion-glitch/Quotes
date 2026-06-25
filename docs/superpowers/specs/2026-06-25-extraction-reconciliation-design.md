# Spec — Doble validación por reconciliación form ↔ IA (Blue Quote)

- **Fecha:** 2026-06-25
- **Origen:** Diana/usuario reportaron que una Blue Quote con **4 drivers** terminó con **2** en la cotización de Progressive.
- **Causa raíz:** el extractor **form-based** (`BlueQuotePDFExtractor`) lee los campos del PDF rellenable y saca los 4 drivers correctamente (verificado live sobre la Blue Quote de ELITE). El subconteo viene del **fallback de IA/visión** (`_extract_blue_quote_with_ai`), que se usa cuando la Blue Quote es plana/escaneada o cuando el form se considera "insuficiente", y que es **no-determinista** (puede subcontar listas).

## Objetivo

Eliminar el subconteo de listas (drivers / unidades) y los datos faltantes que produce el fallback de IA, corriendo **ambos** extractores sobre la Blue Quote y **reconciliando** sus salidas con una precedencia clara (**form autoritativo, IA llena huecos**), **auto-corrigiendo** y logueando las discrepancias. No frena la cotización (el usuario eligió auto-corregir y seguir).

## Alcance

- **Campos cruzados de verdad** (lo que ambos extractores producen hoy): `drivers` (lista), **conteo total de unidades**, `commodity`, `coverages`, y campos escalares del negocio (business_name, usdot, owner, **email**, etc.).
- Los registros detallados de vehículos/trailers quedan **form-autoritativos** (la IA solo aporta un total para cruzar — su prompt devuelve `unit_count` + `trailer_types`, no registros completos).

## Fuera de alcance (YAGNI)

- NO separa power-units vs trailers (eso es ítem del rule engine, se trata aparte).
- NO frena para revisión manual (el usuario eligió **auto-corregir y seguir**).
- NO audita campos que la IA no extrae.
- NO toca el rule engine ni GEICO.

## Arquitectura

### Componente nuevo: `modules/extraction_reconciler.py`

Función **pura** (sin red, sin estado), fácil de testear:

```
reconcile(form: dict | None, ai: dict | None) -> tuple[dict, list[Discrepancy]]
```

- `form` = salida del `BlueQuotePDFExtractor` ya mapeada a las estructuras del perfil (drivers, units, commodity, coverages, applicant scalars), o `None`/vacío si el form no aplicó (PDF plano).
- `ai` = salida del extractor de IA (mismos campos en lo que extrae), o `None` si la IA falló / proxy caído.
- Devuelve el dict **reconciliado** + una lista de `Discrepancy(field, form_value, ai_value, resolution)` para loguear.

### Integración en `document_ai_extractor.py`

El bloque de Blue Quote (hoy ~L920–965: "form; si insuficiente → IA fallback") pasa a:

1. Correr el **form extractor** → `form_fields` (best-effort; si raise → `None`).
2. Correr el **IA extractor** → `ai_fields` (best-effort; si raise/timeout/proxy-down → `None`). Refactor: `_extract_blue_quote_with_ai` debe **devolver** la data estructurada en vez de mutar `profile` directamente (o correr sobre un perfil temporal), para poder reconciliar.
3. `reconcile(form_fields, ai_fields)` → asignar el resultado a `profile`.
4. Loguear cada discrepancia/override con una línea clara.

## Flujo de datos

```
Blue Quote PDF
   ├── BlueQuotePDFExtractor.extract()  → form_fields (o None si plano/raise)
   └── _extract_blue_quote_with_ai()    → ai_fields  (o None si falla/proxy down)
                         │
                         ▼
            reconcile(form_fields, ai_fields)
                         │
            ▼ perfil reconciliado + [discrepancias]
              (logueadas; profile.* asignado)
```

## Reglas de reconciliación (form autoritativo, IA llena huecos)

- **Escalares** (business_name, usdot, owner_name, owner_age, email, commodity, business_years, is_new_venture): si el **form** tiene valor no vacío → form; si no → IA.
- **Listas / conteos** (drivers, conteo de unidades):
  - form tiene ≥1 → **gana el form** (tabla estructurada, completa).
  - form vacío (PDF plano) → **IA**.
  - conteos difieren (p.ej. form=4 drivers, IA=2) → **loguear discrepancia y gana el form**.
  - IA encontró **más** que el form (posible fila que el parser del form se saltó) → loguear **WARNING** para visibilidad (gana el form igual, pero queda registrado).
- **coverages**: precedencia form; si el form está vacío, IA.

## Manejo de errores (degradación graceful)

- IA falla / proxy caído → `ai=None` → **form-only** (= comportamiento actual cuando el form sirve). La IA es **best-effort**: nunca rompe la extracción.
- Form vacío / raise (PDF plano/escaneado) → **IA-only** (= fallback actual).
- Ambos vacíos → cae al manejo de "datos insuficientes" actual (baja confianza / halt actual).

## Auto-corrección + visibilidad

- Cada override/relleno imprime una línea: `[reconcile] drivers: form=4, IA=2 → uso form (4)`.
- Las discrepancias quedan en el log de la corrida. (Opcional futuro: nota en el correo de análisis; no en este alcance.)

## Costo

- 1 llamada de IA extra por Blue Quote (antes la IA solo corría en fallback). El proxy de IA es local (`host`/contenedor → :3000) → costo despreciable.

## Testing (función pura, determinista, sin red)

Unit de `reconcile()`:
1. form 4 drivers + IA 2 drivers → reconciliado **4** + discrepancia logueada (caso ELITE).
2. form vacío + IA 3 drivers → **3** (IA).
3. form commodity="X" + IA commodity="Y" → **"X"** (form).
4. `ai=None` (IA falló) → todo del form.
5. `form=None` (plano) → todo de IA.
6. relleno de hueco: form sin email + IA con email → **email de IA**.
7. conteo de unidades form≠IA → form + WARNING de discrepancia.

Integración (opcional, con doubles): el bloque de `document_ai_extractor` llama a ambos extractores y a `reconcile`, y degrada bien cuando uno devuelve `None`.

## Criterios de éxito

- Una Blue Quote rellenable con N drivers/unidades produce **N** en el perfil, aunque la IA subcontara.
- Si la IA falla o el proxy está caído, la extracción sigue funcionando (form-only).
- Las discrepancias quedan visibles en el log.
- Cero regresiones en la suite existente.
