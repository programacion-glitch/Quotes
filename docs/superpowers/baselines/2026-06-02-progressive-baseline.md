# Progressive Baseline Metrics — 2026-06-02

| File | Lines | wait_for_timeout (unjustified) | _click_continue locales |
|---|---|---|---|
| `base_page.py` | 117 | 0 | 0 |
| `business_info_page.py` | 831 | 23 | 0 |
| `coverages_rates_page.py` | 408 | 11 | 0 |
| `drivers_page.py` | 271 | 6 | 1 |
| `final_details_page.py` | 71 | 1 | 0 |
| `home_page.py` | 144 | 3 | 0 |
| `login_page.py` | 147 | 0 | 0 |
| `more_business_page.py` | 178 | 8 | 1 |
| `vehicles_page.py` | 639 | 21 | 1 |
| **TOTAL** | **2806** | **73** | **3** |

## Tiempos end-to-end live (pre-refactor)

- M&D CUSTOM FREIGHT LLC: <no capturado — requiere ejecución live por el usuario>
- RYD LLC: <no capturado — requiere ejecución live por el usuario>

## Simulator baseline

- Acciones trazadas: 135
- Status: OK
- Nota: el simulador requirió correcciones al MockLocator/MockPage (is_visible, scroll_into_view_if_needed, wait_for_function, page.on, get_by_label(exact=), get_by_placeholder, NOT_FOUND_MARKERS para banners de error). El conteo previo de 83 en memoria es de una versión anterior del módulo; el conteo actual refleja las ~37 mejoras de la sesión 2026-06-02 (más fallbacks robustos por campo).

## Comparativa pre/post refactor (partial close 2026-06-02)

Ver `2026-06-02-progressive-post-refactor.md` para los conteos post-refactor.

| Metrica | Pre | Post | Delta |
|---|---|---|---|
| Total wait_for_timeout (unjustified) | 73 | 76 | +4% (base_page agrego primitivas con waits justificados marcados como "unjustified" por el script) |
| Total _click_continue locales | 3 | 2 | -33% (more_business migrado a safe_click_continue) |
| Total lineas pages/*.py | 2806 | 3208 | +402 (base_page 117→549: hub de primitivas; more_business 178→127: migrado) |

**Status:** PARTIAL refactor. Solo `more_business_page` migrado a primitivas en este PR. `coverages_rates_page` recibio fix narrow (race condition) sin migracion completa. `drivers_page`, `vehicles_page`, `coverages_rates_page` (full), `business_info_page` quedan para un PR siguiente. Las primitivas estan listas y validadas LIVE con dos commodities diferentes (Trucker M&D y Beverage Distributor RYD).

**Nota wait_for_timeout:** El incremento de 73→76 se debe a que `base_page.py` contiene waits internos en primitivas (p. ej. polling de `Ext.Ajax.isLoading()`) que el script cuenta como "unjustified" pero son esperas dinamicas correctas. Los waits en `more_business_page` bajaron de 8 a 0.
