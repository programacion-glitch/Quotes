# H2O Quote RPA — Project Context

Sistema de automatización de cotizaciones de seguro comercial de auto para
H2O Commercial Insurance. Lee correos con Blue Quotes, extrae datos con
DocumentAI, evalúa elegibilidad por MGA con un rule engine, y dispatcha
a cada MGA (la mayoría por email, **Progressive vía web automation con Playwright**).

## Arquitectura clave

```
workflow_orchestrator.py          # entrypoint
├── modules/quote_profile.py     # QuoteProfile dataclass (single source of truth)
├── modules/document_ai_extractor.py  # IA + fallback BlueQuote
├── modules/rule_engine.py       # Elegibilidad MGA por reglas
└── modules/progressive/         # Web automation (this is the active focus)
    ├── client.py                # ProgressiveClient entrypoint
    ├── quote_flow.py            # Orquestador end-to-end
    ├── field_mapper.py          # QuoteProfile → MappedFields
    ├── otp_reader.py            # Gmail IMAP para OTP
    └── pages/                   # Page Object Model (Playwright)
        ├── login_page.py
        ├── home_page.py
        ├── business_info_page.py
        ├── vehicles_page.py
        ├── drivers_page.py
        ├── more_business_page.py
        ├── coverages_rates_page.py    # ⭐ donde se captura el precio
        └── final_details_page.py      # STOP HERE (no PAYMENT)
```

## Documentos importantes (leer al retomar)

1. **`docs/AGENTS_CONTEXT.md`** — Contexto histórico del módulo Progressive, hallazgos live, decisiones
2. **`docs/Progressive Variables Obligatorias.md`** — Qué campos debe traer la Blue Quote para cotizar
3. **`docs/Proceso Progressive.md`** — Diagrama original del flujo (si existe)
4. **`docs/superpowers/plans/2026-04-09-progressive-module.md`** — Plan original de implementación

## Comandos útiles

```bash
# Setup en máquina nueva
pip install -r requirements.txt
playwright install chromium

# Simulador end-to-end (sin tocar red, valida estructura del flow)
python tests/simulate_progressive.py

# Tests unitarios
python -m pytest tests/test_rule_engine.py
```

## Reglas para Progressive (web automation)

- **BasePage primitivas** (`modules/progressive/pages/base_page.py`): `safe_fill`, `safe_radio`, `safe_checkbox`, `safe_select_combo`, `safe_click_continue`, `find_by_label_text`, `find_by_placeholder`, `find_radiogroup`, `find_combo`, `field_exists`, `wait_for_extjs_idle`, `wait_for_page`, `wait_for_field_revealed_by`, `wait_for_currency_formatted`, `remove_overlays`, `blur_active_element`, `current_page_token`, `screenshot`, `dump_debug_context`. Ver spec `docs/superpowers/specs/2026-06-02-progressive-basepage-hardening-design.md`.
- **Migración por page:** `more_business_page` ya usa primitivas + `REQUIRED/CONDITIONAL/OPTIONAL` fields. Otras pages (`drivers_page`, `vehicles_page`, `coverages_rates_page`, `business_info_page`, `home_page`, `login_page`, `final_details_page`) aún usan código pre-refactor — funcionan pero no usan primitivas. Migración pendiente en PR siguiente.
- **Campos condicionales por commodity:** declarar en `CONDITIONAL_FIELDS` + usar `field_exists` para soft-skip. Ejemplos validados live: ELD ausente para Beverage Distributor, Snapshot ProView ausente para Trucker pero presente para Distributor.
- **STOP en FINAL DETAILS:** el flujo termina en `pageName=AdditionalDetails`. NUNCA click el "Continue" final — avanza a PAYMENT y bind real de la póliza.
- **NoHit es HALT:** si MVR/CLUE falla y Progressive pide SSN → reportar al usuario, no auto-rellenar SSN (data sensible).
- **Effective date:** viene del subject del email con regex `[Ee]ffective\s+date[:\s]+(\d{1,2}/\d{1,2}/\d{4})`.
- **Esperas dinámicas, no `wait_for_timeout` mágicos:** usar `wait_for_extjs_idle`, `wait_for_field_revealed_by`, etc. Si necesitas un `wait_for_timeout(N)` literal, dejá comentario justificando.
- **MTC subform pending:** para Beverage Distributor, Motor Truck Cargo pide preguntas extra antes del limit combobox. Actualmente se skipea con WARN — cotización completa SIN MTC. Investigación pendiente.

## Estado actual (2026-06-02 — partial refactor closed)

✅ BasePage hub de primitivas ExtJS-safe listo (5 familias, 40 tests unitarios).
✅ `more_business_page` migrado a primitivas — arregla bug RYD ELD + nuevo Snapshot ProView CONDITIONAL.
✅ `coverages_rates_page` con fix narrow: `wait_for_extjs_idle` en `_recalculate_if_needed` + `capture_price` — arregla race condition de price capture.
✅ End-to-end LIVE validado:
   - M&D CUSTOM FREIGHT LLC (Trucker): $53,064/year
   - RYD LLC (Beverage Distributor): **$42,387/year, Quote #CA117049229** (primera vez)
⚠️  Migración pendiente: `drivers_page`, `vehicles_page`, `coverages_rates_page` (full), `business_info_page`, `home_page`, `login_page`, `final_details_page`. Funcionan, no usan primitivas todavía.
⚠️  MTC subform discovery pendiente para Beverage Distributor.
⚠️  Add Trailer flow real pendiente.

Próximos PRs candidatos:
- Migrar pages restantes a primitivas (cierra los criterios #3 y #4 del spec).
- Descubrir MTC subform para distributors.
- Add Trailer flow real.

## Env vars requeridas

Ver `docs/AGENTS_CONTEXT.md` sección "Env vars requeridas". Variables van en `.env` (no commitear).
