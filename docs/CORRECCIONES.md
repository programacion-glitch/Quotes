# Correcciones de negocio — contexto y changelog

Documento vivo. Cuando llegue una ola de correcciones (normalmente Diana
respondiendo a un correo `[ANALISIS]`), este archivo da el contexto para
retomar sin re-explicar nada, y el changelog registra qué se ajustó, cuándo
y con qué regla/commit.

## Cómo trabajamos una ola de correcciones

1. **Enlistar** los puntos (página, campo, qué hizo el bot vs. qué esperaba
   negocio), citando capturas/quotes de referencia.
2. **Cruzar contra los registros**: reglas de elegibilidad (Excel de reglas)
   y decisiones de flujo (`config/mga_decision_rules.xlsx`, IDs `R-xxx`).
   Filas EN-DUDA que negocio valida pasan a VIGENTE; lo nuevo se agrega.
3. **Aplicar**: datos primero (Excels), después código (con tests), después
   correo de análisis si cambia el formato.
4. **Commit citando el R-ID** y actualizar el changelog de abajo.
5. Si se tocó el Excel de reglas → **subir la versión nueva al master de
   Drive** (ver "archivos vivos").

## Archivos vivos (¡no confundir!)

| Archivo | Rol |
|---|---|
| `config/CHECK LIST (2)_ESTANDARIZADO.xlsx` | **Reglas de elegibilidad VIVAS** — es lo que lee el rule engine (`settings.yaml: excel_checklist`), hoja `REGLAS FINALES`. Master en Drive (programacion@, id en `REGLAS_DRIVE_FILE_ID`); el sync lo baja al arrancar y **pisa lo local**. `REGLAS_SYNC_ENABLED=false` desde 2026-08-03 hasta subir el corregido a Drive. |
| `config/REGLAS_quotes.xlsx` | Solo la copia local que escribe `tools/read_sheet_as_user.py`. **Nadie en producción la lee.** |
| `config/mga_decision_rules.xlsx` | Decision Ledger: decisiones del flujo web Progressive/GEICO (`R-001…R-087`). Estados: VIGENTE (validada por negocio) / EN-DUDA (default técnico, agenda con Diana). |
| `data/quote_queue.db` | Cola + `decisions_json` por job (qué decidió el bot en cada quote — la evidencia). |

Convenciones de fuente en el ledger/correo: `RULE`/`MATCHED` = confiable;
`DEFAULT`/`DEFAULTED`/`AI` = dudosa (sale con ⚠ en el correo de análisis).

## Changelog de ajustes

### 2026-08-04 — Ola 2: respuestas de Diana a las 8 dudas de PANTHER

Diana respondió las 8 preguntas técnicas (queda pendiente agendar la sesión
EN-DUDA). Reglas resueltas:

- **R-002/R-087 (VIGENTE)** — Filings Progressive: ≤500 millas → ESTATAL,
  >500 → FEDERAL. Ambos permisos activos (los 3 pre-marcados por SAFER) →
  se dejan los 3; si no → según el radio. Authority Number no se llena.
  ✅ implementado en FilingProofPage (`filing_selection`). ⏳ validación live.
- **R-078 (VIGENTE)** — Filings GEICO: intraestatal exige el TXDMV# (campo
  `TXDOT#` de la Blue Quote; GEICO bloquea sin él); TXDOT N/A → No por el
  momento; >500 mi/ilimitado → Yes solo MC (2 primeros). ✅ implementado:
  `ApplicantProfile.txdot` + `filing_mode`/`txdmv_number` en el mapper +
  `_fill_filing_details` (el DOM exacto de los sub-campos queda best-effort
  con WARN hasta la validación live).
- **R-013/R-015 (VIGENTE)** — Clasificación por TRAILER cuando el commodity
  no mapea (también GEICO): dry van/flatbed → General Freight; reefer →
  Refrigerated Goods; auto hauler → Auto Hauler; S&G → Dirt Sand and Gravel;
  scrap → Scrap Metal; dump → S&G o Scrap según commodity; tank / cement
  mixer / logging / no-reflejable → Trucker + "Other for hire". Resuelve el
  caso JUAREZ (PACKED CHARCOAL en dry van → General Freight). ✅ implementado
  en Progressive (business type fallback + subtipo ampliado + match tolerante
  de "Other for hire"); en GEICO aplica vía el mapper de business class
  existente. ⏳ validación live.
- **Rule engine — 4 columnas nuevas** (✅ implementado + CHECK LIST poblado):
  - `MAX_VEHICLE_AGE_YEARS=15`: MAXIMUM, COVER WHALE, MJ HALL, PROFESSIONAL
    RRG, TUMI, FUTURISTICS, COUNTY HALL, AONE (descartan >15 años).
  - `MIN_VEHICLE_YEAR=2001`: XPT, STAR MUTUAL.
  - `REQUIRES_MECH_INSPECTION=YES` (warning, no descarta): AMWINS, UNIVERSAL
    CASUALTY, SGA, SIU, NOVATAE, GSIAY, INVO.
  - `MAX_RADIUS_MILES=200`: INVO (excede → se DESCARTA, no se advierte).
  - `REQUIRED_COVERAGES=AL,MTC,APD` en filas NV de Great West: sin paquete
    completo se descarta con motivo.
- **Great West + UIIA (resuelto)** — UIIA es flatbed que va al puerto: NV sí
  aplica con paquete completo + único conductor + tractor y trailer
  identificados + contrato.

### 2026-08-03 — Ola PANTHER EXPRESS (13 puntos de Diana + 4 hallazgos)

Referencia: PANTHER EXPRESS TRUCKING LLC, USDOT 4514637, quote CA117638002.
Commits `2484124..00d765f` en `progressive-basepage-hardening`.

**Reglas de elegibilidad** (CHECK LIST, hoja REGLAS FINALES):
- INVO: solo S&G, sin NV, ≤200 mi, cámaras (8 filas de otros tipos eliminadas).
- SGA: `IS_NEW_VENTURE=NO` (mínimo 3 años — nunca NV).
- Novatae: `ROUTING=SOLO_NICO` en las 19 filas.
- County Hall: sí acepta NV (`IS_NEW_VENTURE` limpiado) + `REQUIRES_APP_NV=YES`.
- XPT: `REQUIRES_APP_NV=YES` (app de new venture).
- Great West: eliminadas 6 filas NV contradictorias (NV solo dry van/flatbed/
  reefer); notas NV (3 coberturas + único driver camión+trailer).
- Paramount (camiones ≤15 años, form+preguntas+excel), Rocklake (loss runs
  MTC/APD sí o sí), Futuristics (ELD + quote form), Berkshire (plataforma
  online; NO con drivers de otros estados/internacionales): notas.
- Rule engine: columna nueva `REQUIRES_APP_NV` (app exigible solo a NV).

**Código**:
- R-085 (nueva, VIGENTE): zip de garaging = PHYSICAL address, no mailing
  (Prog + GEICO). `ApplicantProfile.physical_zip`.
- R-015 (→VIGENTE): Type of Trucker según operación — reefer→Refrigerated
  Goods, dry van/flatbed→General Freight/Other (fuente RULE).
- R-087 (nueva, EN-DUDA): interstitial **Filing/Proof of Insurance** — página
  que Progressive muestra desde que R-002 responde Yes; mataba todas las
  quotes (morían esperando el premium). `FilingProofPage`: radio include-all-
  vehicles=Yes, checkboxes como Progressive los pre-marca. ⏳ Validación live
  pendiente.
- R-002 (refinada): filings siempre Yes; State vs Federal según radio —
  criterio exacto pendiente con Diana.
- R-086 (nueva, VIGENTE): PDF de Progressive con nombre
  `AAAA-MM-DD {negocio} Progressive {quote#}.pdf` — ✅ implementado
  (`quote_pdf_basename` en pdf_downloader; la descarga del PDF oficial ya
  existía desde julio). El destino final (subcarpeta "quotes" del cliente)
  queda para el alcance D3. ⏳ Validación live pendiente.

**Correo de análisis**:
- Dedupe por MGA (Great West salía en elegibles Y no elegibles a la vez).
- Notas por compañía COMPLETAS en cada fila (requisito de Diana).
- Desbloqueables: Paramount/Novatae entran (REQUIRES_QUESTIONS ahora es
  "Faltan:…"), XPT/County Hall vía app NV; sección "Requisitos por MGA".

**Hallazgos técnicos de la investigación**:
- Contenedor muerto 3 días (exit 137) — correos 31-jul→03-ago sin procesar.
- GEICO: Imperva bloqueaba el chromium-headless-shell (Error 15) → GEICO
  headful + Xvfb directo en Docker (xvfb-run cuelga sin xdpyinfo);
  healthcheck anclado a `^python`. Validado sin Error 15.
- El rule engine vive en CHECK LIST, no en REGLAS_quotes (correcciones
  portadas; sync de Drive apagado hasta subir el master).
- Tokens OAuth vencidos (quotes@ y programacion@) → re-auth pendiente.

**Alcance nuevo (NO implementado)**: ver
`docs/superpowers/plans/2026-08-03-alcance-d-panther-feedback.md`
(analizar negocios con años, excel de prospectos, carpetas Drive del
cliente, nombre del PDF).

### 2026-07-29 — Decision Ledger + servicio transparente

- Bot 100% transparente sobre el buzón de ventas (dedup por message-id en
  SQLite, cero etiquetas/leídos); análisis = correo NUEVO a
  `EMAIL_ANALYSIS_TO` (dianarubio@ durante estabilización).
- Correo con el "por qué" del rule engine + tabla "Decisiones tomadas"
  (⚠ dudosas primero) para Progressive y GEICO.
- `config/mga_decision_rules.xlsx` creado (84 reglas; 65 EN-DUDA = agenda).
- Hallazgo: R-079 — GEICO no aplica las coberturas del BlueQuote (acepta
  defaults del portal); primas Prog/GEICO no comparables.

### 2026-07-06 — Filings + remitentes

- R-002: radio "Are state or federal filings required?" → Yes cuando aparece
  (cliente con autoridad). *(Efecto colateral descubierto el 03-08: revela el
  interstitial Filing/Proof.)*
- Specs de descarga del PDF oficial (RATES → Print/Send → PDFHandler.ashx)
  y filtro de remitentes de ventas.

### 2026-06-25 — Fixes live Progressive (Diana)

- Detección de decline → `not_eligible` (ALMA FORCE).
- R-006: radio de operación = bracket discreto ('500 miles' exacto).
- Casilla GL en Q1 de Other Business Insurance; email del cliente (R-003).

### 2026-06-11/16 — GEICO stealth + wins

- Imperva Incapsula bloqueaba submits (UA truncado, navigator.webdriver) →
  `modules/geico/stealth.py`. Wins live: SOLANO $17,596, FGF $28,580,
  RAFYURY $33,699, etc.
