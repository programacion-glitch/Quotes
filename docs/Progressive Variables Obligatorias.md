# Progressive — Variables obligatorias para diligenciar la quote

Este documento es la **referencia autoritativa** sobre qué datos debe contener
el `QuoteProfile` (extraído de Blue Quote + documentos asociados) para que el
módulo Progressive (Playwright) llegue al precio final del seguro.

> **Validación live end-to-end:**
> - **2026-05-25** — USDOT `2998569` (M&D CUSTOM FREIGHT LLC) → $53,064/año
> - **2026-06-01** — USDOT `2998569` (M&D CUSTOM FREIGHT LLC) → **$57,944/año**, Quote # `CA117031734`
> 
> Ningún valor de M&D está hardcoded; el código es 100% genérico para cualquier blue quote.

---

## TL;DR — Mínimo absoluto para que Progressive cotice

```python
QuoteProfile(
    applicant=ApplicantProfile(
        business_name="...",          # 🔴 obligatorio
        owner_name="...",             # 🔴 obligatorio (First + Last)
        usdot="...",                  # 🔴 obligatorio (debe verificar en SAFER)
        owner_dob="MM/DD/YYYY",       # 🟡 sin esto el premio sale inexacto
        zip_code="...",               # 🟡 driver principal de rating territorial
        street_address="...",         # 🟡 SAFER lo pre-pobla si coincide
    ),
    units=UnitsProfile(
        count=1,                      # 🔴 mínimo 1 vehículo
        vehicles=[
            VehicleProfile(
                vin="2GKALNEK6H6187660",  # 🟡 VIN preferido (autocompleta Y/M/M)
                trailer_type="FLATBED",   # tipo para el botón MostCommonVehicles
                # gvw, radius_miles, has_loan: tienen defaults razonables
            ),
        ],
    ),
    drivers=[
        DriverProfile(
            name="JUAN PEREZ",        # debe matchear owner_name para is_policyholder
            license_number="...",     # 🟡 sin esto NoHit → HALT (Progressive pide SSN)
            license_state="Texas",
        ),
    ],
)
# Y del subject del email:  effective_date = "06/01/2026"
```

---

## 🔴 CRÍTICAS — sin estas el flujo HALT antes de abrir browser

`MappedFields.missing_critical()` valida estos campos. Si falta alguno,
`ProgressiveClient.create_quote()` retorna error sin abrir browser.

| Variable Blue Quote | Campo Progressive | Por qué crítica |
|---|---|---|
| `applicant.usdot` | "USDOT Number" + botón Verify | Sin USDOT verificable en SAFER, Progressive no permite continuar. |
| `applicant.business_name` | "Business Name" (radio) | Required en START. |
| `applicant.owner_name` | "First Name" + "Last Name" | Required en START. Se hace `.split()` por espacios. |
| `effective_date` | "When should this Progressive Commercial Auto policy start?" | Required. Se extrae del **subject del email** con regex `[Ee]ffective\s+date[:\s]+(\d{1,2}/\d{1,2}/\d{4})`. |
| `units.vehicles` (≥1) | VehicleSummary → AddVehicle (loop) | Mínimo 1 vehículo. Cada uno requiere VIN o Y/M/M. |

---

## 🟡 RECOMENDADAS — Progressive no halt, pero el precio sale aproximado

`MappedFields.missing_for_accurate_price()` reporta estos como `warnings` del resultado.

### Applicant / Owner

| Variable | Campo Progressive | Impacto |
|---|---|---|
| `applicant.owner_dob` | "Date of Birth" (mm/dd/yyyy) | Las tarifas dependen de la edad del driver/owner. |
| `applicant.street_address` | "Street Address" (radio del SAFER o textbox) | Si el SAFER del USDOT lo pre-pobla, se elige ese radio. |
| `applicant.zip_code` | "ZIP Code" → territory rating | **Driver principal de precio.** |
| `applicant.city` | "City" (auto-fill por ZIP, raramente manual) | Auto-fill por ZIP. |
| `applicant.phone` | (no usado por Progressive START, sí por Geico) | Opcional. |
| `applicant.email` | (no usado por Progressive START, sí por Geico) | Opcional. |

### Per vehículo — `profile.units.vehicles[i]`

| Variable | Campo Progressive | Default si falta | Impacto |
|---|---|---|---|
| `vehicle.vin` (preferido) **OR** `year+make+model` | VIN textbox + Lookup, o Y/M/M comboboxes | (sin default) | Sin uno de los dos, AddVehicle falla. **VIN es preferible**: autocompleta Y/M/M, GVW, body style. **El Y/M/M cascade es frágil en ExtJS** — usar VIN siempre que la blue quote lo traiga. |
| `vehicle.gvw` | "What is the gross vehicle weight?" | `"26,001 lbs or greater"` | Driver de precio. Default puede sobreestimar. |
| `vehicle.radius_miles` | "Farthest one-way distance..." | `"More than 500 miles"` | Driver de precio. |
| `vehicle.has_loan` | "Is there a loan/lease on this vehicle?" | `"No"` | Si "No" → revela pregunta Comp/Coll. Si Loan/Lease → lender info en FINAL DETAILS. |
| `vehicle.trailer_type` | Botón en MostCommonVehicles (Pickup/Box/Flatbed/Tractor/Cargo Van/Other) | `"FLATBED"` | El tipo del vehículo cambia los campos requeridos dinámicos. |
| `vehicle.garaging_zip` | "Zip code where the vehicle is located" | usa `applicant.zip_code` | Si el vehículo se guarda en distinta ubicación al owner. |

### Per driver — `profile.drivers[i]`

| Variable | Campo Progressive | Impacto |
|---|---|---|
| `driver.license_number` | "Driver's License Number" | **🚫 Sin esto → NoHit page → HALT.** Progressive pide SSN si MVR lookup falla. **Política CLAUDE.md prohíbe auto-rellenar SSN.** |
| `driver.license_state` | "Driver's License State" | Default `"Texas"`. |
| `driver.date_of_birth` | DOB (heredado de `applicant.owner_dob` si is_policyholder, manual para extras) | Required para drivers no-owner. |
| `driver.exclude_from_policy` | "Exclude this driver?" radio | Default `False`. |
| `driver.has_accidents_or_violations` | "Has this driver had any accidents..." radio | Default `False`. |

---

## ⚪ OPCIONALES — Progressive tiene defaults razonables

| Variable | Campo Progressive | Default usado |
|---|---|---|
| `commodity` | "Business type list" combobox + "Type of Trucker" sub-combobox | `Trucker → General Freight / Other` |
| `applicant.entity_type` | "How is the customer's business structured?" | Auto-derivado del business name: contiene "LLC"/"INC"/"CORP" → "Corporation or LLC", else "Individual / Sole Proprietor" |
| `coverages_detail.bodily_injury_limit` | "Bodily Injury and Property Damage Liability" | `"$1,000,000 CSL"` |
| `coverages_detail.comp_deductible` / `coll_deductible` | Per-vehicle Comp/Coll deductible | `"$1,000"` (override del default Progressive `"$500 Deductible"`) |
| `coverages_detail.medical_payments_limit` | Per-vehicle "Medical Payments" | `None` (decline) |
| `coverages_detail.rental_reimbursement_limit` | Per-vehicle "Rental Reimbursement" | `None` (decline) |
| `coverages_detail.roadside_assistance` | Per-vehicle "Roadside Assistance" | `"Selected w/ $0 Deductible"` (Progressive default ya selected) |
| `coverages_detail.fire_theft_cac` | Per-vehicle "Fire & Theft w/ Combined Additional" | `None` |
| `coverages_detail.uninsured_motorist_limit` | UM/UIM BI + Property Damage | `None` (común en TX) |
| `coverages_detail.personal_injury_protection_limit` | PIP | `None` |
| `coverages_detail.hired_auto` (bool) | Hired Auto Liability subform (7 preguntas) | `False`. Si `True`, requiere `hired_auto_contractual=True` o Progressive marca "Coverage not available". |
| `coverages_detail.non_owned_auto` (bool) | Employer Non-Owned Auto Liability subform | `False` |
| `coverages_detail.motor_truck_cargo_limit` | Motor Truck Cargo combobox | `None` |
| `coverages_detail.non_owned_trailer_phys_damage_limit` | Non-Owned Trailer Physical Damage combobox | `None` |
| MVR/CLUE order | "Do you want to order MVR/CLUE reports?" en FINAL DETAILS | Default `False` (no se ordena — gratis para la cotización) |
| EIN | "Employer Identification Number" en FINAL DETAILS | Opcional siempre |

---

## 🚫 HALT condition: NoHit page

Si el `license_number` de algún driver no se valida contra DMV (típico cuando es ficticio o erróneo), Progressive muestra `pageName=NoHit` pidiendo **SSN del owner**.

**El módulo HALT aquí.** CLAUDE.md tiene la regla explícita:

> NoHit es HALT: si MVR/CLUE falla y Progressive pide SSN → reportar al usuario, no auto-rellenar SSN (data sensible).

`QuoteResult.error` retorna:
> "Driver MVR/CLUE lookup failed. Progressive requires the driver's SSN to proceed — which is not collected from the blue quote. Verify driver license_number is correct or supply SSN."

---

## Fallback: USDot CL widget (datos públicos de SAFER)

Progressive expone un widget en el dashboard (link "Check USDOT number?") que devuelve datos públicos de SAFER **sin entrar al wizard**:

- SAFER Business Name
- Policy Address (street + city + state + ZIP)
- Cargo Commodity
- SAFER Driver Count / Power Unit Count
- Business Registration date

Si la Blue Quote no trae `street_address`/`city`/`zip_code`, podemos preconsultar el widget USDot CL y usar esos datos como **fallback**. Esto está en backlog (`docs/Proceso Progressive.md`), no implementado todavía en código de producción, pero usable manualmente.

---

## Comportamiento de SAFER prefill (importante)

Cuando Progressive verifica el USDOT en BusinessOwnerInfo, devuelve dos campos pre-poblados con datos del SAFER federal:

### Business Name → RADIO con dos opciones
```yaml
- radio "M&D CUSTOM FREIGHT LLC"        # ← nombre del SAFER, preferido si coincide
- radio "Enter a different Business Name"  # ← fallback, abre textbox manual
```

El código hace `get_by_role("radio", name=fields.business_name, exact=False)` — si el SAFER coincide con el nombre del Blue Quote, lo selecciona. Si no, cae al "Enter different" y llena el textbox.

### Home Address → RADIO con misma mecánica
```yaml
- radio "7630 AMELIA RD APT 110 HOUSTON TX 77055"  # ← address del SAFER
- radio "Enter a different address"
```

Mismo patrón: matchea contra `fields.owner_street` con `has=...`. Si no matchea, llena Street/ZIP/City/State manualmente.

---

## Verificación antes de enviar (recomendado en código)

```python
from modules.progressive.field_mapper import map_profile_to_fields
from modules.progressive.client import ProgressiveClient

fields = map_profile_to_fields(profile, effective_date=eff_date)

# Validación crítica
critical = fields.missing_critical()
if critical:
    print(f"❌ HALT - faltan campos críticos: {critical}")
    return

# Advertencias (no bloquean, pero el precio será aproximado)
warnings = fields.missing_for_accurate_price()
if warnings:
    print(f"⚠️  Precio aproximado. Falta: {warnings}")

# Cotizar
result = ProgressiveClient.create_quote(profile, effective_date=eff_date)
if result.success:
    print(f"✅ Quote: {result.price.annual_premium} ({result.price.quote_number})")
else:
    print(f"❌ Failed at {result.step_reached}: {result.error}")
    if result.screenshot_path:
        print(f"   Screenshot: {result.screenshot_path}")
```

---

## Flujo end-to-end completo (qué páginas atraviesa el bot)

```
1. Login + OTP                       ← lee Gmail IMAP, borra el correo OTP usado
2. Dashboard                          ← State=Texas, Commercial Auto, Check USDOT
3. BusinessOwnerInfo (START)          ← USDOT verify, Business Name radio, Address radio, Owner info
4. VehicleSummary → loop:
   a. MostCommonVehicles              ← click tipo (Pickup/Flatbed/etc)
   b. AddVehicle                      ← VIN lookup (preferido) o Y/M/M
      ↳ Vehicle Type mismatch (si VIN no coincide con tipo)
      ↳ Comp/Coll Yes/No (si loan=No)
      ↳ Equipment value (si Comp/Coll=Yes)
   c. Continue → vuelve a VehicleSummary
5. AddDriver (policyholder pre-cargado)
   → DriverSummary → loop additional drivers (add → fill → back to summary)
   → Continue
   ↳ NoHit (si MVR lookup falla → HALT, requiere SSN)
6. MoreAboutBusiness (BUSINESS)       ← currently insured, other coverages (CHECKBOXES, no radio), ELD
7. CoveragesRates (RATES)             ← ⭐ PRECIO CAPTURADO AQUÍ
   ↳ Subforms opcionales: Hired Auto, Non-Owned, MTC, Non-Owned Trailer
8. AdditionalDetails (FINAL DETAILS)  ← agent, EIN, MVR order. STOP HERE — no clickear Continue final.
   ↳ PAYMENT (NO ENTRAR — bind real de póliza)
   ↳ COMPLETE (NO ENTRAR)
```

---

## Cambios documentados en validaciones live

| Fecha | Hallazgo | Aplicado en código |
|---|---|---|
| 2026-04-09 | Selectores iniciales validados (BusinessOwnerInfo, Vehicles, Drivers) | ✅ |
| 2026-05-25 | RATES + Hired Auto subform + FINAL DETAILS validados; precio $53,064 capturado | ✅ |
| 2026-05-26 | Refactor de page objects + drive sync + REGLAS FINALES | ✅ |
| 2026-06-01 | **Bug #1**: OTP label cambió de `MfaOtpEntry` a `"One-time passcode"` | ✅ `login_page._enter_otp` con primary role-based selector + fallback |
| 2026-06-01 | **Bug #4**: MoreBusinessPage "Other coverages" cambió de **radio** a **CHECKBOX GROUP doble** (existing policies + bundle-with-Progressive). Hay que tickear "None of the above" en ambos. | ✅ `_answer_other_coverages` ahora tickea checkboxes; mantiene fallback al radiogroup legacy |
| 2026-06-01 | **Bug #2** (edge case): Y/M/M cascade frágil en ExtJS — después de seleccionar Year, Make queda `aria-disabled="true"` indefinidamente. | ⚠️ Documentado: usar VIN siempre que la blue quote lo traiga. Y/M/M es fallback best-effort. |
| 2026-06-01 | OTP reader IMAP ahora **borra** el correo después de leer (`delete_after_read=True` default) | ✅ `otp_reader.py` con IMAP MOVE → Trash |
| 2026-06-01 | Precio validado live nuevo: **$57,944/año**, Quote `CA117031734` | — |
