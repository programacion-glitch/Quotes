# Progressive — Amount Normalization + GVW/Value Fail-Loud

**Fecha:** 2026-06-04
**Estado:** Diseño aprobado, pendiente plan de implementación
**Branch destino:** progressive-basepage-hardening (o branch nuevo)
**Continúa:** `2026-06-04-progressive-fail-loud-mapping-design.md`

## Problema

El live run de REPUBLIC AGGREGATE HAULERS (commodity SAND & GRAVEL, 2× Dump
Truck) confirmó que el feature fail-loud anterior funciona — el commodity
resolvió a "Dirt Sand & Gravel (For A Fee)" y el tile a "Dump Truck" (el break
histórico de REPUBLIC). Pero destapó el siguiente bloqueo, en el AddVehicle form:

- **GVW** `"51.000 LBS"` → `safe_select_combo` no matchea ninguna opción → WARN
  y sigue → campo required vacío (amarillo en el screenshot).
- **Value** `"$45.000"` → `field_mapper` lo normaliza a `"45.000"` (mantiene el
  punto) → ExtJS lo formatea como `$45` → "must be greater than $100".
- Resultado: `safe_click_continue: URL still contains 'AddVehicle' after 4
  attempts` — un error críptico, síntoma de dos required vacíos/inválidos.

Causa raíz (confirmada por screenshot `logs/progressive_error_vehicles.png`): el
PDF usa **punto como separador de miles** (formato latino): `"51.000 LBS"` =
51,000 lbs; `"$45.000"` = $45,000. La extracción/normalización lo trata como
decimal.

Dos problemas:
1. **Normalización de números** — no se distingue punto-miles (latino) de
   punto-decimal (US). Los Blue Quotes vienen **mixtos** (US y latino, según
   quién los llena).
2. **GVW es un dropdown de rangos** — incluso con el número normalizado (51000),
   hay que ubicarlo en su bucket ("26,001 lbs or greater"); hoy el mapper pasa el
   string crudo. Además GVW/value hacen WARN-and-continue silencioso en vez de
   fallar fuerte.

## Decisiones de diseño (acordadas con el usuario)

1. **Objetivo primario:** procesar TODA la data del Blue Quote y cotizar. HALT
   es la red de seguridad para datos genuinamente inusables, NO el primer
   recurso. Con el normalizador, el caso REPUBLIC se procesa y cotiza (no HALT).
2. **Formato de números MIXTO** — el normalizador maneja US (`$45,000.00`) y
   latino (`$45.000`), detectando por contexto.
3. **GVW ausente → default `"26,001 lbs or greater"`** (assumption, no HALT — la
   mayoría de camiones comerciales caen ahí). HALT solo si GVW viene pero no
   parsea o no entra en ningún bucket.
4. **Value ausente → no-APD** (ya existe). HALT solo si viene pero, ya
   normalizado, es inusable (< $100 o no parsea).
5. **Opciones de GVW** se capturan vía **DIAG en vivo** (como Type of Trucker).
6. **Enfoque A:** normalizar en `field_mapper` + resolvers numéricos dedicados,
   preflight-checked. NO tocar el extractor.

## Arquitectura

```
modules/progressive/
├── amounts.py            # NUEVO — parse_amount(raw) -> float | None
├── gvw.py                # NUEVO — bucket_gvw(weight, options) -> str (o HALT)
├── catalogs/gvw.json     # NUEVO — opciones del combo GVW (sembrado vía DIAG)
├── field_mapper.py       # normaliza GVW + value con parse_amount; MappedVehicle.gvw_weight
├── preflight.py          # + _check_gvw, _check_value
└── pages/vehicles_page.py# GVW via bucket_gvw (live options); value validado; fail-loud
```

## Componentes

### 1. Normalizador — `amounts.py`

```python
def parse_amount(raw: str | None) -> float | None:
    """'51.000 LBS' -> 51000 · '$45,000.00' -> 45000.0 · '$45.000' -> 45000
       '45.5' -> 45.5 · '1.500.000' -> 1500000 · vacío/basura -> None"""
```

**Reglas (en orden):**
1. Limpiar: quitar todo salvo dígitos, `,`, `.`. Si no queda dígito → `None`.
2. Sin separadores → entero directo.
3. Ambos `,` y `.` presentes → el que aparece **último** es decimal, el otro es
   miles. Quitar miles, decimal → `.`. (`"45,000.00"` → 45000.0;
   `"45.000,50"` → 45000.5.)
4. Un solo tipo de separador:
   - aparece **> 1 vez** → miles → quitar todos. (`"1.500.000"` → 1500000.)
   - aparece **1 vez**, **exactamente 3 dígitos detrás** → miles. (`"51.000"` →
     51000; `"1,500"` → 1500.)
   - aparece **1 vez**, **1-2 dígitos detrás** → decimal. (`"45.5"` → 45.5;
     `"45.00"` → 45.0.)
   - aparece **1 vez**, **4+ dígitos detrás** → decimal (mantener; caso raro).

Regla clave: **3 dígitos detrás = miles; 2 = centavos.** Distingue `"$45.000"`
(latino → 45000) de `"$45.00"` (US centavos → 45). Pura, sin estado, testeable.

### 2. GVW — `gvw.py` + `catalogs/gvw.json`

`catalogs/gvw.json` (sembrado vía DIAG; opciones reales del combo):
```json
{
  "field": "Gross vehicle weight",
  "captured": "<fecha DIAG>",
  "source": "DIAG <cliente> run",
  "options": ["10,000 lbs or less", "10,001 - 26,000 lbs", "26,001 lbs or greater"]
}
```
*(las opciones exactas salen del DIAG; el ejemplo es ilustrativo)*

```python
def bucket_gvw(weight: float | None, options: list[str]) -> str:
    """Ubica `weight` en el bucket de rango que lo contiene. Parsea los labels
    del catálogo/live a rangos numéricos (sin hardcodear boundaries):
      '26,001 lbs or greater' -> (26001, inf)
      '10,001 - 26,000 lbs'   -> (10001, 26000)
      '10,000 lbs or less'    -> (0, 10000)
    weight None o fuera de todo rango -> raise UnmappableValueError."""
```

Parseo de labels: extrae los números (vía `parse_amount`), y según el patrón del
label ("or greater" / "or less" / "X - Y") arma `(min, max)`. Deriva los rangos
de los labels mismos → si Progressive cambia los buckets, el DIAG refresca el
JSON y `bucket_gvw` se adapta.

**In-flight** enumera opciones live del combo GVW (autoritativo); el catálogo es
para preflight offline.

### 3. Value — validación fail-loud

En `field_mapper`, la columna Value se normaliza con `parse_amount`. La
validación (en field_mapper / preflight):
- value ausente → `None` → no-APD (existente).
- value presente, `parse_amount` → `None` (basura) → HALT.
- value presente, número `< 100` (piso Progressive "must be greater than $100")
  → HALT.
- value presente, número `>= 100` → se procesa (se llena en el textbox).

HALT: `UnmappableValueError` field=`"Vehicle value"`, source_value=el crudo.

### 4. Integración

- **`field_mapper._map_vehicle`** — usa `parse_amount`:
  - GVW: nuevo campo `MappedVehicle.gvw_weight: float | None` (peso numérico);
    se mantiene `gvw: str` (label, default `"26,001 lbs or greater"` cuando
    ausente).
  - value: `MappedVehicle.value` pasa a ser el número limpio (reemplaza la
    normalización digits+"." actual que produce `"45.000"`).
- **`preflight.py`** — `_check_gvw` (si `gvw_weight` presente, intenta
  `bucket_gvw` contra `gvw.json`; si HALTea → Blocker) y `_check_value` (value
  presente < 100 o no-parseable → Blocker). Juntan blockers en la misma pasada.
- **`vehicles_page`** (AddVehicle) — GVW: enumera opciones live → `bucket_gvw` →
  `safe_select_combo(combo, bucket)`; si `bucket_gvw` HALTea, propaga
  `UnmappableValueError` (fail-loud, ya manejado por quote_flow). Value: usa el
  número validado; si inválido → HALT.
- **DIAG (paso del plan)** — bloque temporal en `vehicles_page` que dumpea las
  opciones del combo GVW; una corrida live captura → sembramos `gvw.json` → se
  remueve el DIAG.

## Testing (todo offline)

- `tests/progressive/test_amounts.py` — batería US/latino: `51.000 LBS`,
  `$45,000.00`, `$45.000`, `$45.000,50`, `1.500.000`, `1,500`, `45.5`, `45.00`,
  `""`/basura → None.
- `tests/progressive/test_gvw_bucket.py` — 51000→"26,001 or greater",
  8000→"10,000 or less", 15000→"10,001 - 26,000", None→HALT, peso fuera de
  rango→HALT, parseo de labels.
- `tests/progressive/test_value_validation.py` — value válido procesa,
  `<100`→HALT, ausente→no-APD, basura→HALT.
- `tests/progressive/test_preflight.py` (extender) — GVW/value malos → blocker;
  REPUBLIC normalizado (`51.000 LBS` + `$45.000`) → preflight pasa (procesa).
- **No-regresión:** 118 tests actuales verdes; simulador `success=True
  $53,064`.

## Fuera de alcance (YAGNI / specs posteriores)

- Normalizar otros campos numéricos fuera de GVW/value.
- Normalizar en el extractor (se hace en field_mapper).
- Migrar los WARN-and-continue de otros campos del AddVehicle form (tonnage,
  driving wheels, etc.) — sólo GVW + value en este spec.

## Refs

- Feature anterior: `docs/superpowers/specs/2026-06-04-progressive-fail-loud-mapping-design.md`
- Evidencia live: `logs/progressive_error_vehicles.png` (REPUBLIC AGGREGATE)
- Catálogos: `modules/progressive/catalogs/README.md`
