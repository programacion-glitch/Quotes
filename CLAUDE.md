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

- **Selectores ExtJS**: comboboxes Sencha NO son `<select>`. Patrón obligatorio: `combo.click()` → `get_by_role("option", name=value).click()`. NUNCA `select_option()` con ExtJS.
- **STOP en FINAL DETAILS**: el flujo termina en `pageName=AdditionalDetails`. NUNCA click el "Continue" final — avanza a PAYMENT y bind real de la póliza.
- **NoHit es HALT**: si MVR/CLUE falla y Progressive pide SSN → reportar al usuario, no auto-rellenar SSN (data sensible).
- **Effective date**: viene del subject del email con regex `[Ee]ffective\s+date[:\s]+(\d{1,2}/\d{1,2}/\d{4})`.

## Estado actual (2026-05-26)

✅ End-to-end automatizado y validado live con USDOT real (M&D CUSTOM FREIGHT LLC).
✅ Precio capturado en `$53,064/year` (Quote # CA116960411).
✅ Simulador pasa con 83 acciones trazadas.
⚠️  Hay ~1500 líneas de cambios sin commit en `modules/progressive/`.

## Env vars requeridas

Ver `docs/AGENTS_CONTEXT.md` sección "Env vars requeridas". Variables van en `.env` (no commitear).
