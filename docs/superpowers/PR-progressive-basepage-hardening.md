# PR Title

```
Progressive BasePage hardening: FULL CLOSE — RYD $44,621 con MTC (8/8 pages)
```

# PR Body

## Summary

- Codifica las reglas ExtJS-safe de Progressive en primitivas obligatorias de `BasePage` (`safe_fill`, `safe_radio`, `safe_checkbox`, `safe_select_combo`, `safe_click_continue`, `wait_for_extjs_idle`, `find_*`, `field_exists`, etc.). 5 familias, 14 primitivas, errores estructurados.
- **Migra las 8 de 8 pages** al modelo de primitivas + `REQUIRED/CONDITIONAL/OPTIONAL` field classification. Cada page declara sus campos condicionales y usa `field_exists` para soft-skip.
- Implementa MTC completo para Distributor: 3 Yes/No subform + commodity picker inline (Type → Commodity cascading) + limit combobox revelado post-commodity. Formato Progressive `$Xk with a $Y Deductible`.
- Resuelve 16 issues live-discovered desde Phase 6 partial close: CONDITIONAL fields (ELD, ProView, owns_goods, USDOT-belongs, Comp/Coll), MTC subform completo, safe_select_combo tolerant matching, viewport/force regression, _expand_coverage smart toggle, Recalculate retry loop.
- **RYD LLC cotiza end-to-end con MTC**: `$44,621/year`, Quote `#CA117054124`. M&D sin regresión: `$53,064/year`.

## Scope

**FULL refactor — 8 de 8 pages migradas.** 44 commits sobre baseline `94cd256`. 40 tests unitarios (`tests/progressive/`). Simulador sin regresión.

Pages migradas: `base_page.py`, `business_info_page.py`, `coverages_rates_page.py`, `drivers_page.py`, `final_details_page.py`, `home_page.py`, `login_page.py`, `more_business_page.py`, `vehicles_page.py`.

## Discoveries durante implementación

- **USDOT 'belongs to customer' CONDITIONAL**: auto-confirmado para DOT recientemente cotizado en sesión — el radio puede no aparecer.
- **AddVehicle Comp/Coll cascading**: radio se revela después de loan=No con timing fix via `wait_for_field_revealed_by`.
- **MTC Distributor subform**: 3 Yes/No (mobile homes, business docs, refrigeration) + commodity picker inline (Type+Commodity cascading) + limit revealed POST-commodity.
- **MTC limit format**: `$Xk with a $Y Deductible` (k-notation + combined deductible). Helper `_build_mtc_limit_preferences` mapea `$100,000` → `$100k with a $1,000 Deductible`.
- **_expand_coverage smart toggle**: Progressive cachea expanded state entre quotes del mismo USDOT — verificar marker antes de hacer click.
- **safe_select_combo tolerant matching**: exact match → partial match + verificación bidireccional (option_text ↔ input_value).
- **Recalculate race condition**: compite con 'Done with this coverage' → retry loop 3x + poll de premium materialization.
- **Viewport paradox**: `force=True` en primer click de botones largos saltea auto-scroll de Playwright. Natural click primero, `force=True` solo en retries.

## Test plan

- [x] 40 unit tests en `tests/progressive/` pasan (`pytest tests/progressive/ -v`)
- [x] Simulador `tests/simulate_progressive.py` completa OK
- [x] Live M&D CUSTOM FREIGHT LLC: $53,064/year (sin regresión)
- [x] Live RYD LLC Beverage Distributor: **$44,621/year, Quote #CA117054124** — incluye MTC $100k with $1,000 Deductible

## Pendientes (PR siguiente)

- Add Trailer flow real (skipeado con WARN)
- Commodity matching refinement para perfiles no-food

## Referencias

- Spec: [`docs/superpowers/specs/2026-06-02-progressive-basepage-hardening-design.md`](docs/superpowers/specs/2026-06-02-progressive-basepage-hardening-design.md)
- Plan: [`docs/superpowers/plans/2026-06-02-progressive-basepage-hardening.md`](docs/superpowers/plans/2026-06-02-progressive-basepage-hardening.md)
- Métricas pre/post: [`docs/superpowers/baselines/2026-06-02-progressive-baseline.md`](docs/superpowers/baselines/2026-06-02-progressive-baseline.md)
- Métricas post-refactor: [`docs/superpowers/baselines/2026-06-03-progressive-post-refactor.md`](docs/superpowers/baselines/2026-06-03-progressive-post-refactor.md)

# Crear PR

URL: https://github.com/programacion-glitch/Quotes/pull/new/progressive-basepage-hardening

Copia el título y el body de arriba.
