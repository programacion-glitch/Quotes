# Bot autónomo vía Gmail API — monitorear, cotizar (Progressive+GEICO), responder en hilo + etiquetar

**Fecha:** 2026-06-17
**Estado:** Diseño aprobado por el usuario, pendiente plan de implementación
**Branch destino:** progressive-basepage-hardening (o branch nuevo)
**Spec relacionado:** `docs/superpowers/specs/2026-06-15-rpa-quote-queue-design.md` (la cola RPA que este spec pone a correr de punta a punta)

## Objetivo

Dejar el bot corriendo **autónomo en este host**: monitorea el buzón
`quotes@h2oins.com`, lee cada correo nuevo no-leído que matchee el filtro de
asunto actual, lo analiza desde cero (extracción + elegibilidad), y si un MGA-RPA
(**Progressive y GEICO**) es elegible, lo cotiza. Cuando termina, responde **en el
mismo hilo del correo** con el análisis + la(s) impresión(es) PDF, dirigido a
`quotes@h2oins.com` con **CC a `programacion@h2oins.com`**, y aplica al correo
original la etiqueta de Gmail **`Cotizado-Bot`**.

## Problema / por qué hace falta este trabajo

Al inspeccionar el código se confirmaron dos huecos que impiden la operación
autónoma en esta máquina:

1. **El transporte de correo del flujo principal está bloqueado en este host.**
   `workflow_orchestrator.py` recibe por **IMAP** (`modules/email_receiver.py`)
   y envía por **SMTP** (`modules/email_sender.py`). El host (eScan / Acronis)
   **resetea las conexiones TLS de IMAP/SMTP de Gmail** (993/465/587) para
   procesos del host — por eso el OTP ya migró a la **Gmail API por HTTPS/443**
   (`modules/gmail_api_otp_reader.py`). Tal como está, el bot **no puede recibir
   ni enviar correo en esta máquina**. HTTPS/443 NO está bloqueado.
2. **No existe el consumidor de la cola.** La cola RPA (`modules/quote_queue/`)
   está construida y el orquestador **encola** (productor), pero **no hay
   `runner.py` que lance los workers** (consumidores). Hoy nadie procesa los
   jobs encolados → los quotes nunca corren y el correo de análisis nunca sale.

El RPA (Playwright + sesiones únicas de GEICO/Progressive + stealth) **debe**
correr en este host. Por lo tanto el bot corre acá y habla con Gmail por la API.

## Decisiones (acordadas con el usuario)

1. **Transporte:** Gmail API en este host (no IMAP/SMTP; no mover a Docker).
2. **Alcance MGA:** **Progressive + GEICO** (ambos por RPA). Se enciende
   `GEICO_QUEUE_ENABLED=true`. Riesgo conocido de GEICO: *quote-resume*
   (re-correr el mismo USDOT puede retomar un quote viejo) — mitigado por la
   regla de idempotencia (≤3x/día) y vigilancia al arrancar.
3. **Destinatarios del análisis:** `To: quotes@h2oins.com`, `CC:
   programacion@h2oins.com`. **NO** se incluye al remitente externo (seguimiento
   interno en el hilo).
4. **Arranque:** procesa **solo los no-leídos nuevos** que matcheen el **filtro
   de asunto actual** (`email.monitoring.subject_filter`). Lo ya leído/etiquetado
   se ignora.
5. **Etiqueta:** `Cotizado-Bot`, aplicada al correo original **cuando se envía el
   análisis** (cualquier desenlace: cotizó, falló o HALT).
6. **Fuera de alcance:** el dispatch a MGAs-por-email y el gate `APROBAR` quedan
   **intactos y manuales**. El bot automatiza solo el análisis + la cotización
   RPA. (El envío a MGAs-por-email sigue usando SMTP; migrarlo a Gmail API es un
   trabajo futuro si se necesita.)

## Arquitectura

### Componente nuevo: `modules/gmail_client.py`

Transporte Gmail API (HTTPS). Reusa el OAuth existente (`data/credentials.json`
+ `data/token.json`, mismo patrón que `gmail_api_otp_reader.py`). API:

- `fetch_unread(subject_filter: str) -> List[dict]` — lista los correos
  **no-leídos** (`is:unread`) que matchean el filtro de asunto, en el **mismo
  formato dict** que produce hoy `EmailReceiver.fetch_unread_emails` para que el
  resto del flujo (`document_extractor.extract_all`, `_process_submission`) no
  cambie:
  `{id, thread_id, message_id, subject, sender_name, sender_email, from, date,
  body, attachments:[{filename, data, content_type}], raw_message:None}`.
  - `id` = Gmail message id (para `mark_read` / `add_label`).
  - `thread_id` = Gmail `threadId` (para responder en el hilo).
  - `message_id` = header `Message-ID` (para `In-Reply-To` / `References`).
  - El parseo MIME (cuerpo + adjuntos) extiende `_extract_body` del OTP reader
    para también juntar adjuntos (`body.attachmentId` → `messages.attachments.get`).
- `send_threaded(*, to, cc, subject, body, attachments, is_html, thread_id,
  in_reply_to) -> bool` — arma un MIME (`To`, `Cc`, `Subject`, `In-Reply-To`,
  `References`, cuerpo, adjuntos desde paths o bytes), lo codifica base64url y
  llama `users.messages.send(userId="me", body={"raw": ..., "threadId":
  thread_id})`. El `threadId` mantiene la respuesta en el hilo.
- `add_label(message_id, label_name)` — asegura la etiqueta
  (`labels.list` → `labels.create` si falta; cachea el id) y
  `messages.modify(addLabelIds=[label_id])`.
- `mark_read(message_id)` — `messages.modify(removeLabelIds=["UNREAD"])`.

**Scope:** el token actual tiene `gmail.modify`, que según la API de Gmail
autoriza `messages.send` + `messages.modify` (labels) + lectura → **no requiere
re-consentimiento**. Verificación: el primer `send_threaded` confirma; si
devuelve 403 `insufficientPermissions`, agregar `gmail.send` a `SCOPES` y
re-correr `scripts/gmail_oauth_bootstrap.py` una vez (paso operativo único).

### Componente nuevo: `modules/quote_queue/runner.py`

Entrypoint del bot autónomo (reemplaza el `main()` que usaba IMAP). Un solo
proceso:

1. Al arrancar: `store.reclaim_stale()` (devuelve a `pending` los jobs
   `claimed`/`running` con `lease_until` vencido por un crash).
2. **Monitor de inbox (productor):** loop cada `check_interval` (60s) que llama
   `GmailClient.fetch_unread(subject_filter)` y, por cada correo,
   `orchestrator.process_email(email_data)`; al terminar (cualquier desenlace)
   `GmailClient.mark_read(id)`.
3. **Workers (consumidores):** un thread por MGA habilitado
   (`PROGRESSIVE`, y `GEICO` si el flag está ON). Cada worker corre
   `QuoteWorker.run_once()` en loop (con un sleep corto cuando la cola está
   vacía). Serial dentro del MGA (sesión única); paralelo entre MGAs.
4. Apagado limpio en `KeyboardInterrupt`/SIGTERM.

El monitor y los workers comparten el mismo `QuoteQueueStore` (SQLite WAL).

### Cambios en `workflow_orchestrator.py`

- `__init__`: construir un `GmailClient` compartido; leer `analysis_to`
  (`quotes@h2oins.com`) y `analysis_cc` (`programacion@h2oins.com`) de config.
- `start_monitoring`: ya no instancia `EmailReceiver`; el loop de monitoreo vive
  en `runner.py` y llama `process_email`. (Se puede dejar `start_monitoring`
  como wrapper que delega al runner, o moverlo al runner.)
- `_process_submission`:
  - Al guardar el contexto de la submission, incluir **`thread_id`,
    `message_id` (para `In-Reply-To`), `cc`** además de los campos actuales
    (`recipient`, `subject`, `body_html`, `attachment_paths`). `recipient` pasa a
    ser `analysis_to`.
  - Los caminos que mandan el análisis **al instante** (sin RPA elegible,
    rate-limited, not-found) usan `GmailClient.send_threaded(to=analysis_to,
    cc=analysis_cc, thread_id, in_reply_to=message_id, ...)` y luego
    `GmailClient.add_label(id, "Cotizado-Bot")`.
  - `_submission_id`: hoy saca el `Message-ID` de `email_data["raw_message"]`,
    que ahora es `None`. Cambiar para usar el campo `email_data["message_id"]`
    (con el mismo fallback `hash(subject+usdot)` si falta).
- Anti-loop: el guard actual `if "ANALISIS" in subject` ya hace que el bot
  ignore sus propios correos; además quedan leídos + etiquetados.

### Cambios en `modules/quote_queue/worker.py`

- `QuoteWorker` recibe el `GmailClient` (en vez de un `EmailSender` SMTP).
- **REQUISITO — los PDFs de las cotizaciones van ADJUNTOS al correo de análisis.**
  El worker ya arma la lista de adjuntos así (preservar este comportamiento):
  `attachments = list(ctx["attachment_paths"])  # BlueQuote original` +
  `[j.pdf_path for j in jobs if j.pdf_path]  # la impresión de la página de
  precio de CADA MGA que cotizó`. El correo de análisis debe salir con **una
  impresión PDF por cada MGA que produjo precio** (Progressive y/o GEICO).
- `maybe_send_submission_email`: usa
  `gmail.send_threaded(to=ctx["recipient"], cc=ctx["cc"], subject, body,
  attachments=attachments, is_html=True, thread_id=ctx["thread_id"],
  in_reply_to=ctx["in_reply_to"])` — `attachments` acepta paths o dicts bytes.
- Tras enviar OK: `gmail.add_label(ctx["message_id"], "Cotizado-Bot")`.
- La firma del contexto la produce el orquestador (arriba).
- **Captura del PDF de precio:** depende de que `QuoteResult.pdf_path` venga
  poblado. GEICO ya lo puebla (validado live: 5 quotes hoy con PDF de fallback en
  Final Quote Details). Progressive **aún NO** lo puebla (ver spec de la cola,
  sección "Captura de la impresión") — es un pre-requisito para que el correo de
  Progressive lleve PDF; si falta, el análisis igual sale con el premium y el
  mensaje "impresión no disponible".

### Captura del PDF de precio de Progressive (in-scope)

Requisito del usuario: **el correo de análisis debe llevar adjunta la impresión
de cada cotización**. GEICO ya puebla `QuoteResult.pdf_path`. Progressive **no**
— hay que agregarlo para que su correo lleve PDF:

- `modules/progressive/quote_flow.py`: agregar `pdf_path: Optional[str]` al
  `QuoteResult` y poblarlo en el step `rates` (la página de precio final).
- `modules/progressive/pages/coverages_rates_page.py`: al capturar el precio,
  guardar la **página completa a PDF** con
  `page.pdf(print_background=True, prefer_css_page_size=True)` (solo Chromium
  headless, que es el default). Fallback headed: screenshot full-page PNG.
- Path bajo `data/quote_pdfs/` (gitignored, data de cliente).
- Si la captura falla, el análisis igual sale con premium + "impresión no
  disponible" (no bloquea el correo).

### Config (`.env` / config_manager)

| clave | valor | uso |
|---|---|---|
| `rule_engine.geico_queue_enabled` | `true` | enciende GEICO en la cola |
| `email.analysis_to` | `quotes@h2oins.com` | To del análisis (default: `email.username`) |
| `email.analysis_cc` | `programacion@h2oins.com` | CC del análisis |
| `email.monitoring.subject_filter` | (el actual) | filtro de no-leídos |
| `email.label_processed` | `Cotizado-Bot` | etiqueta a aplicar |

## Flujo de datos (end-to-end)

```
runner: reclaim_stale()
loop monitor (60s):
  GmailClient.fetch_unread(subject_filter)
    -> por cada correo:
        orchestrator.process_email(email_data)   # extrae, evalúa, encola RPA
        GmailClient.mark_read(id)
workers (1 por MGA, en paralelo entre MGAs, serial dentro):
  QuoteWorker.run_once():
     claim_next(mga) -> create_quote(profile, eff_date) -> mark_terminal
     si siblings_all_terminal && gana try_claim_submission_email:
        GmailClient.send_threaded(to=quotes@, cc=programacion@,
                                  thread_id, in_reply_to, +PDFs)
        GmailClient.add_label(message_id, "Cotizado-Bot")
```

Si NO hay MGA-RPA elegible (o todos rate-limited / not-found): el orquestador
manda el análisis al instante por `GmailClient.send_threaded` + etiqueta, sin
encolar.

## Manejo de errores y casos borde

- **Principio (heredado de la cola):** el humano nunca espera un correo que no
  llega — el análisis sale aunque el quote falle/HALT (mensajes humanizados ya
  existen en `messages.py`).
- **Marcado leído siempre:** todo correo procesado se marca leído tras el
  callback (éxito, skip por baja confianza, sin adjuntos, not-found) para no
  reprocesarlo en el siguiente poll. La etiqueta `Cotizado-Bot` se aplica solo
  cuando se ENVÍA un análisis; los skips silenciosos quedan leídos sin etiqueta
  (se loguean).
- **GEICO quote-resume:** mitigado por `recently_quoted(mga, usdot, 24h) <= 3`
  (ya implementado). Vigilar las primeras corridas.
- **Token Gmail vencido:** `GmailClient` refresca el token (igual que el OTP
  reader); si el refresh falla, loguea claro y el monitor sigue intentando en el
  próximo ciclo (no tumba el proceso).
- **Crash a mitad de quote:** la cola es durable; `reclaim_stale()` al reiniciar.
- **Carrera Progressive/GEICO terminando juntos:** `try_claim_submission_email`
  garantiza un solo correo (ya implementado).

## Testing (sin tocar la red)

- **Unit `gmail_client.py`** (servicio Gmail mockeado):
  - `send_threaded` arma el `raw` con `To`/`Cc`/`Subject`/`In-Reply-To`/
    `References` correctos y pasa `threadId`.
  - `add_label` crea la etiqueta si no existe y llama `modify` con el id; reusa
    el id si ya existe.
  - `fetch_unread` mapea la respuesta del API al dict esperado (incl. adjuntos y
    `thread_id`/`message_id`).
  - `mark_read` quita `UNREAD`.
- **Unit `runner.py`** con `FakeGmailClient` + `FakeMGAClient`: el monitor llama
  `process_email` + `mark_read` por correo; los workers drenan la cola; el correo
  se arma una sola vez cuando todos los hermanos terminan.
- **Worker** (ya existe el patrón): verificar que llama `send_threaded` + label
  con el contexto extendido.
- Correr con `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe`
  y pasar `pyflakes`.

## Despliegue / operación

- Entrypoint: `python -m modules.quote_queue.runner` (o un wrapper
  `scripts/run_bot.py`).
- Dejar corriendo en este host (servicio de Windows o consola persistente — a
  definir en el plan; análogo al servicio "OpenAI Local Proxy").
- Pre-requisito: `data/token.json` válido (ya existe para el OTP).

## Fuera de alcance (YAGNI)

- Migrar el dispatch a MGAs-por-email a Gmail API (sigue SMTP; APROBAR intacto).
- Reemplazar `_pending_approvals` en memoria por la tabla durable (downstream).
- Broker externo / paralelismo dentro de un MGA (la sesión única lo prohíbe).
- Resolver los filos de GEICO (NUNEZ, quote-resume) — viven en otros specs; la
  idempotencia los acota para la operación autónoma.
