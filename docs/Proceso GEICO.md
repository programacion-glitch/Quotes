# Proceso GEICO Commercial Auto — Mapa del Flow

> Documento equivalente a `Proceso Progressive.md` y `AGENTS_CONTEXT.md` pero para
> GEICO. Mapeo live realizado el **2026-05-28** con HUMBERTO VILLARREAL
> (USDOT `2033673`, BlueQuote `20260113`).
>
> Quote capturada: **$18,941.00 / year** (12-Month policy).
> PDF guardado en `data/output/geico_quote_HUMBERTO_VILLARREAL.pdf`.

## Estado actual del módulo

⏳ **Mapeo completo, implementación pendiente.**
- 7 steps mapeados + 1 step dinámico (DriveEasy Pro)
- 18 screenshots en `geico_*.png` (mover a `docs/imagenes_geico/` al consolidar)
- STOP point identificado: **Final Quote Details**, NO click el Next que va a MVR & CLUE

## Cadena completa (pageName / title)

```
Login (Azure B2C) → MFA email OTP (quotes@h2oins.com) →
Gateway Dashboard (gateway.geico.com/quote)
  ├─ Check Commercial Auto/Trucking (exclusivo, los otros productos se disabled)
  ├─ Check USDOT (server-side eligibility) — NotEligible HALT si rechaza
  └─ Fill ZIP (eligibility ZIP también) → Start New Quote → nueva tab
       │
       └─ sales.geico.com/quote (wizard):
            1. Business Class & USDOT
            2. Business & Owner Info
            3. Vehicles (VIN decode + sub-page comp/coll + Vehicle Summary)
            4. Drivers & Incidents (Owner placeholder + Add Driver real + Driver Summary)
            5. Additional Business Info
            5b. DriveEasy Pro (telematics — dinámico, aparece si elegible)
            6. Quote & Coverages ⭐ PRECIO + PDF deliverable
            7. Final Quote Details ⭐ STOP HERE (NO click Next final)
            [8. MVR & CLUE — NO ENTRAR]
            [9. Payment Information — NO ENTRAR]
```

## Login + MFA

- **Login URL = `https://gateway.geico.com`** (SP-initiated entry). ⚠️ **NO usar
  una authorize URL capturada** (`.../oauth2/v2.0/authorize?...&code_challenge=...`).
  El `code_challenge` PKCE de una URL capturada tiene su *verifier* en el browser
  que la generó; al reusarla, `ecams.geico.com` no puede completar el token
  exchange → sesión inválida → **"Tu sesión ha terminado"**. Validado live
  2026-05-28: un browser fresco que visita `gateway.geico.com` es redirigido por
  ecams a un b2clogin con PKCE fresco (ecams retiene el verifier) → sesión válida.
- Tras login, GEICO aterriza en `gateway.geico.com/Dashboard`; el widget de
  eligibility ("Commercial Auto") vive en `gateway.geico.com/quote` — el flujo
  navega ahí explícitamente (`DashboardPage._ensure_on_quote_dashboard`).
- **Credenciales**: env vars `GEICO_USER` (`I070857`) y `GEICO_PASS`
- **MFA**: condicional. GEICO pide OTP solo periódicamente (no siempre). Validado
  live: con IP/equipo trusted, el login pasa **sin MFA** directo al gateway.
  - El `login_page` hace polling: detecta lo que ocurra primero — redirect al
    gateway (login directo) o el selector MFA Email/Phone.
  - **El check de "estoy en el gateway" DEBE parsear el host** (`urlparse().hostname
    == gateway.geico.com`), NO substring — la authorize URL trae
    `relayState=https%3A%2F%2Fgateway.geico.com%2F...` que daría falso positivo.
  - Si MFA aparece: **elegir Email** → código de 6 dígitos a `quotes@h2oins.com`
    (mismo Gmail/App Password que Progressive). `GeicoOTPReader` lo lee por IMAP.

### Selectores login

| Campo | Selector / ref |
|---|---|
| Username textbox | `role=textbox name="Username"` |
| Password textbox | `role=textbox name="Password"` |
| Sign in button | `role=button name="Sign in"` |
| MFA method radio Email | `#extension_mfaByPhoneOrEmail_email` |
| Continue button | `role=button name="Continue"` |
| Send verification code | `role=button name="Send verification code"` |
| Verification code input | `role=textbox name="Verification code"` |
| Verify code button | `role=button name="Verify code"` |
| Send new code | `role=button name="Send new code"` (re-trigger OTP) |

## Gateway Dashboard

URL: `gateway.geico.com/quote`

Sidebar info auto-populated:
- User Name (e.g. `i070857`)
- Agency ID (e.g. `H2O COMMERCIAL INSURANCE AGENCY CORP (Agency ID: G00759)`)

**Quick Start** radios:
- "Start a Quote" [default checked]
- "Search for Policy"
- "Lookup Prior Quote"

**Check Eligibility** checkboxes (5 productos, mutually exclusive):
- Private Passenger Auto
- Motorcycle, ATV & Off-Road
- RV
- **Commercial Auto/Trucking** ⭐ (nuestro caso)
- Umbrella

⚠️ **Patrón crítico**: el checkbox real está oculto detrás del label. Click el contenedor con cursor pointer, NO el `<input>` raw (timeout porque está outside viewport). Selector: `#labelForCommercialAuto`.

Al marcar Commercial Auto:
- Los otros 4 productos se vuelven `[disabled]`
- Aparecen 3 campos: `ZIP Code` (required), `State` (autopopula del ZIP, disabled), `USDOT Number` (Optional pero recomendado)

### Eligibility checks (server-side, ambos requeridos para habilitar Start New Quote)

1. **USDOT eligibility**: 
   - Type USDOT → enable button `Check USDOT` → click → server check
   - Devuelve alert: "**Eligible** — This USDOT number is eligible for insurance coverage at this time" ✅
   - O "**Not Eligible** — The USDOT operating history and record for this entity or closely related entities does not meet GEICO's eligibility criteria" ❌ HALT
   - **Caso documentado**: M&D CUSTOM FREIGHT LLC (USDOT `2998569`) → Not Eligible. Mismo USDOT pasa Progressive con quote $53,064.

2. **ZIP eligibility**:
   - Después de USDOT, type ZIP → server check
   - "Eligible — This ZIP Code is eligible for insurance coverage at this time" ✅

⚠️ **GEICO NO autopopula la dirección desde USDOT** (a diferencia del Progressive SAFER widget). Necesitamos el ZIP de `physical_address` o `mailing_address` de la BlueQuote.

3. **Start New Quote** se transforma de `<button disabled>` a `<a>` con URL:
   ```
   sales.geico.com/dashboard?processor=commercialquote&zip=<ZIP>&usdot=<USDOT>&usdotsid=<token>
   ```
   - El `usdotsid` es token de sesión generado por el eligibility check
   - **No se puede saltar el dashboard** — siempre hay que pasar por el check para obtener el token

4. Click → abre wizard en **nueva tab** (igual que Progressive)

## Step 1: Business Class & USDOT

Title: `GEICO Business Class & USDOT`

| Campo | Valor (HUMBERTO) | Source BlueQuote |
|---|---|---|
| `5-Digit ZIP Code` | `77705` | pre-poblado de dashboard |
| Radio "Does the customer have a USDOT Number?" | `Yes` [checked] | pre-seleccionado |
| `USDOT Number` textbox | `2033673` | pre-poblado |
| Radio "Is this the customer's business?" (con preview address) | `Yes` | confirmar el lookup |
| Radio "Does the customer have an ELD?" | `No` (default conservador) | BlueQuote no menciona |
| `Business class` combobox (1,596 opciones alfabéticas) | `Dirt Sand & Gravel (For A Fee)` | `commodities`: `DIRT, SAND & GRAVEL 100%` |
| Radio "Does any vehicle/load require hazmat placard?" | `No` (aparece después de business class) | inferido del commodity |

🎯 **Hallazgo importante**: GEICO usa **mailing address** del lookup, no physical address.

🎯 **Business class catalog**: lista alfabética plana, sin grupos. Match exacto encontrado para "DIRT, SAND & GRAVEL 100%". Para field_mapper: reutilizar/extender `modules/ai_commodity_classifier.py` orientado al catálogo GEICO.

## Step 2: Business & Owner Info

Title: `GEICO Business & Owner Info`

Sidebar Dashboard se enriquece con: Contact Number, Email, Business Segment (`Trucking`).

**Auto-populated desde server (FMCSA registry probable)**:
- Business street address (mailing)
- ZIP, City (combobox: BEAUMONT [selected] / OTHER)
- Email
- Owner phone, Business phone

| Campo a llenar | Valor (HUMBERTO) | Source |
|---|---|---|
| Business Owner First Name | `HUMBERTO` | `driver[0].name` split |
| Business Owner Last Name | `VILLARREAL` | drop middle initial "F" |
| Date of Birth | `03/25/1949` | `driver[0].dob` |
| Marital Status combobox | **`Single`** (siempre default) | NO está en BlueQuote |
| Owner phone | `(409) 656-7240` | **BlueQuote prevalece sobre GEICO auto-pop** |
| Business phone | `(409) 656-7240` | mismo número |
| Business ownership type combobox | `Individual/Sole Proprietorship` | inferido: business_name == owner_name + DBA presente |
| Coverage Start Date | default mañana | NO modificar para testing; en prod leer del email subject |
| Radio "Is the owner a driver on the policy?" | **`No`** (HUMBERTO excluded en BlueQuote) | `owner_is_driver = NOT (owner in drivers AND excluded=="YES")` |

Marital Status options: `Single / Married / Divorced / Separated / Widowed`
Business ownership options: `Limited Liability Company / Individual/Sole Proprietorship / Corporation/Other / Partnership / Trust`

## Step 3: Vehicles

Title: `GEICO Vehicles`

**Sub-page 1: vehicle entry**
- Radio "Do you have VIN handy?" → `Yes` (siempre que BlueQuote traiga VIN)
- VIN textbox (17 chars) → fill VIN → **VIN decode runs server-side**
- Auto-pobló: Year, Make, Model (e.g. `2009 / MACK / CHU (PINNACLE)`)

⚠️ **Edge case crítico**: GEICO VIN decode puede contradecir BlueQuote.type. Ejemplo: VIN `1M1AN07Y19N003670` decodea a `Tractor` (MACK PINNACLE es tractor heavy-duty real), pero BlueQuote dijo `Dump Truck`. **Regla field_mapper: VIN decode > BlueQuote**. Si selecciono Dump Truck primero, GEICO lo sobreescribe a Tractor cuando completa decode.

| Campo | Valor |
|---|---|
| Vehicle Type combobox (39 opciones, se reordena según VIN decode) | `Tractor` (auto) o forzar BlueQuote.type |
| Garaging address searchbox | auto-pop `585 NOLAN STREET` |
| ZIP / City | auto-pop |
| `Farthest one-way distance` combobox | `51-100` (BlueQuote `0-100` MILES) |
| Radio "Personal use?" | `No` |

⚠️ **El combobox de distance NO es `<select>` clickable**. Para forzar valor: `combo.value = "51-100"; combo.dispatchEvent(new Event('change'))` via JS evaluate. `selectOption` falla por aria-label mismatch.

Distance options: `0-25 / 26-50 / 51-100 / 101-200 / 201-300 / 301-500 / More than 500`

**Sub-page 2: comp/coll dialog**

Heading: "Tell us more about your {YEAR} {MAKE} {MODEL}."
- Radio "Would the customer like to add comprehensive or collision coverage?" 
- Regla: `comp_coll = bluequote.coverages.physical_damage_deductible is not None`
- HUMBERTO: `physical_damage_deductible: null` → `No`

**Sub-page 3: Vehicle Summary**

Lista vehículos agregados + `Add Vehicle or Trailer` + `Looks Good` button.

Para BlueQuotes con N vehículos: iterar Add Vehicle por cada uno antes de Looks Good.

## Step 4: Drivers & Incidents

Title: `GEICO Drivers & Incidents`

**Sub-page 1: Owner placeholder driver**

GEICO crea automáticamente un driver placeholder con el owner name (incluso si "owner_is_driver = No" en Step 2). Pide:
- `{Owner}'s Driver License State` combobox (default Texas)
- Radio "Does this driver have a CDL?" — si owner está excluded, default `No` (mantiene placeholder pero excluded de rating)

**Sub-page 2: Add a Driver**

Para cada driver no-excluded en BlueQuote:

| Campo | Valor (CLIFTON) | Source |
|---|---|---|
| First Name | `CLIFTON` | `driver.name` split |
| Last Name | `THOMAS` | drop suffix |
| Suffix combobox | `JR` | parsed from name |
| Date of Birth | `09/12/1960` | `driver.dob` |
| Driver's License State | Texas [selected] | `driver.state` |
| Radio "What is their relationship to the business?" | `Employee` (no es Owner) | inferido (no es business owner) |
| Radio "Does this driver have a CDL?" | `Yes` | `driver.class in ["A","B"]` o `driver.cdl_class is not None` |
| **Driving history** | None (BlueQuote accidents=0, violations=0) | skip "Add Incident" |

Suffix options: `(empty) / JR / SR / I / II / III / IV / V / 2ND / 3RD / MD`
Relationship options: `Owner / Employee / Other`

🟡 **Texas Residents alert**: "Do NOT list tickets dismissed from MVR due to Defensive Driving Course." Informational.

**Sub-page 3: Driver Summary**

Lista drivers con status:
- HUMBERTO VILLARREAL → `Owner` / `NonDriver` (excluded)
- CLIFTON THOMAS → `Employee` / `Active`
- `Add Driver` para más + `Looks Good`

## Step 5: Additional Business Info

Title: `GEICO Additional Business Info`

| Campo | Valor (HUMBERTO) | Source BlueQuote |
|---|---|---|
| Years operating combobox | `7+` | `years_in_business: 27 YEARS` |
| Employees (excl owners) combobox | `1` | drivers count - owner count |
| Has current auto insurance? combobox | `Yes` | `current_carrier: PROGRESSIVE...` |
| Years with current insurer combobox | `3-5 Years` | `years_continuous_coverage: 4 YEARS` |
| Current BI limits combobox | `$500,000/$500,000 or $500,000 CSL` | `auto_liability_limits: $500K CSL` |
| Radio liability type | `None` | `general_liability: null` |
| Radio "named additional insured/waiver"? | `No` | no mencionado |
| Radio "blanket additional insured contract"? | `No` (default) | no mencionado |
| Radio "state/federal filings required"? | `No` | no mencionado (intrastate-only TX) |

Years operating: `Less than 1 / 1 / 2 / 3-6 / 7+`
Employees: `None / 1 / 2-3 / 4-5 / 6-10 / 11-20 / 21+`
Current insurance: `Yes / No / No, the customer was deployed`
Years with insurer: `Less Than 1 Year / 1-3 Years / 3-5 Years / 5-10 Years / 10+ Years`
BI limits: 10 opciones desde `State Minimum` hasta `$1,000,000/$1,000,000 or $1,000,000 CSL`

⚠️ Al elegir `Yes` en current insurance, aparecen 2 nuevos campos required (years with insurer + BI limits). Validation error si faltan.

## Step 5b: DriveEasy Pro (dinámico)

Title: `GEICO DriveEasy Pro` — telematics opt-in.

Aparece después de Step 5 condicional a tamaño/tipo. 3 opciones (radios):
1. **Customer's ELD** — generalmente INELIGIBLE si ELD=No en Step 1
2. **Dashcam from GEICO** — INELIGIBLE para vehicles antiguos
3. **OBD from GEICO** — usualmente la única elegible

Botón **`Continue without driveEasy Pro`** para skip.

**Default field_mapper**: `choose_driveeasy_pro = False` (BlueQuote no pide telemática, evita opt-in extras).

## Step 6: Quote & Coverages ⭐ PRECIO + PDF

Title: `GEICO Quote & Coverages`

**Premium display** (12-Month policy):
- Total: `$18,941.00` ("Due Today")
- Pay In Full discount: `Save $2,075.00`
- 4 / 9 / 11 payment options con auto-pay

Toggle 6-Month vs 12-Month button.

**Per-policy coverages** (combobox, defaults para TX):

| Cobertura | Default | Precio |
|---|---|---|
| Liability Coverage type | Bodily Injury and Property Damage Liability | — |
| BI / CSL Limit | `$500,000 Combined Single Limit` | $19,344.00 |
| UM/UIM combobox | `$500,000 Combined Single Limit` | $582.00 |
| Medical Payments | `Not Included` | — |
| Basic PIP | `$2,500` | $183.00 |

BI/CSL options: 6 split limits + 6 CSL limits (`$30K/$60K` hasta `$1M CSL`)
UM/UIM options: I decline, $85K CSL, $100K, $300K, $500K
PIP options: I decline, $2,500

**Per-vehicle coverages** (cada vehicle tiene su sub-bloque):
- Comprehensive: Not Included | $100/$250/$500/$1k/$2.5k/$5k deductible
- Collision: Not Included
- Road Services: I decline (requires comp+coll antes de activar)
- Fire And Theft: Not Included | mismos deductibles que Comp
- Rental Reimbursement w/ Downtime: Not Included (requires comp+coll)

**Optional add-ons** (collapsibles abajo):
- Motor Truck Cargo
- Hired Autos
- Non-Owned Hired Autos
- Non-Owned Trailer Physical Damage
- Trailer Interchange

🎯 **PDF Deliverable**: link `Print Quote Proposal` (refresh URL incluye `conversationId` y `retentionKey`):
```
sales.geico.com/PrintQuote?doctype=CommercialQuotePdfIAAgent&retentionKey=<key>&auth=t&conversationId=<id>&termLength=12
```
- Abre en nueva tab como PDF inline (no triggers download dialog)
- Download method: JS `fetch(url, {credentials:'include'})` → arrayBuffer → base64 → decode
- 99 KB PDF típicamente (CommercialQuotePdfIAAgent template, "Registered to: GEICO" en metadata)

⚠️ Alert visible: `"MVR/CLUE Hasn't run"` — el precio puede cambiar tras Step 8.
⚠️ Alert visible: `"An unidentified trailer has been added to your policy"` — porque seleccionamos Tractor (auto-añade trailer placeholder). Esto afecta precio.

## Step 7: Final Quote Details ⭐ STOP HERE

Title: `GEICO Final Quote Details`

| Campo | Valor (HUMBERTO) | Source |
|---|---|---|
| Radio "Worker's comp coverage?" | `No` (small op) | no mencionado en BlueQuote |
| Email confirmation textbox | `mmortiz1957@gmail.com` ✅ | auto-pop |
| Owner phone confirmation textbox | `(409) 656-7240` ✅ | auto-pop (after Step 2 override) |
| Checkbox GEICO Text Messages | `[checked]` (default) | dejar default |
| Checkbox Digital Communications | `[checked]` (default) | dejar default |
| HUMBERTO's DL State combobox | Texas [selected] | `driver[0].state` |
| **HUMBERTO's DL Number** textbox | `10069460` | `driver[0].dl_number` |
| CLIFTON's DL State combobox | Texas [selected] | `driver[1].state` |
| **CLIFTON's DL Number** textbox | `00767736` | `driver[1].dl_number` |
| VIN textbox (disabled, per-vehicle) | `1M1AN07Y19N003670` ✅ | confirmed |
| Vehicle registered owner combobox | `HUMBERTO VILLARREAL` | inferred desde owner |
| Radio "Vehicle owned, leased, financed?" | `Owned [checked]` | BlueQuote `value: $0` + no loan info |
| Add Authorized Rep | opcional | skip |
| Add Certificate Holder | opcional | skip |
| Radio "blanket additional insured contract?" | `No [checked]` (default) | dejar default |

🛑 **STOP**: el `button "Next"` al final lleva a **Step 8: MVR & CLUE** (consume MVR pulls server-side, puede modificar precio). NO click este Next en flow de cotización-only. Análogo a Progressive `AdditionalDetails` STOP.

## Step 8 y 9 (NO mapeados, NO ENTRAR)

- **8. MVR & CLUE**: GEICO ejecuta MVR + CLUE check usando los DL numbers de Step 7. Devuelve quote ajustada por driving history. Consume MVR/CLUE pulls (puede tener costo). 
- **9. Payment Information**: bind real de la póliza. **NUNCA ENTRAR** en automation cotización-only.

## Decisiones de diseño aprobadas (esta sesión)

| Decisión | Aplicación |
|---|---|
| **A**: Browser por cotización (no sesión persistente) | igual que Progressive |
| **B**: OTP polling Gmail por timestamp (mismo `quotes@h2oins.com` + mismo App Password) | reusar `modules/progressive/otp_reader.py` |
| **C**: HYBRID para campos faltantes (defaults obvios, HALT para sensibles) | igual que Progressive |
| **D**: VIN decode > BlueQuote cuando conflict | nueva regla GEICO-específica |
| **E**: `GEICO_DRY_RUN` flag en .env | igual estructura que Progressive |
| **F**: Reintento con browser limpio, screenshot en error | igual que Progressive |
| **G**: Print Quote Proposal PDF como deliverable (no email auto) | distinto a Progressive (que no implementa PDF aún) |
| **H**: Marital Status = `Single` siempre | sin proxy de data, decisión política |
| **I**: `owner_is_driver = NOT (owner appears in drivers AND excluded=YES)` | nueva regla GEICO |

## Env vars requeridas (.env — NO COMMITEAR)

```
GEICO_USER=I070857
GEICO_PASS=<from-1password>
GEICO_LOGIN_URL=<azure-b2c-url>
GEICO_OTP_EMAIL=quotes@h2oins.com
GEICO_OTP_APP_PASSWORD=<same-as-progressive>
GEICO_DRY_RUN=true
GEICO_HEADLESS=false
GEICO_MAX_RETRIES=1
```

⚠️ **Problema de seguridad pendiente**: `.env` está tracked en git (`a9cc6d6 chore: redact Progressive credentials` confirma history previa). Las creds GEICO se agregaron sin remediar primero. Acción pendiente: agregar `.env` a `.gitignore`, `git rm --cached .env`, rotar `EMAIL_PASSWORD` (Gmail App Password expuesta).

## Cross-reference: GEICO vs Progressive

| Aspecto | Progressive | GEICO |
|---|---|---|
| Estados disponibles | LA / OK / TX (3) | 50 states |
| MFA | OTP email (token + remember device) | OTP email (Phone/Email selector) |
| USDOT pre-check | SAFER widget (datos públicos) | Server-side eligibility (Yes/No HALT) |
| Auto-pop alcance | Dirección desde SAFER | Dirección + Email + Phones + Business Segment |
| Wizard structure | 7 pages | 7 pages (+ 1 dinámico DriveEasy Pro) |
| Vehicle Type combobox | ExtJS custom (click + click option) | Native `<select>` (mayoría) + algunos custom |
| Edge case business class | Sencha combobox con grupos | Lista plana 1,596 alfabéticas |
| Edge case VIN type conflict | No documentado | VIN decode > BlueQuote (regla) |
| STOP point | `AdditionalDetails` (antes de PAYMENT) | `Final Quote Details` (antes de MVR + PAYMENT) |
| Deliverable | Quote # + premium text capture | PDF directo desde `PrintQuote` link + premium text |

## Datos de prueba validados

| BlueQuote | USDOT | GEICO eligibility | Quote |
|---|---|---|---|
| `20260113_HUMBERTO_VILLARREAL` | 2033673 | ✅ Eligible (mapping manual) | $18,941/year |
| `20260528_REPUBLIC_AGGREGATE_HAULERS` | 8425025 | ❌ Not Eligible (NEW VENTURE, sin historial) — live 2026-05-28 vía `GEICOClient.create_quote` | HALT |
| (Progressive M&D test) `M&D CUSTOM FREIGHT` | 2998569 | ❌ Not Eligible | N/A |
| `20260127_FREIGHTZONE_LLC` | 3877502 | ⏳ NOT TESTED YET | — |
| `20260128_GEORGE_SORIANO` | 4070832 | ⏳ NOT TESTED YET | — |

**Patrón confirmado**: GEICO rechaza USDOTs de **new ventures** sin historial
operativo (M&D y REPUBLIC ambos). El `GEICOClient` lo detecta en el dashboard
(`EligibilityHaltError`) y retorna `QuoteResult(halted=True)` SIN reintentar
(client.py respeta `halted`). Para validar el wizard completo (Steps 1-7 +
precio + PDF) se necesita un USDOT elegible como HUMBERTO 2033673.

## Pendientes próxima sesión

1. **Implementar módulo `modules/geico/`** siguiendo este mapa + patrón de `modules/progressive/`
2. **Crear `docs/superpowers/plans/2026-05-XX-geico-module.md`** con plan detallado de implementación
3. **Probar BlueQuotes restantes** (FREIGHTZONE, SORIANO) para detectar más edge cases (coberturas con cargo, additional insureds, multi-vehicle, etc.)
4. **Field mapper coverage avanzado**: mapear cargo limits, hired auto, non-owned trailer cuando BlueQuote los traiga
5. **Print Quote retrofit en Progressive**: usar mismo patrón JS fetch para descargar el PDF de Progressive (gap documentado en AGENTS_CONTEXT)
6. **Remediar `.env` tracking** + rotar Gmail App Password expuesta
