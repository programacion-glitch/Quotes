# Progressive Post-Refactor Metrics — 2026-06-02

Capturado post-commit 020e291 (BasePage hardening, partial close).
Solo `more_business_page` completamente migrada a primitivas.
`coverages_rates_page` recibio fix narrow (race condition). Otras pages sin migrar.

| File | Lines | wait_for_timeout (unjustified) | _click_continue locales |
|---|---|---|---|
| `base_page.py` | 549 | 12 | 0 |
| `business_info_page.py` | 831 | 23 | 0 |
| `coverages_rates_page.py` | 429 | 10 | 0 |
| `drivers_page.py` | 271 | 6 | 1 |
| `final_details_page.py` | 71 | 1 | 0 |
| `home_page.py` | 144 | 3 | 0 |
| `login_page.py` | 147 | 0 | 0 |
| `more_business_page.py` | 127 | 0 | 0 |
| `vehicles_page.py` | 639 | 21 | 1 |
| **TOTAL** | **3208** | **76** | **2** |

## Nota sobre cambios de lineas

`base_page.py` crecio de 117 a 549 lineas porque ahora contiene el hub completo de primitivas
(5 familias: localizacion, interaccion, esperas dinamicas, estado, diagnostico).
`more_business_page.py` redujo de 178 a 127 lineas tras migracion a primitivas.
Las demas pages no cambiaron.

## Resultado live validado en este PR

- M&D CUSTOM FREIGHT LLC (Trucker): $53,064/year (sin regresion)
- RYD LLC (Beverage Distributor): **$42,387/year, Quote #CA117049229** (primera vez)
