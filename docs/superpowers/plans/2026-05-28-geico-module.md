# Plan: GEICO Commercial Auto Module

> **Status**: in progress (2026-05-28). Block 1 first.
> **Reference**: `docs/Proceso GEICO.md` for live-mapped flow; `modules/progressive/` for patterns to mimic.

## Goal

Replicate Progressive's architecture for GEICO — given a `QuoteProfile`, log in, run the wizard, capture quote price + PDF, STOP before MVR & CLUE / Payment.

```
GEICOClient.create_quote(profile, effective_date) -> QuoteResult
```

## Architectural decisions (fixed)

- **Async Playwright** (same as Progressive)
- **Page Object Model**, label-based selectors when possible, JS-set fallback for ExtJS/custom comboboxes
- **`field_mapper.py` central** — all the 7 rules from `feedback-field-mapper-rules.md` applied here
- **HALT early** if USDOT/ZIP "Not Eligible" or critical field missing — don't waste session
- **STOP at Final Quote Details** — no click on the Next that goes to MVR
- **PDF deliverable** via JS `fetch + credentials:include` + base64 decode → save to `data/output/`
- **OTP via Gmail IMAP** — reuse `modules/progressive/otp_reader.py` (same Gmail account)

## Block 1 (this iteration): scaffold + auth + dashboard

Files:

| File | LOC | Purpose |
|---|---|---|
| `modules/geico/__init__.py` | 1 | Empty marker |
| `modules/geico/client.py` | ~140 | `GEICOClient.create_quote()`, `GEICOConfig.from_env()` |
| `modules/geico/quote_flow.py` | ~80 | `QuoteFlow.run()` — Block 1 reaches dashboard only |
| `modules/geico/field_mapper.py` | ~180 | `MappedFields` dataclass + `map_profile_to_fields()`. Block 1 fields only (usdot, zip, business_name, owner, basics) — Block 2/3 extend with vehicles/drivers/coverages |
| `modules/geico/otp_reader.py` | ~30 | Thin re-export of `GmailOTPReader` from Progressive |
| `modules/geico/pages/__init__.py` | 1 | Empty marker |
| `modules/geico/pages/base_page.py` | ~130 | Helpers + screenshot to `logs/geico_*.png` |
| `modules/geico/pages/login_page.py` | ~150 | Azure B2C login + MFA Email path |
| `modules/geico/pages/dashboard_page.py` | ~200 | Commercial Auto checkbox + USDOT eligibility + ZIP eligibility + Start New Quote → new tab |

After Block 1: `python -c "from modules.geico.client import GEICOClient"` succeeds, but `create_quote()` will stop early ("Block 1 stops at dashboard").

## Block 2: Steps 1-3

Page objects:
- `business_class_page.py` (Step 1)
- `business_owner_page.py` (Step 2)
- `vehicles_page.py` (Step 3 — VIN decode, sub-pages, summary)

Extend `field_mapper.py` with: vehicle mapping, ELD default, business class mapping (use AI commodity classifier).

## Block 3: Steps 4-5b

- `drivers_page.py` (Step 4 — placeholder + add real + summary)
- `additional_business_page.py` (Step 5)
- `driveeasy_page.py` (Step 5b — always `Continue without`)

Extend `field_mapper.py` with: driver mapping with owner-excluded logic, years-with-insurer, BI limits.

## Block 4: Steps 6-7 + deliverable

- `coverages_page.py` (Step 6 — premium capture + the page where Quote#/price live)
- `final_details_page.py` (Step 7 — DL numbers fill, STOP)
- `pdf_downloader.py` — JS fetch + base64 decode, save to `data/output/geico_quote_{business_name}.pdf`

## Block 5: glue

- `tests/simulate_geico.py` — end-to-end simulator (mocked Page, no network)
- Update `workflow_orchestrator.py` so it dispatches to GEICO when MGA rules say so

## Done criteria

- All page objects compile (`python -m py_compile`)
- Simulator passes (mocked flow reaches `Final Quote Details` without crashing)
- Real run with HUMBERTO (USDOT 2033673, ZIP 77705) reproduces quote ~$18,941 + writes PDF
