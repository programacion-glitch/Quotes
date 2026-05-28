# Agents Context — Progressive Module

> Este documento es la "memoria viva" del proyecto Progressive para Claude.
> Copiado al repo desde `~/.claude/projects/.../memory/` para que viaje con el código.
> Última actualización del contenido: 2026-05-25 (exploración live), código: 2026-05-26.

## Estado actual del módulo

✅ **Módulo Progressive end-to-end completo** desde login hasta captura del precio final.
- Todos los selectores validados live el 2026-05-25 contra el portal real
- USDOT de prueba: `2998569` (M&D CUSTOM FREIGHT LLC)
- Precio capturado en prueba: **$53,064/year** (Quote # CA116960411)
- Simulador `tests/simulate_progressive.py` pasa con 83 acciones trazadas

## Cadena completa (pageName URLs)

```
Login → Dashboard → Product dialog → USDot CL panel (opcional fallback) →
BusinessOwnerInfo (START) → VehicleSummary → MostCommonVehicles → AddVehicle (loop) →
AddDriver → DriverSummary → NoHit (HALT condition si MVR falla) →
MoreAboutBusiness (BUSINESS) → CoveragesRates (RATES - precio aquí) →
AdditionalDetails (FINAL DETAILS - STOP HERE) → [PAYMENT - NO ENTRAR] → [COMPLETE]
```

## Hallazgos live importantes (mayo 2026)

### Dashboard
- `combobox[name="State"]` con opciones: Louisiana / Oklahoma / Texas (sólo 3)
- `button "Select Product(s)"` abre `dialog "Product Selection"`
- Dentro del dialog: `button "Commercial Auto"` + `link "Check USDOT number?"`
- **USDot CL widget** (panel separado tras Check USDOT) — devuelve SAFER public data: business name, address, state, cargo commodity, driver count, PU count, business registration date. **Útil como fallback** si la blue quote no tiene esos datos
- `button "Add Products to Quote"` abre wizard en **NUEVA TAB**

### BusinessOwnerInfo (START)
- Effective Date: `combobox "When should this Progressive Commercial Auto policy start?"` (default = today)
- **Business Name es RADIO**, no textbox:
  - `radio "M&D CUSTOM FREIGHT LLC"` (pre-poblado del SAFER) ← preferir si existe
  - `radio "Enter a different Business Name"` + textbox debajo
- Para Corp/LLC: heading "Home Address / please enter the information for the President or CEO."
- Para Individual: heading "Home address / personal information of the Business Owner"
- **Checkbox auto-marcado**: `checkbox "The president or CEO is a driver on the policy."` [checked]
- **Home Address es RADIO** con misma mecánica que Business Name (SAFER preferido + "Enter a different")
- Type of Trucker combobox tiene grupo "Most common types" y "All types"

### AddVehicle (campos dinámicos)
Para Pickup Truck:
- `combobox "Vehicle Type"` (si el VIN no matchea el tipo seleccionado)
- `combobox "What is this vehicle's tonnage?"` (3/4 ton or more / ...)
- `combobox "How many driving wheels does this vehicle have?"` (4 x 2 / 4 x 4)
- `combobox "What type of trailer hitch does this vehicle have?"`

Para SUV/vehículo personal:
- `combobox "What type of SUV is this?"` (SUV / Luxury SUV) — required tras Vehicle Type=Sport Utility Vehicle
- `combobox "Annual Mileage"` (default "8,000 - 11,999")

Todos los vehículos:
- `radio "Is this vehicle used for business, personal or both?"` (Business Only / Business & Personal / Personal Only)
- `radio "Does the customer need Comprehensive or Collision coverage..."` (Yes/No) — aparece si loan=No
  - Si Yes: `radio "What is the total value of all permanently attached equipment..."` ($0 to $2,000 / More than $2,000) **REQUIRED**

Radius options: 50/100/200/300/500 miles / **More than 500 miles** (NO "Over 500 miles")
GVW options: "6,000 or less" / ... / "26,001 lbs or greater"
Loan radio: "Yes - Loan" / "Yes - Lease" / "No"

### Suggested vehicles (VehicleSummary)
- Progressive pre-detecta vehículos por dirección del owner
- Botón "Add" en cada uno: **VA al MostCommonVehicles** (no auto-fill), pero después de elegir tipo llega al AddVehicle con VIN ya pre-llenado y mensaje "The vehicle type you previously chose doesn't match the VIN provided"

### AddDriver
- `combobox "Driver's License State"` (default Texas)
- `textbox "Driver's License Number MVR/CLUE reports..."` (label largo, usar partial match)
- `radio "Exclude this driver from the policy? (No Coverage)"` Yes/No (default No)
- `radio "Has this driver had any accidents, claims or violations in the past 5 years?"` Yes/No (default No)
- `link "{FirstName} isn't a driver"`
- `button "Need an SR22?"`

### NoHit (HALT condition)
- Aparece si MVR lookup falla por license falsa
- `textbox "Social Security Number (Recommended for most accurate quote)"`
- SSN debe ser 9 dígitos o con dashes (123-45-6789), validación cliente
- **Para automatización**: si no hay SSN del blue quote, **HALT y reportar al usuario** (no auto-rellenar)

### MoreAboutBusiness (BUSINESS step)
- `textbox "Customer Email Address (Optional)"`
- `radio "Is the customer currently insured?"` Yes/No (required, sin default)
- `radio "Does the customer have other coverages for the business?"` GL / BOP / None (required)
- `combobox "Number of Named Additional Insureds"` (default "0")
- `combobox "Number of Named Waiver of Subrogation Holders"` (default "0")
- `radio "Is a Blanket Additional Insured endorsement needed by contract?"` Yes/No (default No)
- `radio "Is a Blanket Waiver of Subrogation endorsement needed by contract?"` Yes/No (default No)
- `radio "Are state or federal filings required?"` Yes/No (default No)
- `radio "Is an Electronic Logging Device (ELD) required to record hours of service?"` Yes/No (required, sin default)

### CoveragesRates (RATES step) — LA PÁGINA DEL PRECIO
**Premium display**: text "$XX,XXX.XX" + `generic "Total premium amount $X per year"`
**Pay-in-full discount**: text "Or save $X by paying in full: $X"
**Quote provided by**: text starts with "Quote provided by: " (e.g. "Progressive County Mutual Ins Co")

Per-policy coverages (combobox):
- "Bodily Injury and Property Damage Liability" → default $1 million CSL
- "Uninsured/Underinsured Motorist Bodily Injury" → Not selected
- "Uninsured Motorist Property Damage" → Not selected (combobox name realmente es "Uninsured Motorist Bodily Injury" - bug Progressive)
- "Personal Injury Protection" → Not Selected

Per-vehicle coverages (combobox dentro de region "Coverages for the vehicles"):
- "Comprehensive" → "$500 Deductible" default
- "Collision" → "$500 Deductible" default
- "Medical Payments", "Rental Reimbursement"
- "Roadside Assistance" → "Selected w/ $0 Deductible" default
- "Fire & Theft w/ Combined Additional Coverage"

Special coverages expandibles (botón "+"):
- "Hired Auto Liability" — subform de 7 preguntas (validado live ✅)
- "Employer Non-Owned Auto Liability" (similar a imagen ref, no validado end-to-end)
- "Motor Truck Cargo" (sólo el límite; subform interno NO validado live)
- "Non-Owned Trailer Physical Damage" (sólo el límite)

### Hired Auto Liability subform (validado live)
Preguntas que aparecen progresivamente:
1. `radio "How much did the customer spend in renting, hiring, or borrowing vehicles last year..."` → "$5,000 or less" / "More than $5,000"
2. `radio "Is hired auto requested because of a contractual requirement?"` → Yes/No
   - **Si No: "Coverage not available"** - Progressive no permite Hired Auto sin contract requirement
3. `radio "Does the customer broker any trips?"` → Yes/No
4. `combobox "How many autos did the customer rent, hire or borrow in the last year?"` → "0" / "1-2" / "3-5" / "6-10" / "More Than 10"
5. `radio "Does the customer operate as a freight-broker or freight-forwarder at any time?"` → Yes/No
6. `radio "Is a UIIA or intermodal endorsement required?"` → Yes/No
7. `combobox "Hired Auto coverage limit"` → "Not selected" / "Matching Bodily Injury and Property Damage Limits"
8. `button "Done with this coverage"`

### Después de modificar coverages
Mensaje "The coverages have changed, please 'recalculate' to see your rate." + `button "Recalculate"`. **Hay que click Recalculate antes de Finish & Buy**.

### AdditionalDetails (FINAL DETAILS step) — STOP HERE
- `combobox "Agent of Record"`
- `textbox "Employer Identification Number (EIN)"` (Optional, format ##-#######)
- Per-vehicle group: VIN displayed (read-only)
- `radio "Do you want to order MVR/CLUE reports for all drivers?"` Yes/No
- `button "Continue"` → va a PAYMENT (**NO CLICK** para flujo cotización-only)

## Decisiones de diseño aprobadas

- **A**: Browser por cotización (no sesión persistente)
- **B**: OTP polling Gmail por timestamp; resultado = correo + PDF/screenshot a Drive
- **C**: HYBRID para campos faltantes (defaults obvios, halt para críticos)
- **E**: `PROGRESSIVE_DRY_RUN` flag en .env
- **F**: 1 reintento con browser limpio, reportar con screenshot
- **G**: Logging mínimo, screenshot sólo en error

## Env vars requeridas (.env — NO COMMITEAR)

```
PROGRESSIVE_USER=H2oQualityControl
PROGRESSIVE_PASS=...
PROGRESSIVE_OTP_EMAIL=quotes@h2oins.com
PROGRESSIVE_OTP_APP_PASSWORD=...
PROGRESSIVE_DRY_RUN=true
PROGRESSIVE_HEADLESS=true
PROGRESSIVE_MAX_RETRIES=1
```

## ComboBoxes ExtJS - patrón crítico

Los comboboxes de Sencha ExtJS **NO son `<select>`**. Patrón obligatorio:

```python
await combo.click()                                              # abre el listbox
await page.get_by_role("option", name=value).first.click()       # selecciona opción
```

**NUNCA** uses `select_option()` ni `fill()` con comboboxes — falla silenciosamente.

## Pendiente (próxima sesión live)

Coberturas con selectores parciales que necesitan validación end-to-end:
1. **Employer Non-Owned Auto Liability** — verificar flow real vs imagen de referencia
2. **Motor Truck Cargo** — capturar preguntas internas (refrigeración, perishables, deductible)
3. **Non-Owned Trailer Physical Damage** — capturar subform completo
4. Capturar opciones válidas de cada combobox per-vehicle (Comp/Coll/Med Pay/Rental) para matchear con Blue Quote

Otros mejoramientos sugeridos:
- Usar **USDot CL widget** como fallback automático si Blue Quote no trae dirección
- Detectar trailer types más amplios (tank, low-boy, etc.)
- Captura de **PDF de la quote** desde botón "Print, Email, Fax" en RATES page
