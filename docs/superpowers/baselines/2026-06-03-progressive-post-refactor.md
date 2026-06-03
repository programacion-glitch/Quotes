# Progressive Post-Refactor Metrics — 2026-06-03

Capturado con `python tools/capture_baseline_metrics.py` tras FULL CLOSE
del branch `progressive-basepage-hardening` (HEAD `8f033a6`).

| File | Lines | wait_for_timeout (unjustified) | _click_continue locales |
|---|---|---|---|
| `base_page.py` | 574 | 12 | 0 |
| `business_info_page.py` | 840 | 12 | 0 |
| `coverages_rates_page.py` | 1052 | 11 | 0 |
| `drivers_page.py` | 245 | 0 | 0 |
| `final_details_page.py` | 70 | 0 | 0 |
| `home_page.py` | 153 | 0 | 0 |
| `login_page.py` | 159 | 0 | 0 |
| `more_business_page.py` | 127 | 0 | 0 |
| `vehicles_page.py` | 575 | 13 | 1 |
| **TOTAL** | **3795** | **48** | **1** |

## Notas sobre wait_for_timeout post-refactor

El script cuenta como "unjustified" los waits internos en `base_page.py`
(primitivas con polling dinámico de `Ext.Ajax.isLoading()`, `.x-mask`,
`document.readyState`) y los waits de `wait_for_field_revealed_by` en
`coverages_rates_page`. Estos son esperas dinámicas correctas, no magic
sleeps — el contador del script no distingue comentario justificativo.

Comparado con pre-refactor (73 unjustified), la reducción neta es 34%
excluyendo los waits de base_page que son el hub centralizado.

## Live validation (2026-06-03)

- M&D CUSTOM FREIGHT LLC (Trucker, USDOT 2998569): **$53,064/year** (sin regresión)
- RYD LLC (Beverage Distributor, USDOT 4427567): **$44,621/year, Quote #CA117054124**
  — incluye MTC $100k with $1,000 Deductible (Food & Beverage / Other Food & Beverages)
