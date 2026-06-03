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
- **Todas las 8 pages migradas.** NUNCA llamar `page.fill/click/select_option` directamente en código nuevo — usar primitivas.
- **CONDITIONAL fields** — siempre verificar con `field_exists(wait_ms=1500)` antes de `safe_radio`. NUNCA llamar safe_radio sobre un locator que puede no existir (produce RadioStuckError después de 4 retries sin contexto). Campos CONDITIONAL validados live:
  - ELD (presente Trucker, ausente Distributor)
  - Snapshot ProView (ausente Trucker, presente Distributor)
  - owns_goods (presente Distributor)
  - USDOT 'belongs to customer' radio (auto-confirmado para DOT recientemente cotizado — puede no aparecer)
  - AddVehicle Comp/Coll Yes/No (se REVELA tras loan=No — timing fix con `wait_for_field_revealed_by`)
  - MTC subform 3 Yes/No (mobile homes, business docs, refrigeration breakdown)
  - MTC commodity picker inline (Type + Commodity cascading)
  - MTC limit combobox (REVELADO después del commodity)
- **MTC — dos paths por tipo de negocio:**
  - Trucker: limit combobox directo (sin subform)
  - Distributor: 3 Yes/No + commodity picker inline (Type → Commodity en cascada) + limit combobox revelado POST-commodity
  - Formato límite Progressive: `'$Xk with a $Y Deductible'` (k-notation + deductible combinado), NO `$XXX,XXX`
- **safe_select_combo — matching tolerante:** exact match → partial match. Verificar bidireccional (option_text ↔ input_value).
- **_expand_coverage — smart toggle:** detectar si la sección ya está expandida (marker present) antes de hacer click. Progressive cachea expanded state entre quotes del mismo USDOT.
- **Recalculate retry loop:** `_recalculate_if_needed` usa retry loop hasta 3x + poll de premium materialization. Race condition con 'Done with this coverage'.
- **Viewport / force=True:** para botones al final de forms largos (Ok-start-quote, "Enter a different Business Name"), NO usar `force=True` en primer click — Playwright auto-scrolls con click natural. `force=True` solo en retries.
- **Selectores ExtJS comboboxes:** combo.click() → `get_by_role("option", name=value).click()`. NUNCA `select_option()` con ExtJS.
- **STOP en FINAL DETAILS:** el flujo termina en `pageName=AdditionalDetails`. NUNCA click el "Continue" final — avanza a PAYMENT y bind real de la póliza.
- **NoHit es HALT:** si MVR/CLUE falla y Progressive pide SSN → reportar al usuario, no auto-rellenar SSN (data sensible).
- **Effective date:** viene del subject del email con regex `[Ee]ffective\s+date[:\s]+(\d{1,2}/\d{1,2}/\d{4})`.
- **Esperas dinámicas, no `wait_for_timeout` mágicos:** usar `wait_for_extjs_idle`, `wait_for_field_revealed_by`, etc. Si necesitas un `wait_for_timeout(N)` literal, dejá comentario justificando.

## Estado actual (2026-06-03 — FULL refactor closed)

✅ BasePage hub de primitivas ExtJS-safe (5 familias, 14 primitivas, 40 tests unitarios).
✅ 8 de 8 pages migradas a primitivas (M&D y RYD validados live):
   - base_page.py · business_info_page.py · coverages_rates_page.py
   - drivers_page.py · final_details_page.py · home_page.py
   - login_page.py · more_business_page.py · vehicles_page.py
✅ End-to-end LIVE validado:
   - M&D CUSTOM FREIGHT LLC (Trucker): $53,064/year (baseline preservado)
   - RYD LLC (Beverage Distributor): **$44,621/year, Quote #CA117054124**
     — incluye MTC ($100k with $1,000 deductible)
✅ MTC commodity picker para Distributor: Food & Beverage / Other Food & Beverages
✅ Race condition de Recalculate resuelto con retry loop + poll

Próximos PRs candidatos:
- Add Trailer flow real (sigue skipeado con WARN)
- Refinement de commodity matching para otros perfiles (ej. PACKED CHARCOAL no fue elegido — el bot seleccionó "Other Food & Beverages" como cobertura general)

## Env vars requeridas

Ver `docs/AGENTS_CONTEXT.md` sección "Env vars requeridas". Variables van en `.env` (no commitear).
