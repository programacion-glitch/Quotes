# Progressive — Variables obligatorias para cotizar

Este documento lista qué campos **debe contener la Blue Quote** para que el módulo
Progressive (automatizado vía Playwright) pueda llegar al precio final.

Validado live el **2026-05-25** con USDOT real `2998569` (M&D CUSTOM FREIGHT LLC) →
precio obtenido: **$53,064/año** (Quote # CA116960411).

---

## 🔴 CRÍTICAS — sin estas el flujo HALT inmediatamente

Si cualquiera falta, `MappedFields.missing_critical()` devuelve el campo y
`ProgressiveClient.create_quote()` retorna `error` antes de abrir el browser.

| Variable Blue Quote | Campo Progressive | Por qué crítica |
|---|---|---|
| `applicant.usdot` | "USDOT Number" + Verify | Sin USDOT verificable, Progressive no permite continuar. La SAFER lookup confirma business name + address pública. |
| `applicant.business_name` | "Business Name" (radio) | Required en START. Si matchea el SAFER (de USDOT) se usa esa opción (más limpio). |
| `applicant.owner_name` | "First Name" + "Last Name" del Owner/CEO | Required en START. Para LLC/Corp, Progressive trata al owner como President/CEO. |
| `effective_date` | "When should this Progressive Commercial Auto policy start?" | Required. Se infiere del **subject del email** con formato `Effective date: MM/DD/YYYY`. |
| `units.vehicles` (≥1) | VehicleSummary → AddVehicle (loop) | Mínimo 1 vehículo para cotizar. Sin VIN o sin Y/M/M, AddVehicle falla. |

---

## 🟡 RECOMENDADAS — Progressive no halt, pero el precio sale **inexacto o aproximado**

Si cualquiera falta, `MappedFields.missing_for_accurate_price()` lo lista en
los `warnings` del resultado para que el agente humano lo sepa.

### Applicant / Owner

| Variable Blue Quote | Campo Progressive | Impacto |
|---|---|---|
| `applicant.owner_dob` | "Date of Birth" (mm/dd/yyyy) | Las tarifas dependen de la edad del driver. Sin DOB, Progressive usa estimación → premio inexacto. |
| `applicant.street_address` | "Street Address" (radio del SAFER si coincide, o textbox) | Si el SAFER ya tiene la dirección, se usa el radio. Si no, debe pasarse manual. |
| `applicant.zip_code` | "ZIP Code" → territory rating | El ZIP de garaging es el principal driver de precio. Sin él Progressive usa proxy. |
| `applicant.city` | "City" (auto-fill por ZIP) | Auto-fill por ZIP, raramente manual. |

### Per vehículo (`units.vehicles[i]`)

| Variable | Campo Progressive | Impacto |
|---|---|---|
| `vehicle.vin` **OR** (`year`+`make`+`model`) | VIN textbox + Lookup, o Year/Make/Model combobox cascada | Sin uno de los dos, AddVehicle no se puede guardar. **VIN es preferible** (auto-llena Y/M/M y GVW). |
| `vehicle.gvw` | "What is the gross vehicle weight?" | Driver de precio. Default `"26,001 lbs or greater"` puede sobreestimar. |
| `vehicle.radius_miles` | "Farthest one-way distance this vehicle typically travels..." | Driver de precio. Default `"More than 500 miles"`. |
| `vehicle.has_loan` | "Is there a loan/lease on this vehicle?" Yes-Loan/Yes-Lease/No | Si "No", aparece pregunta de Comp/Coll. Si Loan/Lease, lender info se pide en FINAL DETAILS. |
| `vehicle.trailer_type` | Botón en MostCommonVehicles (Pickup/Box/Flatbed/etc) | Drive de tipo (Pickup pide tonnage, etc.) |

### Per driver (`drivers[i]`)

| Variable | Campo Progressive | Impacto |
|---|---|---|
| `driver.license_number` | "Driver's License Number" | **MUY IMPORTANTE**: Progressive ordena MVR/CLUE. Sin license válida → halt en NoHit pidiendo SSN. |
| `driver.license_state` | "Driver's License State" (default Texas) | Default Texas funciona para el 99% de casos. |
| `driver.date_of_birth` | DOB del owner (si is_policyholder), de lo contrario falla | Required para drivers NO-owner. Para owner se hereda de `applicant.owner_dob`. |

---

## ⚪ OPCIONALES — Progressive tiene defaults razonables

Estas se pueden omitir y Progressive aplica un default.

| Variable Blue Quote | Campo Progressive | Default usado |
|---|---|---|
| `commodity` | "Business type list" combobox + "Type of Trucker" (si Trucker) | `Trucker → General Freight / Other` |
| `applicant.entity_type` | "How is the customer's business structured?" radio | Auto-derivado del business name (LLC/INC/CORP → Corporation or LLC, else Individual). |
| `coverages_detail.bodily_injury_limit` | "Bodily Injury and Property Damage Liability" | `"$1,000,000 CSL"` |
| `coverages_detail.comp_deductible` / `coll_deductible` | Per-vehicle Comp / Collision deductible combobox | `"$1,000"` (cambiado del default Progressive `"$500 Deductible"`). Pasa None para declinar. |
| `coverages_detail.medical_payments_limit` | Per-vehicle "Medical Payments" combobox | `None` = no se selecciona. |
| `coverages_detail.rental_reimbursement_limit` | Per-vehicle "Rental Reimbursement" combobox | `None` = no se selecciona. |
| `coverages_detail.roadside_assistance` | Per-vehicle "Roadside Assistance" combobox | `"Selected w/ $0 Deductible"` (Progressive default ya selected). |
| `coverages_detail.fire_theft_cac` | Per-vehicle "Fire & Theft w/ Combined Additional Coverage" | `None` = no se selecciona. |
| `coverages_detail.uninsured_motorist_limit` | "Uninsured/Underinsured Motorist Bodily Injury" + "Uninsured Motorist Property Damage" | `None` = no se selecciona (común en TX). |
| `coverages_detail.personal_injury_protection_limit` | "Personal Injury Protection" | `None` = no se selecciona (no aplica a trailers). |
| `coverages_detail.hired_auto` (bool) | Hired Auto Liability subform (7 preguntas) | Default `False`. Si `True` requiere `hired_auto_contractual=True` o Progressive marca "Coverage not available". |
| `coverages_detail.non_owned_auto` (bool) | Employer Non-Owned Auto Liability subform | Default `False`. |
| `coverages_detail.motor_truck_cargo_limit` | Motor Truck Cargo combobox | `None` = no se agrega. ⚠️ Subform sólo aplica el límite; preguntas adicionales (refrigeración, commodities, deductible) NO validadas live aún. |
| `coverages_detail.non_owned_trailer_phys_damage_limit` | Non-Owned Trailer Physical Damage combobox | `None` = no se agrega. |
| MVR/CLUE order | "Do you want to order MVR/CLUE reports for all drivers?" en FINAL DETAILS | Default `False` (no se ordena - sale gratis). |
| EIN | "Employer Identification Number" en FINAL DETAILS | Opcional siempre. |

### Estado de validación live de cada cobertura

| Cobertura | Selectores capturados live | Subform completo automatizado |
|---|---|---|
| Bodily Injury + PD Liability | ✅ 2026-05-25 | ✅ |
| Comp / Coll deductible per vehicle | ✅ 2026-05-25 | ✅ (combobox simple) |
| Medical Payments | ✅ 2026-05-25 | ✅ (combobox simple) |
| Rental Reimbursement | ✅ 2026-05-25 | ✅ (combobox simple) |
| Roadside Assistance | ✅ 2026-05-25 | ✅ (combobox simple, default selected) |
| Fire & Theft w/ CAC | ✅ 2026-05-25 | ✅ (combobox simple) |
| UM/UIM BI + UM PD | ✅ 2026-05-25 | ✅ |
| Personal Injury Protection | ✅ 2026-05-25 | ✅ |
| Hired Auto Liability | ✅ 2026-05-25 | ✅ (7 preguntas + Done with this coverage) |
| Employer Non-Owned Auto Liability | ⚠️ patrón de imagen (similar a Hired Auto) | ⚠️ no validado end-to-end live |
| Motor Truck Cargo | ⚠️ sólo el "+" expand + limit | ❌ Preguntas adicionales (refrigeración, perishables, deductible) NO validadas live |
| Non-Owned Trailer Physical Damage | ⚠️ sólo el "+" expand + limit | ❌ Preguntas adicionales NO validadas live |

---

## 🚫 HALT condition: NoHit page

Si el `license_number` no se valida contra DMV (típico cuando es ficticio o erróneo),
Progressive muestra `pageName=NoHit` pidiendo **SSN del owner** para reintentar el MVR.

**El módulo HALT aquí.** No automatizamos SSN porque:
1. La Blue Quote rara vez lo trae
2. Es información sensible que el agente humano debe revisar antes de enviar

`QuoteResult.error` retorna:
> "Driver MVR/CLUE lookup failed. Progressive requires the driver's SSN to proceed — which is not collected from the blue quote. Verify driver license_number is correct or supply SSN."

---

## Fallback con SAFER public data

Progressive tiene un **widget USDot CL** (link "Check USDOT number?" en dashboard) que
devuelve datos públicos del SAFER:
- Business Name
- Policy Address (calle + ciudad + estado + ZIP)
- Cargo Commodity
- SAFER Driver Count / Power Unit Count
- Business Registration date

**Si la Blue Quote no trae `street_address`/`city`/`zip_code`**, podemos preconsultar el
USDot CL widget y usar esos datos como fallback. Esto está en backlog
(`docs/Proceso Progressive.md`) pero no implementado todavía.

---

## Resumen — mínimo absoluto para cotizar

```python
QuoteProfile(
    applicant=ApplicantProfile(
        business_name="...",      # 🔴 obligatorio
        owner_name="...",         # 🔴 obligatorio
        usdot="...",              # 🔴 obligatorio
        owner_dob="...",          # 🟡 sin esto precio inexacto
        zip_code="...",           # 🟡 sin esto precio inexacto
    ),
    units=UnitsProfile(
        count=1,                  # 🔴 mínimo 1
        vehicles=[
            VehicleProfile(
                vin="...",        # 🟡 o Year/Make/Model
                # gvw, radius, has_loan, trailer_type tienen defaults
            ),
        ],
    ),
    drivers=[
        DriverProfile(
            name="...",           # = applicant.owner_name (is_policyholder=True)
            license_number="...", # 🟡 sin esto -> NoHit halt
            license_state="Texas",
        ),
    ],
)
```

Y desde el subject del email: `effective_date` (formato `MM/DD/YYYY`).

---

## Cómo verificar antes de enviar

```python
from modules.progressive.field_mapper import map_profile_to_fields

fields = map_profile_to_fields(profile, effective_date=eff_date)

critical = fields.missing_critical()
if critical:
    print(f"❌ HALT - faltan campos críticos: {critical}")
    return

warnings = fields.missing_for_accurate_price()
if warnings:
    print(f"⚠️  El precio será aproximado. Falta: {warnings}")
    # Continuar de todas formas - Progressive aplicará defaults

result = ProgressiveClient.create_quote(profile, effective_date=eff_date)
if result.success:
    print(f"✅ Quote: {result.price.annual_premium} ({result.price.quote_number})")
```
