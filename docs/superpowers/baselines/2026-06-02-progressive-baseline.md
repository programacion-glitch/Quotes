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
