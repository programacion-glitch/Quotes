# Feedback Diana Rubio — Cotización Progressive ELITE TRANSPORT ENTERPRISES LLC

- **Cliente:** ELITE TRANSPORT ENTERPRISES LLC · USDOT 2857089 · TX
- **Fecha feedback:** 2026-06-25 (revisora: Diana Rubio)
- **Quote del bot revisada:** $206,224/año #CA117254900 (precio inflado — varias causas abajo)
- **Blue Quote:** `ae740c55-20260622__BLUE_QUOTE.pdf`

## Verdad de la Blue Quote (extraída de los campos del PDF)

- Owner: LUIS JR MIRELEZ · Business: ELITE TRANSPORT ENTERPRISES LLC
- Email cliente: **elitetransport77@yahoo.com**
- Current carrier: WILSHIRE INSURANCE COMPANY (8 años continuos) → **NO es new venture**
- **Radio de operación: `500 MILES`** (bracket ≤500, NO ilimitado)
- Commodity: **Building Materials 100%**
- GL solicitado: **1,000,000 / 2,000,000** (General aggregate $2,000,000)
- Cargo: $100,000 · Phys Dmg Ded: $1,000
- **4 power units** (tractores): 2005 PTRB, 2007 PTRB, 2007 FRHT, 2001 PTRB (todos Tractor Truck, GVW 80k; 2 con valor APD, 2 sin)
- **5 trailers** (flatbed): GreatDane, Transcraft, Wabash, Transcraft, Doonan
- **4 drivers:** LUIS JR MIRELEZ, IRVING PENA, JASON MARTINEZ, GUILLERMO CANTU (todos TX, clase A, 0 acc/viol)

---

## Triage de los 16 puntos

Leyenda: 🟢 quick win (confirmado, sin dudas) · 🟡 cambio de reglas (REGLAS FINALES) · 🔵 feature nuevo · ❓ necesita aclaración de Diana · 🔍 verificar en vivo

### A. Automatización Progressive (`modules/progressive/`)

| # | Punto Diana | Estado | Ubicación | Acción |
|---|-------------|--------|-----------|--------|
| 1 | Roadside Assistance no se agrega | 🟢 | `coverages_rates_page.py:179` salta el set cuando == default | Setear SIEMPRE Roadside Assistance (la correcta es "Selected w/ $250 Deductible") |
| 2 | Email del cliente falta en la quote | 🟢 | `quote_flow.py:152-156` no pasa `customer_email` a more_business; el handler ya existe (`more_business_page.py:48-62`) | Mapear email + pasarlo |
| 3 | Marcar casilla GL (descuento) | 🟢 | `more_business_page.py:83-95` recibe `other_coverages="None"` hardcodeado en `quote_flow.py:154` | Detectar GL solicitado (profile.coverages tiene "GL") → tildar "General Liability" |
| 4 | Radio 500mi quedó como ">500/ilimitado" | 🟢/🔍 | `vehicles_page.py:895` substring greedy ("500" matchea ">500") + default `"Over 500 miles"` (`field_mapper.py:29,157`) | Arreglar mapeo: 500→bracket ≤500. **Verificar opciones reales del combo en vivo (PW MCP)** |
| 5 | Clasificación: debe ser Commercial Trucker / General Freight; commodity = lo que carga tal cual | 🟡/❓ | `business_type_classifier.py:123-149`, `mappings.py:104-142`, subtype en `business_info_page.py:513-575` | Mapear "Building Materials" → Commercial Trucker/General Freight (tabla o learned cache). Confirmar nombres exactos de categoría/subcategoría |
| 6 | Solo 2 drivers, son 4 | 🔍 | `quote_flow.py:397-412` agrega todos los no-policyholder (sin cap) | El log del run mostró 4 agregados → posiblemente Diana vio un run viejo o el PDF cortó. **Verificar en próximo run** |
| 7 | Falta: Named Additional Insured + Waiver of Subrogation | 🔵❓ | NO implementado (sin campos ni handler) | Diana puso 1 y 1. **¿De dónde sale el número? (¿default 1? ¿del request?)** Implementar |
| 8 | Falta: Filings (state/federal) | 🔵❓ | Solo "filings required?" hardcodeado No (`more_business_page.py:97-104`) | La correcta: filings=Yes, State, Filing Types=Liability, "include all vehicles?"=Yes. **¿Cuándo aplica state vs federal? (¿intrastate TX → State?)** |
| 9 | Falta: casillas señaladas en sección "business" | 🟢 | 2da pregunta "within 45 days" → "None of the above" (ya se tilda); 1ra pregunta es la de GL (#3) | Cubierto por #3 + verificar 2da pregunta |

### B. Rule engine / elegibilidad MGA

| # | Punto Diana | Estado | Ubicación | Acción |
|---|-------------|--------|-----------|--------|
| 10 | GEICO toma como elegible pero NO lo es | 🟡❓ | Filas GEICO en REGLAS FINALES sin MIN_UNITS/etc → pasa siempre | **¿Por qué NO es elegible GEICO aquí? (commodity building materials? flatbed? GVW? unidades?)** Encodear la regla real |
| 11 | Great West marcado no-elegible por GL, pero SÍ hacen GL | 🟡 | `rule_engine.py:301-311` ALLOWED_COVERAGES de Great West sin "GL" | Agregar "GL" a ALLOWED_COVERAGES de Great West en REGLAS FINALES |
| 12 | Novatae acepta pero exige ELD → ponerlo como requisito | 🟡🔵 | ELD vive en NOTAS_EXTRA, no se evalúa | Modelar ELD como requisito (col REQUIRES_ELD + lógica) y mostrarlo como "falta para desbloquear", no decline |
| 13 | Futuristics: cliente debe enrolarse en TruckerCloud antes de cotizar | 🔵❓ | No modelado | Modelar precondición/“sujeto a” y mostrarla en análisis |
| 14 | Berkshire: online, se puede someter; análisis dice "sujeta a" | 🟡 | No está en WEB_AUTOMATION_MGAS; ROUTING vacío | Marcar como submission online "sujeto a" en el análisis |
| 15 | "Unidades" = solo power units (4), no 9 (trailers aparte) | 🟡 | `document_ai_extractor.py:683` count = trucks + trailers | Separar `power_units` vs `trailers`; reglas/MIN_UNITS y display usan power_units |
| 16 | Mostrar qué FALTA para desbloquear MGAs (no solo "declinado") | 🟡 | Ya existe parcial: `analysis_email_builder.py:100-111` (`_is_only_missing_docs`, sección "Desbloquea") | Extender a requisitos (ELD, TruckerCloud, etc.), no solo documentos |

### C. Drive / PDF / prospectos

| # | Punto Diana | Estado | Ubicación | Acción |
|---|-------------|--------|-----------|--------|
| 17 | Guardar en carpeta del cliente → subcarpeta "2. QUOTES" → nombre `AÑO,MES,DIA` + "Progressive" | 🟡 | `drive_manager.py:238-345` carpeta plana "{business} USDOT {usdot}", nombre original | Crear subcarpeta "2. QUOTES" + renombrar `YYYY,MM,DD Progressive ...` |
| 18 | Es PRINT/indicación, NO se envía al vendedor; "quote" solo para formal | 🟢 | Ya es interno ("impresión", al agente, no al vendedor). Pero el archivo se llama `progressive_quote_{n}.pdf` | Renombrar archivo a "indication"/"indicación" (no "quote") |
| 19 | Bot marca en Excel de prospectos las compañías enviadas + precio | 🔵❓ | NO existe ningún mecanismo | **¿Automático por el bot o manual?** Si auto: ubicación del Excel + columnas |

---

## Preguntas que bloquean implementación (para Diana)

1. **GEICO (#10):** ¿cuál es el criterio real por el que NO es elegible para este perfil? (commodity, flatbed, GVW, # unidades, otro)
2. **Additional Insured / Waiver (#7):** ¿el número (1/1) es un default fijo o sale del request/otro documento?
3. **Filings (#8):** ¿qué determina state vs federal? (¿interstate→federal, intrastate TX→state?) ¿Authority Number de dónde?
4. **Radio (#4):** confirmar opciones reales del combo Progressive (¿existe "500 miles" discreto vs ">500"?). Se verifica en vivo.
5. **Prospectos (#19):** ¿el bot lo escribe automático? Si sí: ruta del Excel + columnas (compañía, precio, fecha, estado).

## Quick wins listos para implementar YA (sin aclaración)

#1 Roadside · #2 Email cliente · #3 GL checkbox · #11 Great West GL · #15 separar power_units/trailers · #17 carpeta "2. QUOTES" + naming · #18 renombrar PDF a "indication". (#4 radio y #6 drivers: verificar en vivo.)
