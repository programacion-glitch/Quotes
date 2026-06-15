# Cola de Cotización RPA — Desacople intake / quoting + correo con impresión adjunta

**Fecha:** 2026-06-15
**Estado:** Diseño aprobado, pendiente plan de implementación
**Branch destino:** progressive-basepage-hardening (o branch nuevo)

## Problema

Hoy el orquestador (`workflow_orchestrator.py`) procesa cada correo de forma
**síncrona y en un solo hilo**: lee el inbox cada 60s, extrae la BlueQuote,
evalúa elegibilidad, **manda el correo de análisis al instante (paso 5)** y
recién después corre la cotización RPA de Progressive **inline y bloqueante**
(`_dispatch_to_progressive`, que internamente hace `asyncio.run`).

Esto tiene tres consecuencias:

1. **El correo de análisis NO lleva el precio ni la impresión de la cotización.**
   Se envía antes de cotizar. El objetivo del usuario es que el análisis llegue
   *"con la impresión de Progressive adjunta"*.
2. **El intake se bloquea** mientras corre un quote lento (un quote real llegó a
   556s — KATYLAND, 8 unidades). Durante ese tiempo no se procesan correos
   nuevos.
3. **Estado frágil en memoria.** El gate de aprobación manual usa un dict
   `_pending_approvals` (`workflow_orchestrator.py:82`) que se **pierde al
   reiniciar** el proceso.

Además, al inspeccionar el código se confirmó un hueco crítico para el objetivo:
**Progressive hoy NO produce ninguna impresión/PDF de salida.** Todas las
referencias a "pdf" en `modules/progressive/` son sobre la BlueQuote de
*entrada*. GEICO sí tiene `pdf_path` + `pdf_downloader.py`, pero ese endpoint
(`PrintQuote`) es **intermitente** (a veces devuelve JSON en vez del PDF).

## Objetivo

Desacoplar la recepción de correos de la cotización RPA mediante una **cola
durable en SQLite**, de modo que el correo de análisis se envíe **una sola vez,
cuando la(s) cotización(es) RPA terminan, con la impresión (PDF) adjunta**.

## Restricción de fondo: Progressive (y GEICO) NO toleran sesiones simultáneas

Evidencia en el propio código:

- Un solo login de agente por MGA (`PROGRESSIVE_USER`, GEICO `i070857`).
- `modules/progressive/client.py:104-108`: comentario de observación live —
  *"repeated fresh logins trip Progressive's 'maximum attempts of submitting an
  OTP' lockout (observed live 2026-06-10)"*.
- `modules/geico/client.py:43-47`: *"GEICO enforces a single session per agent
  (i070857): fresh logins invalidate the previous session and too many in a row
  can lock the account."*
- El estado de sesión es **un único archivo compartido por MGA**
  (`data/progressive_session.json`, `data/geico_session.json`) que incluye el
  device-trust del MFA. Dos browsers concurrentes se pisarían el storage_state.

**Conclusión:** la cola NO sirve para paralelizar dentro de un MGA (la
concurrencia segura es 1). Sirve para **desacoplar** (intake sigue aceptando
trabajo), **durabilidad** (sobrevive reinicios) y **reintentos**. La regla
"sesión única" es **por MGA, no global**: Progressive y GEICO son portales y
logins distintos, así que **un quote de Progressive y uno de GEICO sí pueden
correr en paralelo entre sí**.

## Decisiones de diseño (acordadas con el usuario)

1. **Mecanismo de cola:** SQLite durable (WAL), sin broker externo. RabbitMQ /
   Redis quedan descartados por ahora: sobredimensionados para un bot de una
   sola máquina, ~28 quotes/día, con concurrencia 1 por MGA. El disparador para
   reconsiderar un broker real sería escalar a varias máquinas o varios MGAs en
   paralelo.
2. **Timing del correo:** **un solo correo**, después de cotizar, con el/los PDF
   adjunto(s). Si NO hay MGA-RPA elegible, el análisis sale al instante (como
   hoy).
3. **Alcance MGAs:** diseño genérico (un worker por MGA-RPA). **Progressive
   arranca ON; GEICO detrás de `GEICO_QUEUE_ENABLED` (default OFF)** hasta cerrar
   sus filos conocidos (quote-resume, PDF intermitente).
4. **Impresión = página completa del precio final, a PDF, vía Playwright** —
   mismo mecanismo para ambos MGAs (ver sección dedicada). Reemplaza la
   dependencia del flaky `PrintQuote` de GEICO y cubre el hueco de Progressive.
5. **Mensajes humanizados dirigidos al AGENTE.** El correo de análisis lo recibe
   el agente interno de H2O (`rule_engine.summary_email`, por defecto la propia
   casilla del bot — confirmado en `workflow_orchestrator.py:217`), NO el cliente
   final. Por eso los mensajes se redactan **para el agente, con instrucción
   clara de acción o escalamiento** cuando corresponde. La capa técnica
   (`needs_manual_review`, `halted`, stack traces, rutas de screenshot) queda en
   DB/logs; el cuerpo del correo usa un **catálogo de traducción** claro, en
   español, sin jerga ni códigos internos.
6. **El gate `APROBAR` y el dispatch a MGAs-por-email quedan downstream e
   intactos.** El quote RPA corre automático solo para *enriquecer el análisis*
   (es seguro: ambos flujos frenan ANTES del bind/pago).

## Arquitectura

Paquete nuevo `modules/quote_queue/` con unidades chicas y bien delimitadas:

- **`models.py`** — `QuoteJob` dataclass + enum `JobStatus`. Dependency-free
  (igual criterio que `modules/geico/quote_result_types.py`).
- **`store.py`** — Job store durable sobre SQLite (WAL). Único punto de
  coordinación. API:
  - `enqueue(submission_id, mga, profile, effective_date) -> job_id`
  - `claim_next(mga) -> QuoteJob | None` (lease atómico)
  - `mark_terminal(job_id, status, premium, quote_number, pdf_path, screenshot_path, error)`
  - `mark_deferred(job_id, retry_after)`
  - `reclaim_stale()` (devuelve a `pending` los jobs con `lease_until` vencido)
  - `siblings_all_terminal(submission_id) -> bool`
  - `try_claim_submission_email(submission_id) -> bool` (un solo ganador)
  - `recently_quoted(mga, usdot, window) -> int` (idempotencia)
- **`worker.py`** — `QuoteWorker`, **uno por MGA**. Loop: `claim_next(mga)` →
  `XClient.create_quote(profile, effective_date)` → captura premium + PDF →
  `mark_terminal` → si `siblings_all_terminal` → `try_claim_submission_email` →
  arma y envía el correo de análisis con premiums + PDFs.
- **`messages.py`** — catálogo de traducción desenlace-técnico → mensaje humano
  (ver sección "Mensajes humanizados").
- **`runner.py`** — entrypoint. Levanta el monitor de inbox (productor) + N
  worker-threads (consumidores, uno por MGA habilitado) en el mismo proceso.
  Al arrancar llama `reclaim_stale()`.

### Cambios en código existente

- `workflow_orchestrator.py` — en `_process_submission`, reemplazar el envío
  inmediato del análisis + dispatch inline por: **encolar un job por MGA-RPA
  elegible** y guardar el contexto de la submission. Si no hay MGA-RPA elegible,
  enviar el análisis al instante (camino actual). El dispatch a MGAs-por-email,
  el upload a Drive y el gate `APROBAR` quedan donde están.
- `modules/progressive/quote_flow.py` — agregar `pdf_path: Optional[str]` al
  `QuoteResult` (GEICO ya lo tiene) y poblarlo en el step `rates`.
- `modules/progressive/pages/coverages_rates_page.py` y el page object del
  precio final de GEICO — agregar la captura PDF full-page.

## Captura de la impresión (Progressive + GEICO, mecanismo único)

- Al llegar a la página del **precio final** (Progressive: `rates`; GEICO:
  `Final Quote Details`), el page object captura **la página completa a PDF** con
  `page.pdf(print_background=True, prefer_css_page_size=True)` de Chromium —
  página entera, no solo el viewport.
- Esto **reemplaza** la dependencia del endpoint flaky `PrintQuote` de GEICO
  (causa del "PDF intermitente") y **cubre el hueco** de Progressive.
- `page.pdf()` solo funciona en **Chromium headless**, que es el default
  (`PROGRESSIVE_HEADLESS=true`, `GEICO_HEADLESS=true`). **Fallback** cuando se
  corre headed (debug): screenshot full-page PNG (`full_page=True`). Ambos son
  adjuntables al correo.
- El path resultante se guarda en `QuoteResult.pdf_path` y el worker lo persiste
  en `quote_jobs.pdf_path`.
- Los PDFs de salida se guardan bajo `data/quote_pdfs/` (no se commitean — entran
  al `.gitignore`, son data de cliente).

## Modelo de datos (SQLite, WAL mode)

Tabla `quote_jobs` — una fila por (submission × MGA):

| campo | tipo | uso |
|---|---|---|
| `id` | INTEGER PK | |
| `submission_id` | TEXT | agrupa los jobs de un mismo correo |
| `mga` | TEXT | `PROGRESSIVE` \| `GEICO` |
| `profile_json` | TEXT | `QuoteProfile` serializado (data extraída por la IA) |
| `effective_date` | TEXT | del subject |
| `usdot` | TEXT | para idempotencia |
| `status` | TEXT | `pending` → `claimed` → `running` → terminal |
| `attempts` | INTEGER | |
| `lease_until` | REAL | epoch; recuperación de crashes |
| `retry_after` | REAL | epoch; para `deferred` |
| `premium` | TEXT | resultado |
| `quote_number` | TEXT | resultado |
| `pdf_path` | TEXT | impresión |
| `screenshot_path` | TEXT | solo interno (no va al correo) |
| `error` | TEXT | técnico, solo interno |
| `created_at`, `updated_at` | REAL | |

Estados terminales: `quoted`, `failed`, `halted`. Estado transitorio especial:
`deferred` (re-encolable con backoff).

Tabla `submissions` — contexto para armar el correo:

| campo | uso |
|---|---|
| `submission_id` | PK. Se deriva del `Message-ID` del correo; si falta, fallback determinista a `hash(subject + usdot)` |
| `context_json` | `email_data`, evaluaciones, mga_list, tipo_negocio, commodity, business_name, subject |
| `email_sent` | flag para no mandar dos veces |
| `created_at` | |

Esto **reemplaza el `_pending_approvals` en memoria** (durable, sobrevive
reinicios).

## Concurrencia y seguridad de sesión

- **Un worker-thread por MGA.** Dentro de un MGA: estrictamente **serial** (un
  job a la vez → una sola sesión de browser → respeta sesión-única + evita el
  lockout de OTP). Entre MGAs: **paralelo** (portales/logins distintos).
- El budget duro de 700s y la política de retry de cada client se **preservan**:
  el worker solo llama `create_quote`, no reimplementa el control de browser.
- **Idempotencia:** antes de encolar/correr, `recently_quoted(mga, usdot,
  window)` honra la regla *"no re-cotizar el mismo USDOT >3x/día"*.

## Recuperación ante crash/reinicio

- Al arrancar el runner: `reclaim_stale()` devuelve a `pending` los jobs
  `claimed`/`running` con `lease_until` vencido (un crash a mitad de quote no
  deja el job colgado).
- La cola es durable → si el proceso muere, al volver sigue donde quedó.

## Ensamblado del correo (sin doble envío)

- Tras cada job terminal, el worker pregunta `siblings_all_terminal(submission_id)`.
  Si sí → `try_claim_submission_email(submission_id)` (transacción atómica: solo
  un worker gana) → arma y manda el análisis (reusando `build_analysis_email`)
  enriquecido con premiums + PDFs adjuntos.
- Cubre la carrera de Progressive y GEICO terminando casi a la vez.

## Manejo de errores y casos borde

Principio: **el humano nunca se queda esperando un correo que no llega.** Pase lo
que pase con la cotización, el análisis sale.

- **Quote falla / HALT (SSN, rechazo FMCSA, NoHit):** job `failed`/`halted` con
  `error` y `screenshot_path` (internos). El correo se envía igual, con el
  mensaje humanizado correspondiente y sin PDF de ese MGA. Los flags existentes
  (`needs_manual_review` de SSN, `UnderwritingRejectError` de FMCSA, `halted`,
  `is_stub`, `session_expired`) ya distinguen estos casos; el worker los mapea a
  un estado terminal y NO los reintenta cuando un reintento reproduciría el mismo
  resultado.
- **PDF ausente:** con `page.pdf()` full-page esto casi desaparece; si el render
  falla → análisis con premium y mensaje *"impresión no disponible"*.
- **Producto no disponible / OTP cooldown:** job → `deferred` con backoff. Si
  tras un máximo de espera los demás jobs ya terminaron → mandar el análisis con
  lo que haya + nota de pendiente.
- **GEICO detrás de `GEICO_QUEUE_ENABLED` (default OFF)** hasta cerrar
  quote-resume + PDF. Con el flag ON entra al mismo pipeline sin tocar nada más.
- **Confianza baja / commodity no mapeado:** comportamiento actual (HALT o
  not-found email). Esos casos **ni llegan a encolarse**.

### Mensajes humanizados (catálogo `messages.py`)

Dos capas separadas: **técnica** (DB/logs, para trazabilidad y reintentos) y
**humana** (correo al agente). El destinatario es el **agente interno de H2O**,
así que los mensajes están redactados para él: dicen qué pasó y, cuando hace
falta, **qué acción tomar o escalar**. El nombre del MGA y el premium se
interpolan.

| Desenlace técnico | Mensaje al agente |
|---|---|
| `quoted` (con PDF) | *"{MGA} cotizó: {premium}. Impresión de la página de precio adjunta."* |
| `quoted` sin PDF | *"{MGA} cotizó: {premium}. No se pudo generar la impresión esta vez; el precio quedó confirmado."* |
| `needs_manual_review` / NoHit (SSN) | *"{MGA} requiere el SSN del titular para verificar su identidad antes de cotizar. **Acción:** solicitar el SSN al cliente y reintentar — no se autocompleta por política de seguridad."* |
| `halted` / `UnderwritingRejectError` (FMCSA) | *"{MGA} no puede cotizar este negocio por sus reglas de elegibilidad (verificación FMCSA/USDOT). No requiere reintento; evaluar un MGA alternativo."* |
| `deferred` (producto no disponible / cooldown OTP) | *"Cotización de {MGA} pendiente (producto no disponible o espera de OTP). Se reintentará automáticamente; no requiere acción por ahora."* |
| `failed` (error técnico inesperado) | *"No se pudo completar la cotización de {MGA} automáticamente. **Acción:** revisar manualmente (detalle técnico en los logs internos)."* |

Stack traces, `error` crudo y rutas de `screenshot_path` **no** se vuelcan en el
cuerpo del correo; van a `logs/` y a la fila del job. El correo al agente puede
mencionar que "hay detalle en los logs", pero sin pegar el volcado.

## Testing (sin tocar la red)

- **Unit — `store.py`:** enqueue/claim/complete; idempotencia por `(mga, usdot)`;
  `reclaim_stale` (recuperación de lease vencido); `try_claim_submission_email`
  (un solo ganador bajo contención).
- **Unit — `worker.py`:** máquina de estados con un `FakeMGAClient` (sin browser)
  que devuelve `QuoteResult` quoted/failed/halted/deferred; verificar que el
  correo se arma solo cuando todos los hermanos están terminales, y que un fallo
  igual dispara el análisis.
- **Unit — `messages.py`:** cada desenlace mapea al texto humano correcto y NO
  filtra campos técnicos.
- **Unit — captura PDF:** el page object llama `page.pdf()` full-page y cae al
  PNG cuando headed (con un `page` mockeado).
- **Integración offline:** extender el estilo de `tests/simulate_progressive.py`
  para validar orquestador→cola→worker→correo estructuralmente, sin red.
- Correr con `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe`
  y pasar `pyflakes` (atrapa NameErrors de imports que `py_compile` no ve).

## Fuera de alcance (YAGNI)

- Broker externo (Rabbit/Redis) — SQLite alcanza.
- Paralelismo dentro de un MGA — la sesión única lo prohíbe.
- Cambios al gate `APROBAR` o al dispatch a MGAs-por-email.
- Cambios a los wizards salvo: (a) captura PDF full-page del precio final, y
  (b) `pdf_path` en el `QuoteResult` de Progressive.
- Resolver los filos de GEICO (quote-resume, PDF) — son prerequisito para
  encender `GEICO_QUEUE_ENABLED`, pero su fix vive en otro spec/plan.
