# Decision Ledger + Análisis explicado + Servicio transparente — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Runner 100% transparente sobre el buzón de ventas (sin etiquetas/mark-read, dedup por message-id), correo de análisis NUEVO solo a Diana con el "por qué" del rule engine y la tabla "Decisiones tomadas" del nuevo Decision Ledger (Progressive + GEICO), respaldado por un registro de reglas en Excel versionado.

**Architecture:** El ledger es un módulo puro con estado thread-local (un worker-thread por MGA en el mismo proceso); `choice_resolver` lo alimenta automáticamente y los sitios hardcodeados lo citan con `rule_id`. El worker captura `entries()` tras `create_quote` y las persiste en una columna nueva de `quote_jobs`; el correo se arma desde ahí. La dedup de correos pasa de etiquetas Gmail a una tabla `seen_emails` en la cola SQLite.

**Tech Stack:** Python 3.12, SQLite (WAL), Gmail API, openpyxl, pytest.

**Spec:** `docs/superpowers/specs/2026-07-29-progressive-decision-ledger-design.md`

## Global Constraints

- Python NO está en PATH: usar `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe` (abreviado `<PY>` en los comandos).
- Tests: `<PY> -m pytest <archivo> -v` desde la raíz del repo. La suite completa tiene **2 fallas pre-existentes en `tests/test_rule_engine.py`** — son conocidas y NO se arreglan en este plan.
- NUNCA commitear `.env`, `data/token.json`, `data/credentials.json`, ni nada bajo `data/`.
- El bot NUNCA etiqueta, marca leído, ni modifica el correo original de ventas. NUNCA responde en el hilo de ventas.
- `decision_ledger.record()` es best-effort: NUNCA lanza hacia el caller.
- El bot NO lee `config/mga_decision_rules.xlsx` en runtime — es registro humano.
- En código de pages de Progressive/GEICO: NUNCA `page.fill/click/select_option` directo — solo primitivas BasePage (acá solo agregamos llamadas a `decision_ledger.record`, no interacción nueva).
- Commits en español, formato `feat(scope):` / `fix(scope):` como el historial.

---

### Task 1: Store — dedup por message-id + columna `decisions_json`

**Files:**
- Modify: `modules/quote_queue/store.py` (`_create_tables`, `_row_to_job`, `mark_terminal`; método nuevo `try_claim_email`)
- Modify: `modules/quote_queue/models.py` (campo `decisions_json` en `QuoteJob`)
- Test: `tests/quote_queue/test_store.py` (agregar tests al final)

**Interfaces:**
- Consumes: nada nuevo.
- Produces: `QuoteQueueStore.try_claim_email(gmail_id: str) -> bool` (True solo la PRIMERA vez para ese id — atómico). `mark_terminal(..., decisions_json: Optional[str] = None)`. `QuoteJob.decisions_json: Optional[str]`.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar al final de `tests/quote_queue/test_store.py`:

```python
class TestSeenEmails:
    def test_try_claim_email_first_time_true(self, tmp_path):
        store = QuoteQueueStore(tmp_path / "q.db")
        assert store.try_claim_email("gmail-abc-123") is True

    def test_try_claim_email_second_time_false(self, tmp_path):
        store = QuoteQueueStore(tmp_path / "q.db")
        store.try_claim_email("gmail-abc-123")
        assert store.try_claim_email("gmail-abc-123") is False

    def test_try_claim_email_distinct_ids_independent(self, tmp_path):
        store = QuoteQueueStore(tmp_path / "q.db")
        assert store.try_claim_email("id-1") is True
        assert store.try_claim_email("id-2") is True

    def test_claim_survives_reopen(self, tmp_path):
        """La dedup es durable: sobrevive reinicios del proceso."""
        db = tmp_path / "q.db"
        QuoteQueueStore(db).try_claim_email("id-1")
        store2 = QuoteQueueStore(db)
        assert store2.try_claim_email("id-1") is False


class TestDecisionsJson:
    def test_mark_terminal_saves_decisions_json(self, tmp_path):
        store = QuoteQueueStore(tmp_path / "q.db")
        jid = store.enqueue("sub-1", "PROGRESSIVE", "{}", None, "123")
        store.mark_terminal(jid, "quoted", premium="$1,000",
                            decisions_json='[{"field": "Roadside"}]')
        job = store.get_jobs("sub-1")[0]
        assert job.decisions_json == '[{"field": "Roadside"}]'

    def test_mark_terminal_decisions_json_default_none(self, tmp_path):
        store = QuoteQueueStore(tmp_path / "q.db")
        jid = store.enqueue("sub-1", "PROGRESSIVE", "{}", None, "123")
        store.mark_terminal(jid, "failed", error="error")
        assert store.get_jobs("sub-1")[0].decisions_json is None
```

(Usar los imports ya presentes en el archivo; si `tmp_path` no se usa aún ahí, es el fixture builtin de pytest — no requiere setup.)

- [ ] **Step 2: Verificar que fallan**

Run: `<PY> -m pytest tests/quote_queue/test_store.py -v -k "SeenEmails or DecisionsJson"`
Expected: FAIL (`AttributeError: ... no attribute 'try_claim_email'` y `TypeError: mark_terminal() got an unexpected keyword argument`).

- [ ] **Step 3: Implementación**

En `modules/quote_queue/store.py`:

(a) En `_create_tables`, dentro del `executescript` existente, agregar la tabla:

```sql
CREATE TABLE IF NOT EXISTS seen_emails (
    gmail_id TEXT PRIMARY KEY,
    seen_at REAL NOT NULL
);
```

y DESPUÉS del `executescript` (aún dentro del `with self._lock`), la migración aditiva (la DB de producción `data/` ya tiene `quote_jobs` creada):

```python
# Migración aditiva: quote_jobs ya existe en producción sin esta columna.
try:
    self._conn.execute("ALTER TABLE quote_jobs ADD COLUMN decisions_json TEXT")
except sqlite3.OperationalError:
    pass  # columna ya existe
self._conn.commit()
```

(b) Método nuevo (junto a `try_claim_submission_email`):

```python
def try_claim_email(self, gmail_id: str) -> bool:
    """Reclama un correo por su Gmail message-id. Atómico y durable:
    True solo la PRIMERA vez — la dedup del monitor vive acá, NO en
    etiquetas de Gmail (el buzón de ventas no se toca)."""
    now = time.time()
    with self._lock:
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO seen_emails (gmail_id, seen_at) VALUES (?, ?)",
            (gmail_id, now),
        )
        self._conn.commit()
        return cur.rowcount == 1
```

(c) `mark_terminal`: agregar parámetro `decisions_json=None` y sumarlo al UPDATE (`decisions_json=?` con `_sqlite_safe(decisions_json)`).

(d) `_row_to_job`: agregar `decisions_json=row["decisions_json"]`.

En `modules/quote_queue/models.py`, agregar al dataclass `QuoteJob` (al final, con default):

```python
decisions_json: Optional[str] = None
```

- [ ] **Step 4: Verificar que pasan + sin regresiones**

Run: `<PY> -m pytest tests/quote_queue/test_store.py -v`
Expected: PASS todos (los previos y los nuevos).

- [ ] **Step 5: Commit**

```bash
git add modules/quote_queue/store.py modules/quote_queue/models.py tests/quote_queue/test_store.py
git commit -m "feat(queue): dedup durable por message-id (seen_emails) + columna decisions_json"
```

---

### Task 2: Runner transparente — `poll_once` sin etiquetas

**Files:**
- Modify: `modules/quote_queue/runner.py` (`poll_once`, `run_forever`)
- Test: `tests/quote_queue/test_runner.py`

**Interfaces:**
- Consumes: `store.try_claim_email(gmail_id) -> bool` (Task 1).
- Produces: `poll_once(gmail, orchestrator, subject_filter, store, after_epoch=None, rt_senders=None, new_venture_senders=None) -> int` — el parámetro `seen_label` DESAPARECE; `store` es ahora obligatorio (4º posicional).

- [ ] **Step 1: Escribir los tests que fallan**

En `tests/quote_queue/test_runner.py`, agregar (adaptar imports a los del archivo):

```python
class _MailboxGuardGmail:
    """Gmail fake que EXPLOTA si el bot intenta modificar el buzón."""
    def __init__(self, emails):
        self._emails = emails

    def fetch_unread(self, *a, **k):
        return self._emails

    def add_label(self, *a, **k):
        raise AssertionError("El bot NO debe etiquetar correos (transparencia)")

    def mark_read(self, *a, **k):
        raise AssertionError("El bot NO debe marcar leído (transparencia)")


class _SpyOrchestrator:
    def __init__(self):
        self.processed = []

    def process_email(self, email_data):
        self.processed.append(email_data["id"])


def _email(id_="m1", sender="rt@h2oins.com", subject="Submission - X"):
    return {"id": id_, "sender_email": sender, "subject": subject}


class TestPollOnceTransparente:
    def test_procesa_sin_tocar_el_buzon(self, tmp_path):
        from modules.quote_queue.store import QuoteQueueStore
        store = QuoteQueueStore(tmp_path / "q.db")
        gmail = _MailboxGuardGmail([_email()])
        orch = _SpyOrchestrator()
        n = poll_once(gmail, orch, "Submission", store,
                      rt_senders={"rt@h2oins.com"}, new_venture_senders=set())
        assert n == 1
        assert orch.processed == ["m1"]

    def test_no_reprocesa_correo_ya_visto(self, tmp_path):
        from modules.quote_queue.store import QuoteQueueStore
        store = QuoteQueueStore(tmp_path / "q.db")
        gmail = _MailboxGuardGmail([_email()])
        orch = _SpyOrchestrator()
        poll_once(gmail, orch, "Submission", store,
                  rt_senders={"rt@h2oins.com"}, new_venture_senders=set())
        n2 = poll_once(gmail, orch, "Submission", store,
                       rt_senders={"rt@h2oins.com"}, new_venture_senders=set())
        assert n2 == 0
        assert orch.processed == ["m1"]  # una sola vez

    def test_correo_no_procesable_no_se_reclama(self, tmp_path):
        """Un correo que no pasa el guard de remitentes NO se reclama:
        si mañana entra al allowlist, se puede procesar."""
        from modules.quote_queue.store import QuoteQueueStore
        store = QuoteQueueStore(tmp_path / "q.db")
        gmail = _MailboxGuardGmail([_email(sender="otro@x.com")])
        orch = _SpyOrchestrator()
        n = poll_once(gmail, orch, "Submission", store,
                      rt_senders={"rt@h2oins.com"}, new_venture_senders=set())
        assert n == 0
        assert store.try_claim_email("m1") is True  # sigue libre

    def test_crash_de_procesamiento_no_reprocesa(self, tmp_path):
        """Mismo comportamiento que la etiqueta vieja: reclamado aunque falle."""
        from modules.quote_queue.store import QuoteQueueStore
        store = QuoteQueueStore(tmp_path / "q.db")

        class Boom:
            def process_email(self, email_data):
                raise RuntimeError("boom")

        gmail = _MailboxGuardGmail([_email()])
        poll_once(gmail, Boom(), "Submission", store,
                  rt_senders={"rt@h2oins.com"}, new_venture_senders=set())
        assert store.try_claim_email("m1") is False
```

- [ ] **Step 2: Verificar que fallan**

Run: `<PY> -m pytest tests/quote_queue/test_runner.py -v -k Transparente`
Expected: FAIL (`poll_once` no acepta `store` posicional / TypeError).

- [ ] **Step 3: Implementación**

Reescribir `poll_once` en `modules/quote_queue/runner.py`:

```python
def poll_once(gmail, orchestrator, subject_filter: str, store,
              after_epoch=None, rt_senders=None, new_venture_senders=None) -> int:
    """Un ciclo del monitor: procesa cada submission ORIGINAL de ventas.
    Devuelve cuántas PROCESÓ (no cuántas fetcheó).

    TRANSPARENCIA TOTAL (Usuario 2026-07-29): el bot NO etiqueta, NO marca
    leído, NO modifica el correo de ventas de ninguna forma. La dedup vive
    en la cola SQLite (`store.try_claim_email` por Gmail message-id), NO en
    el buzón. Se reclama ANTES de procesar (mismas semánticas que la
    etiqueta vieja en finally: un crash a mitad de proceso no reprocesa).

    Guard de remitentes: idéntico a antes; lo que no pasa NO se procesa NI
    se reclama (si mañana entra al allowlist, sigue procesable).

    after_epoch: corte por fecha — solo correos recibidos después de ese epoch.
    """
    guard_active = not (rt_senders is None and new_venture_senders is None)
    rt = rt_senders or set()
    nv = new_venture_senders or set()
    from_allowlist = sorted(rt | nv) if guard_active else None

    emails = gmail.fetch_unread(subject_filter, after_epoch=after_epoch,
                                from_allowlist=from_allowlist)
    processed = 0
    for email_data in emails:
        if guard_active and not is_processable_submission(
                email_data.get("sender_email", ""),
                email_data.get("subject", ""), rt, nv):
            continue  # no es submission original de ventas
        if not store.try_claim_email(email_data["id"]):
            continue  # ya visto en un ciclo/arranque anterior
        processed += 1
        try:
            orchestrator.process_email(email_data)
        except Exception as e:  # un correo malo no frena el monitor
            print(f"  [monitor] error procesando "
                  f"{email_data.get('subject', '')[:50]}: {e}")
    return processed
```

En `run_forever`: borrar `seen_label = config.get("email.label_seen", ...)` y el comentario asociado; en el loop llamar `poll_once(gmail, orchestrator, subject_filter, store, after_epoch=cutoff, rt_senders=..., new_venture_senders=...)`. (`store` ya existe: `store = orchestrator.quote_store`.) Dejar `label = config.get("email.label_processed", ...)` para la Task 3, que lo elimina junto con el worker.

- [ ] **Step 4: Correr y arreglar los tests viejos del archivo**

Run: `<PY> -m pytest tests/quote_queue/test_runner.py -v`
Los tests pre-existentes de `poll_once` que pasan `seen_label=` o esperan `add_label` van a fallar: actualizarlos para pasar un `QuoteQueueStore(tmp_path / "q.db")` y eliminar toda aserción de etiquetado. NO borrar cobertura de guard de remitentes ni de conteo — solo el mecanismo de dedup cambió.
Expected: PASS todos.

- [ ] **Step 5: Commit**

```bash
git add modules/quote_queue/runner.py tests/quote_queue/test_runner.py
git commit -m "feat(runner): servicio transparente - dedup por message-id en SQLite, cero etiquetas"
```

---

### Task 3: Correo de análisis NUEVO solo a Diana (sin hilo, sin CC, sin etiqueta)

**Files:**
- Modify: `modules/quote_queue/worker.py` (`__init__`, `maybe_send_submission_email`)
- Modify: `workflow_orchestrator.py` (`__init__` ~líneas 100-104, `_process_submission` ~251-266, `_send_analysis_now` ~501-521, `_send_not_found_email` ~523-550)
- Modify: `modules/analysis_email_builder.py` (subject, línea 481)
- Modify: `modules/quote_queue/runner.py` (construcción del worker en `run_forever`, quitar `label`)
- Modify: `config/settings.yaml` (líneas de `analysis_cc`, `label_processed`, `label_seen`)
- Test: `tests/quote_queue/test_worker_email.py`

**Interfaces:**
- Consumes: contexto de submission (JSON en store).
- Produces: contexto reducido a `{"recipient", "subject", "body_html", "attachment_paths"}`. `QuoteWorker(mga, store, create_quote, gmail, drive_manager=None)` — el parámetro `label_processed` DESAPARECE. Subject del análisis: `f"[ANALISIS] {business_name} | {original_subject}"`.

- [ ] **Step 1: Escribir los tests que fallan**

En `tests/quote_queue/test_worker_email.py` agregar (con los helpers/mocks del archivo, adaptando):

```python
class _RecorderGmail:
    def __init__(self):
        self.sent = []

    def send_threaded(self, **kwargs):
        self.sent.append(kwargs)
        return True

    def add_label(self, *a, **k):
        raise AssertionError("El worker NO debe etiquetar (transparencia)")


def test_analysis_email_es_correo_nuevo_sin_hilo_ni_cc(tmp_path):
    """El análisis sale como correo NUEVO al destinatario del contexto
    (Diana en estabilización): sin thread_id, sin in_reply_to, sin CC."""
    from modules.quote_queue.store import QuoteQueueStore
    from modules.quote_queue.worker import QuoteWorker
    import json

    store = QuoteQueueStore(tmp_path / "q.db")
    jid = store.enqueue("sub-1", "PROGRESSIVE", "{}", None, "123")
    store.mark_terminal(jid, "quoted", premium="$1,000")
    store.save_submission_context("sub-1", json.dumps({
        "recipient": "dianarubio@h2oins.com",
        "subject": "[ANALISIS] ACME LLC | Submission - ACME",
        "body_html": "<html><!--RPA_QUOTES_SECTION--></html>",
        "attachment_paths": [],
    }))
    gmail = _RecorderGmail()
    worker = QuoteWorker("PROGRESSIVE", store, lambda p, e: None, gmail)
    assert worker.maybe_send_submission_email("sub-1") is True
    (sent,) = gmail.sent
    assert sent["to"] == "dianarubio@h2oins.com"
    assert sent.get("cc") is None
    assert sent.get("thread_id") is None
    assert sent.get("in_reply_to") is None
```

- [ ] **Step 2: Verificar que falla**

Run: `<PY> -m pytest tests/quote_queue/test_worker_email.py -v -k correo_nuevo`
Expected: FAIL (hoy el worker pasa `thread_id`/`cc` desde el contexto, o el constructor con 4 args posicionales choca con `label_processed`).

- [ ] **Step 3: Implementación**

(a) `modules/quote_queue/worker.py`:
- `__init__`: eliminar el parámetro `label_processed` y el atributo `self.label_processed`.
- `maybe_send_submission_email`: el `send_threaded` queda SIN `cc`, SIN `thread_id`, SIN `in_reply_to`:

```python
ok = self.gmail.send_threaded(
    to=ctx["recipient"],
    subject=ctx["subject"],
    body=body,
    attachments=attachments,
    is_html=True,
)
```

y ELIMINAR completo el bloque `if ok and ctx.get("message_id"): ... add_label ...`. Actualizar el docstring del módulo (ya no "responde en hilo": "manda el correo de análisis NUEVO al destinatario configurado").

(b) `workflow_orchestrator.py`:
- `__init__`: eliminar `self.analysis_cc` y `self.label_processed` (y sus lecturas de config).
- `_process_submission`: el `save_submission_context` guarda SOLO:

```python
self.quote_store.save_submission_context(submission_id, json.dumps({
    "recipient": analysis_to,
    "subject": analysis["subject"],
    "body_html": analysis["body"],
    "attachment_paths": attachment_paths,
}))
```

(eliminar `cc`, `thread_id`, `in_reply_to`, `message_id` del dict y la variable `analysis_cc`).
- `_send_analysis_now`: correo nuevo, sin cc/hilo/etiqueta:

```python
def _send_analysis_now(self, email_data: dict, subject: str, body: str,
                       attachments: list) -> None:
    """Envía el análisis como correo NUEVO a analysis_to (Diana durante
    estabilización). Transparente: no toca el correo original."""
    ok = self.gmail.send_threaded(
        to=self.analysis_to,
        subject=subject,
        body=body,
        attachments=attachments,
        is_html=True,
    )
    print(f"  Analysis sent to {self.analysis_to} (ok={ok})")
```

- `_send_not_found_email`: mismo tratamiento (quitar `cc=`, `thread_id=`, `in_reply_to=` y el bloque `add_label`).

(c) `modules/analysis_email_builder.py` línea 481:

```python
business = profile.applicant.business_name or "Cliente"
subject = f"[ANALISIS] {business} | {original_subject}"
```

(El prefijo `[ANALISIS]` se conserva: es el guard anti-loop de `process_email`.)

(d) `modules/quote_queue/runner.py` `run_forever`: quitar `label = config.get("email.label_processed", ...)` y construir `QuoteWorker(mga, store, _create_quote_for(mga), gmail)` sin `label_processed=`.

(e) `config/settings.yaml`: eliminar las claves `email.analysis_cc`, `email.label_processed` y `email.label_seen` (buscarlas con grep; `analysis_to` SE QUEDA). Actualizar el comentario de `analysis_to`:

```yaml
  analysis_to: "${EMAIL_ANALYSIS_TO}"   # estabilización: dianarubio@h2oins.com (.env)
```

- [ ] **Step 4: Correr y arreglar tests afectados**

Run: `<PY> -m pytest tests/quote_queue/ -v`
Los tests existentes de worker/runner que armaban contexto con `thread_id`/`cc`/`message_id` o esperaban `add_label`: actualizarlos al contexto reducido. Si algún test de `analysis_email_builder` (`tests/test_analysis_email_rpa_section.py` u otro) asertaba el subject viejo, actualizar al formato nuevo.
Expected: PASS todos.

- [ ] **Step 5: Paso manual documentado (NO commitear)**

En `.env` del host: `EMAIL_ANALYSIS_TO=dianarubio@h2oins.com` y borrar `EMAIL_ANALYSIS_CC`. Dejar nota en el mensaje de commit de que el valor productivo va por `.env`.

- [ ] **Step 6: Commit**

```bash
git add modules/quote_queue/worker.py workflow_orchestrator.py modules/analysis_email_builder.py modules/quote_queue/runner.py config/settings.yaml tests/
git commit -m "feat(email): analisis como correo NUEVO a EMAIL_ANALYSIS_TO (Diana) - sin hilo, sin CC, sin etiquetas"
```

---

### Task 4: Sección "Por qué del análisis" (rule engine) en el correo

**Files:**
- Modify: `modules/analysis_email_builder.py` (`_eligible_row`, `_ineligible_row`, bloque web-MGAs en `build_analysis_email`, función nueva `_web_rules_row`)
- Modify: `config/templates/analysis_email.html` (placeholder nuevo `{web_rules_rows}`)
- Test: `tests/test_analysis_email_why.py` (nuevo)

**Interfaces:**
- Consumes: `MGAEvaluation(mga_name, eligible, passed_rules: List[str], failed_rules: List[FailedRule], warnings, informational)` y `FailedRule(rule, reason, current_value=None, required_value=None)` de `modules/rule_engine.py` (ya existen).
- Produces: el HTML del análisis muestra, por MGA: reglas OK (elegibles), razón + `actual` vs `requerido` (no elegibles), y un bloque nuevo "MGAs Web — Evaluación de reglas" para Progressive/GEICO.

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_analysis_email_why.py`:

```python
"""La sección 'por qué' del rule engine en el correo de análisis."""
from modules.analysis_email_builder import build_analysis_email
from modules.rule_engine import MGAEvaluation, FailedRule
from modules.quote_profile import QuoteProfile


def _profile():
    p = QuoteProfile()
    p.applicant.business_name = "ACME LLC"
    p.applicant.usdot = "123456"
    return p


def _build(evaluations, mga_list):
    return build_analysis_email(
        profile=_profile(), commodity="SAND", tipo_negocio="DUMP",
        evaluations=evaluations, mga_list=mga_list,
        original_subject="Submission - ACME",
    )


def test_ineligible_muestra_actual_vs_requerido():
    ev = MGAEvaluation(
        mga_name="COVERWHALE", eligible=False,
        failed_rules=[FailedRule("MIN_UNITS", "Requiere minimo de unidades",
                                 current_value=1, required_value=2)],
    )
    out = _build([ev], [{"mga": "COVERWHALE"}])
    assert "actual: 1" in out["body"]
    assert "requerido: 2" in out["body"]


def test_eligible_muestra_reglas_ok():
    ev = MGAEvaluation(mga_name="COVERWHALE", eligible=True,
                       passed_rules=["MIN_UNITS", "MIN_CDL_YEARS"])
    out = _build([ev], [{"mga": "COVERWHALE"}])
    assert "MIN_UNITS" in out["body"]
    assert "MIN_CDL_YEARS" in out["body"]


def test_mga_web_ineligible_aparece_en_bloque_web_con_razon():
    """Progressive no elegible por reglas: Diana debe ver POR QUE no se
    intento la cotizacion automatica (hoy se filtra y desaparece)."""
    ev = MGAEvaluation(
        mga_name="PROGRESSIVE", eligible=False,
        failed_rules=[FailedRule("MIN_UNITS", "Requiere minimo de unidades",
                                 current_value=1, required_value=2)],
    )
    out = _build([ev], [{"mga": "PROGRESSIVE"}])
    body = out["body"]
    assert "PROGRESSIVE" in body
    assert "Requiere minimo de unidades" in body
    # y NO en la lista roja general (siguen excluidos de ahi):
    assert "no se intent" in body.lower()  # "no se intentó cotización automática"


def test_mga_web_eligible_referencia_seccion_rpa():
    ev = MGAEvaluation(mga_name="PROGRESSIVE", eligible=True,
                       passed_rules=["MIN_UNITS"])
    out = _build([ev], [{"mga": "PROGRESSIVE"}])
    assert "Elegible por reglas" in out["body"]
```

- [ ] **Step 2: Verificar que fallan**

Run: `<PY> -m pytest tests/test_analysis_email_why.py -v`
Expected: FAIL los 4 (hoy no se renderizan valores, reglas OK, ni el bloque web).

- [ ] **Step 3: Implementación**

En `modules/analysis_email_builder.py`:

(a) `_ineligible_row`: en el loop de `failed_rules`, después de `fr.reason` agregar valores cuando existan:

```python
for fr in ev.failed_rules:
    detail = fr.reason
    if fr.current_value is not None or fr.required_value is not None:
        detail += (f' <span style="color:#8c95a6;">(actual: {fr.current_value}'
                   f' &mdash; requerido: {fr.required_value})</span>')
    lines.append(
        f'<p style="margin:4px 0 0 0;font-family:Arial,Helvetica,sans-serif;font-size:12px;color:#5a6577;">'
        f'&#8226; {detail}</p>'
    )
```

(b) `_eligible_row`: después del loop de warnings, agregar:

```python
if ev.passed_rules:
    shown = ", ".join(ev.passed_rules[:8])
    if len(ev.passed_rules) > 8:
        shown += f" (+{len(ev.passed_rules) - 8})"
    lines.append(
        f'<p style="margin:4px 0 0 0;font-family:Arial,Helvetica,sans-serif;font-size:11px;color:#0d7a3f;">'
        f'Reglas OK: {shown}</p>'
    )
```

(c) Función nueva `_web_rules_row(ev)` (junto a `_ineligible_row`):

```python
def _web_rules_row(ev: MGAEvaluation) -> str:
    """Fila del bloque 'MGAs Web — evaluación de reglas' (Progressive/GEICO).

    El veredicto FINAL de estos MGAs lo da el RPA (sección 'Cotizaciones
    automáticas'); este bloque explica el filtro PREVIO del rule engine:
    por qué se intentó (o no) la cotización automática.
    """
    if ev.eligible:
        color, verdict = "#0d7a3f", ("Elegible por reglas &mdash; la cotizaci&oacute;n "
                                     "autom&aacute;tica decide el resultado final "
                                     "(ver secci&oacute;n RPA)")
    else:
        color, verdict = "#c4291c", ("NO se intent&oacute; cotizaci&oacute;n "
                                     "autom&aacute;tica &mdash; reglas:")
    lines = [
        '<tr style="background-color:#f4f7fb;">',
        '<td style="padding:12px 16px;border-bottom:1px solid #bcd2e8;">',
        f'<p style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:14px;font-weight:bold;color:{color};">{ev.mga_name}</p>',
        f'<p style="margin:4px 0 0 0;font-family:Arial,Helvetica,sans-serif;font-size:12px;color:#5a6577;">{verdict}</p>',
    ]
    for fr in ev.failed_rules:
        detail = fr.reason
        if fr.current_value is not None or fr.required_value is not None:
            detail += (f' <span style="color:#8c95a6;">(actual: {fr.current_value}'
                       f' &mdash; requerido: {fr.required_value})</span>')
        lines.append(
            f'<p style="margin:4px 0 0 0;font-family:Arial,Helvetica,sans-serif;font-size:12px;color:#5a6577;">'
            f'&#8226; {detail}</p>'
        )
    if ev.eligible and ev.passed_rules:
        shown = ", ".join(ev.passed_rules[:8])
        if len(ev.passed_rules) > 8:
            shown += f" (+{len(ev.passed_rules) - 8})"
        lines.append(
            f'<p style="margin:4px 0 0 0;font-family:Arial,Helvetica,sans-serif;font-size:11px;color:#5a6577;">'
            f'Reglas OK: {shown}</p>'
        )
    lines.append('</td></tr>')
    return "\n".join(lines)
```

(d) En `build_analysis_email`, en la línea que filtra los web MGAs (`relevant = [ev for ev in relevant if not _is_web_automation_mga(ev.mga_name)]`), capturar ANTES:

```python
web_evals = [ev for ev in relevant if _is_web_automation_mga(ev.mga_name)]
```

y antes del `template.format`, renderizar:

```python
web_rules_rows = "".join(_web_rules_row(ev) for ev in web_evals)
if not web_rules_rows:
    web_rules_rows = _no_data_row("Sin MGAs web para esta cotizacion",
                                  bg="#f4f7fb", border="#bcd2e8")
```

y agregar `web_rules_rows=web_rules_rows` al `template.format(...)`.

(e) `config/templates/analysis_email.html`: insertar el bloque nuevo ANTES del comentario `<!-- ====== ELIGIBLE MGAs ====== -->` (línea ~149), siguiendo el patrón visual de las otras secciones:

```html
<!-- ====== WEB MGAs (rule engine) ====== -->
<tr>
<td style="padding:8px 32px 4px 32px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#1a5276;border-radius:6px 6px 0 0;">
  <tr>
    <td style="padding:14px 20px;">
      <p style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:12px;font-weight:bold;letter-spacing:1.5px;text-transform:uppercase;color:#ffffff;">&#9679; MGAs Web &mdash; Evaluacion de Reglas</p>
    </td>
  </tr>
  </table>
</td>
</tr>
<tr>
<td style="padding:0 32px 20px 32px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border:1px solid #bcd2e8;border-top:none;border-radius:0 0 6px 6px;overflow:hidden;">
  {web_rules_rows}
  </table>
</td>
</tr>
```

OJO: el template usa `{}` de `str.format` — las llaves literales de CSS ya están escapadas en el `<style>` MSO (`{{ }}`); no introducir llaves sin escapar.

- [ ] **Step 4: Verificar que pasan + regresiones del builder**

Run: `<PY> -m pytest tests/test_analysis_email_why.py tests/test_analysis_email_rpa_section.py -v`
Expected: PASS todos (si el test RPA viejo asertaba el HTML completo, ajustar por el bloque nuevo).

- [ ] **Step 5: Commit**

```bash
git add modules/analysis_email_builder.py config/templates/analysis_email.html tests/test_analysis_email_why.py tests/test_analysis_email_rpa_section.py
git commit -m "feat(email): seccion 'por que' del rule engine - reglas OK, actual vs requerido y bloque MGAs web"
```

---

### Task 5: `modules/decision_ledger.py` + hook en `choice_resolver` + captura en worker

**Files:**
- Create: `modules/decision_ledger.py`
- Modify: `modules/progressive/choice_resolver.py` (emitir cada `Resolution`)
- Modify: `modules/progressive/client.py:69` (`create_quote`: `start_run("PROGRESSIVE")`)
- Modify: `modules/geico/client.py:134` (`create_quote`: `start_run("GEICO")`)
- Modify: `modules/quote_queue/worker.py` (`run_once`: capturar `entries()` → `mark_terminal(decisions_json=...)`)
- Test: `tests/test_decision_ledger.py` (nuevo), `tests/quote_queue/test_worker_email.py` (captura)

**Interfaces:**
- Consumes: `mark_terminal(..., decisions_json=None)` (Task 1).
- Produces:
  - `decision_ledger.start_run(mga: str) -> None` — resetea el ledger del thread actual.
  - `decision_ledger.record(field: str, chosen, *, page=None, options=None, source="HARDCODED", rule_id=None, note="") -> None` — best-effort, NUNCA lanza; no-op si no hubo `start_run` en este thread.
  - `decision_ledger.entries() -> List[dict]` — dicts `{mga, page, field, chosen, options, source, rule_id, note}`.
  - Estado **thread-local**: los workers Progressive y GEICO corren en threads distintos del mismo proceso y NO deben contaminarse.

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_decision_ledger.py`:

```python
"""Decision Ledger: registro thread-local de decisiones por corrida."""
import threading

from modules import decision_ledger
from modules.progressive.choice_resolver import resolve_choice


def test_record_sin_start_run_es_noop():
    decision_ledger.record("Roadside", "Yes")
    assert decision_ledger.entries() == []


def test_start_run_resetea_y_record_acumula():
    decision_ledger.start_run("PROGRESSIVE")
    decision_ledger.record("Roadside Assistance", "Selected w/ $250 Deductible",
                           page="Coverages/RATES", source="RULE", rule_id="R-001")
    entries = decision_ledger.entries()
    assert len(entries) == 1
    e = entries[0]
    assert e["mga"] == "PROGRESSIVE"
    assert e["field"] == "Roadside Assistance"
    assert e["chosen"] == "Selected w/ $250 Deductible"
    assert e["rule_id"] == "R-001"
    decision_ledger.start_run("PROGRESSIVE")
    assert decision_ledger.entries() == []  # reset


def test_record_nunca_lanza():
    decision_ledger.start_run("PROGRESSIVE")

    class Boom:
        def __str__(self):
            raise RuntimeError("boom")

    decision_ledger.record("X", Boom())  # no debe explotar
    # la entrada mala se descarta o se stringifica, pero nunca rompe
    assert isinstance(decision_ledger.entries(), list)


def test_threads_aislados():
    """Un worker GEICO y uno Progressive en paralelo no se mezclan."""
    results = {}

    def run(mga):
        decision_ledger.start_run(mga)
        decision_ledger.record(f"campo-{mga}", "valor")
        results[mga] = decision_ledger.entries()

    t1 = threading.Thread(target=run, args=("PROGRESSIVE",))
    t2 = threading.Thread(target=run, args=("GEICO",))
    t1.start(); t2.start(); t1.join(); t2.join()
    assert [e["mga"] for e in results["PROGRESSIVE"]] == ["PROGRESSIVE"]
    assert [e["mga"] for e in results["GEICO"]] == ["GEICO"]


def test_resolve_choice_registra_matched_y_defaulted():
    decision_ledger.start_run("PROGRESSIVE")
    resolve_choice("Body Type", "Dump Truck", ["Dump Truck", "Flatbed"])
    resolve_choice("Rental", None, ["Yes", "No"], default="No")
    entries = decision_ledger.entries()
    assert len(entries) == 2
    assert entries[0]["source"] == "MATCHED"
    assert entries[1]["source"] == "DEFAULTED"
    assert entries[1]["chosen"] == "No"
```

- [ ] **Step 2: Verificar que fallan**

Run: `<PY> -m pytest tests/test_decision_ledger.py -v`
Expected: FAIL con `ModuleNotFoundError: modules.decision_ledger`.

- [ ] **Step 3: Implementación**

Crear `modules/decision_ledger.py`:

```python
"""Decision Ledger — el bot como notario de sus propias decisiones.

Registro en memoria (thread-local) de cada decisión que el bot toma durante
una corrida de cotización: qué campo, qué eligió, entre qué opciones, y por
qué (regla de negocio con rule_id del Excel config/mga_decision_rules.xlsx,
default técnico, matching, AI). El worker lo serializa al terminar el job y
el correo de análisis lo muestra a negocios ("Decisiones tomadas").

Thread-local porque el runner corre UN worker-thread por MGA en el mismo
proceso: cada thread tiene su ledger y no se contaminan entre MGAs.

Best-effort SIEMPRE: registrar jamás puede romper una cotización.
"""

from __future__ import annotations

import threading
from typing import List, Optional

_state = threading.local()


def start_run(mga: str) -> None:
    """Arranca (o resetea) el ledger de la corrida del thread actual."""
    _state.mga = mga
    _state.entries = []


def record(field: str, chosen, *, page: Optional[str] = None,
           options=None, source: str = "HARDCODED",
           rule_id: Optional[str] = None, note: str = "") -> None:
    """Registra una decisión. No-op si no hubo start_run en este thread.

    NUNCA lanza: una falla de registro jamás rompe una cotización.
    """
    try:
        entries = getattr(_state, "entries", None)
        if entries is None:
            return
        entries.append({
            "mga": getattr(_state, "mga", "?"),
            "page": page,
            "field": str(field),
            "chosen": str(chosen),
            "options": [str(o) for o in options] if options else None,
            "source": str(source),
            "rule_id": rule_id,
            "note": str(note) if note else "",
        })
    except Exception:
        pass  # best-effort: el ledger nunca tumba el flujo


def entries() -> List[dict]:
    """Las decisiones registradas en el thread actual (lista vacía si no hay)."""
    return list(getattr(_state, "entries", []) or [])
```

Hook en `modules/progressive/choice_resolver.py` — import arriba
(`from modules import decision_ledger` — ambos son lógica pura, sin ciclo) y
en `resolve_choice` emitir cada `Resolution` ANTES de retornarla. Para no
duplicar el `record` en los 5 puntos de retorno, envolver: renombrar la
función actual a `_resolve_choice_inner` (mismo cuerpo, sin cambios) y crear:

```python
def resolve_choice(field, source_value, options, *, mapping=None, default=None,
                   generic_aliases=frozenset(), screenshot_path=None,
                   debug_context=None):
    res = _resolve_choice_inner(
        field, source_value, options, mapping=mapping, default=default,
        generic_aliases=generic_aliases, screenshot_path=screenshot_path,
        debug_context=debug_context,
    )
    # Notario: toda decisión de opción queda en el ledger (best-effort).
    decision_ledger.record(res.field, res.value, options=list(options),
                           source=res.kind, note=res.note)
    return res
```

(El docstring público se mueve a la función wrapper. `UnmappableValueError`
sigue propagando igual — un HALT no es una decisión tomada.)

`modules/progressive/client.py` — al inicio del cuerpo de `create_quote` (línea ~69):

```python
from modules import decision_ledger
decision_ledger.start_run("PROGRESSIVE")
```

`modules/geico/client.py` — al inicio del cuerpo de `create_quote` (línea ~134): igual con `"GEICO"`.

`modules/quote_queue/worker.py` `run_once` — capturar tras `create_quote` (en el
path de éxito Y en el `except`, ANTES de `mark_terminal`):

```python
from modules import decision_ledger   # import al tope del archivo
...
decisions = decision_ledger.entries()
decisions_json = json.dumps(decisions) if decisions else None
```

y pasar `decisions_json=decisions_json` a AMBAS llamadas `mark_terminal`
(la del except usa `decision_ledger.entries()` igual — lo que alcanzó a
registrarse antes del crash sirve para diagnóstico).

- [ ] **Step 4: Verificar**

Run: `<PY> -m pytest tests/test_decision_ledger.py tests/quote_queue/ -v`
Expected: PASS. Después la suite de progressive (el hook toca `resolve_choice`, usado por field mappers):
Run: `<PY> -m pytest tests/ -v -k "progressive or resolver"`
Expected: PASS (el hook es no-op sin `start_run`; ningún test existente debería romperse).

- [ ] **Step 5: Commit**

```bash
git add modules/decision_ledger.py modules/progressive/choice_resolver.py modules/progressive/client.py modules/geico/client.py modules/quote_queue/worker.py tests/test_decision_ledger.py
git commit -m "feat(ledger): decision_ledger thread-local + hook en choice_resolver + captura en worker"
```

---

### Task 6: Auditoría de decisiones → seed `config/mga_decision_rules.xlsx` + rule_ids en sitios hardcodeados

**Files:**
- Create: `scripts/generate_decision_rules_seed.py`
- Create: `config/mga_decision_rules.xlsx` (generado por el script, SE COMMITEA)
- Modify: `modules/progressive/pages/coverages_rates_page.py:179-185` (record R-001)
- Modify: `modules/geico/pages/business_owner_page.py:556-570` (record R-004)
- Modify: los sitios hardcodeados adicionales que la auditoría identifique (mismo patrón)
- Test: `tests/test_decision_rules_seed.py` (nuevo)

**Interfaces:**
- Consumes: `decision_ledger.record(field, chosen, page=, source=, rule_id=)` (Task 5).
- Produces: Excel con hojas `reglas` (columnas EXACTAS: `ID | MGA | Página | Campo | Contexto | Decisión | Fuente | Quote de referencia | Estado | Notas`) e `instrucciones`. IDs estables `R-NNN` citados en código.

- [ ] **Step 1: AUDITORÍA — enumerar los puntos de decisión (sin código aún)**

Barrer con Grep los sitios donde el bot ELIGE un valor que no viene copiado directo del BlueQuote, y anotar cada uno (archivo:línea, página del wizard, campo, valor, origen). Patrones de búsqueda, en estos árboles:

- `modules/progressive/pages/` y `modules/geico/pages/`: `safe_radio\(|safe_checkbox\(|safe_select_combo\(|_set_combobox` — de cada hit, los que pasan un LITERAL (no un valor del profile) son decisiones.
- `modules/progressive/field_mapper.py`, `modules/progressive/mappings.py`, `modules/geico/` equivalentes: `default|DEFAULT|fallback|hardcode|Diana|feedback` (case-insensitive).
- `modules/progressive/choice_resolver.py` callers: `resolve_choice\(` con `default=` — cada default es una decisión.
- Comentarios con feedback: `Diana|feedback` en `modules/` (esos van `Fuente=Negocio`).

Filas SEMILLA conocidas (arrancan la numeración — la auditoría AGREGA más):

| ID | MGA | Página | Campo | Contexto | Decisión | Fuente | Quote ref | Estado | Notas |
|---|---|---|---|---|---|---|---|---|---|
| R-001 | Progressive | Coverages/RATES | Roadside Assistance | Siempre | Selected w/ $250 Deductible | Negocio (Diana) | ELITE 2857089 | VIGENTE | feedback 2026-06-25, commit f257f96 |
| R-002 | Progressive | Coverages/RATES | Filings state/federal | USDOT < 60 días | Yes | Negocio (Diana) | USDOT 9648609 | VIGENTE | commit c53f4eb |
| R-003 | Progressive | More Business Info | Email del cliente | Siempre | owner_email del BlueQuote | Negocio (Diana) | ELITE 2857089 | VIGENTE | commit f257f96 |
| R-004 | GEICO | Step 2 Business Owner | Interstitial 'Verify USDOT Number' | Cuando aparece | Skip | Negocio (validado live) | FGF | VIGENTE | commit 50c39a8 |
| R-005 | Ambos | Field mapper | Marital status | Sin dato en BlueQuote | Single | Negocio | — | VIGENTE | regla histórica field mapper |
| R-006 | Progressive | Coverages/RATES | Radio de operación | Bracket discreto | '500 miles' exacto (sin overshoot) | Negocio (Diana) | ALMA FORCE 4452732 | VIGENTE | commit 74932df |
| R-007 | Progressive | Other Business Insurance | Q1 casilla GL | Cuando hay GL en BlueQuote | Marcar | Negocio (Diana) | ALMA FORCE 4452732 | VIGENTE | commit 74932df |

Todo default técnico SIN feedback de negocio detrás → `Fuente=Default técnico`, `Estado=EN-DUDA`. Decisiones que resuelve la AI (commodity → business type, MTC commodity) → `Fuente=AI`, `Estado=EN-DUDA`. La lista EN-DUDA es la agenda de la sesión con Diana — NO decidir por negocios acá.

- [ ] **Step 2: Test del seed**

Crear `tests/test_decision_rules_seed.py`:

```python
"""El registro de reglas de decisión existe y tiene el esquema esperado."""
from pathlib import Path

import openpyxl

XLSX = Path(__file__).parent.parent / "config" / "mga_decision_rules.xlsx"
HEADERS = ["ID", "MGA", "Página", "Campo", "Contexto", "Decisión",
           "Fuente", "Quote de referencia", "Estado", "Notas"]


def test_seed_existe_con_esquema():
    wb = openpyxl.load_workbook(XLSX, read_only=True)
    assert "reglas" in wb.sheetnames
    assert "instrucciones" in wb.sheetnames
    ws = wb["reglas"]
    headers = [c.value for c in next(ws.iter_rows(max_row=1))]
    assert headers == HEADERS


def test_ids_unicos_y_estados_validos():
    wb = openpyxl.load_workbook(XLSX, read_only=True)
    ws = wb["reglas"]
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    assert len(rows) >= 7  # al menos las filas semilla conocidas
    ids = [r[0] for r in rows]
    assert len(ids) == len(set(ids)), "IDs duplicados"
    estados = {r[8] for r in rows}
    assert estados <= {"VIGENTE", "EN-DUDA", "PENDIENTE-código"}
```

Run: `<PY> -m pytest tests/test_decision_rules_seed.py -v` → Expected: FAIL (no existe el xlsx).

- [ ] **Step 3: Script generador + generar el Excel**

Crear `scripts/generate_decision_rules_seed.py`:

```python
"""Genera el SEED de config/mga_decision_rules.xlsx desde la auditoría.

Se corre UNA vez (y ante re-seeds deliberados). Después el Excel se edita a
mano: es el registro humano de reglas de decisión (el bot NO lo lee en
runtime). Correr de nuevo PISA el archivo — no correr sobre un Excel con
ediciones manuales sin respaldarlo antes.
"""
from pathlib import Path

import openpyxl
from openpyxl.styles import Font

OUT = Path(__file__).parent.parent / "config" / "mga_decision_rules.xlsx"

HEADERS = ["ID", "MGA", "Página", "Campo", "Contexto", "Decisión",
           "Fuente", "Quote de referencia", "Estado", "Notas"]

# (ID, MGA, Página, Campo, Contexto, Decisión, Fuente, QuoteRef, Estado, Notas)
ROWS = [
    ("R-001", "Progressive", "Coverages/RATES", "Roadside Assistance",
     "Siempre", "Selected w/ $250 Deductible", "Negocio (Diana)",
     "ELITE 2857089", "VIGENTE", "feedback 2026-06-25, commit f257f96"),
    ("R-002", "Progressive", "Coverages/RATES", "Filings state/federal",
     "USDOT < 60 días", "Yes", "Negocio (Diana)",
     "USDOT 9648609", "VIGENTE", "commit c53f4eb"),
    ("R-003", "Progressive", "More Business Info", "Email del cliente",
     "Siempre", "owner_email del BlueQuote", "Negocio (Diana)",
     "ELITE 2857089", "VIGENTE", "commit f257f96"),
    ("R-004", "GEICO", "Step 2 Business Owner",
     "Interstitial 'Verify USDOT Number'", "Cuando aparece", "Skip",
     "Negocio (validado live)", "FGF", "VIGENTE", "commit 50c39a8"),
    ("R-005", "Ambos", "Field mapper", "Marital status",
     "Sin dato en BlueQuote", "Single", "Negocio", "", "VIGENTE",
     "regla histórica field mapper"),
    ("R-006", "Progressive", "Coverages/RATES", "Radio de operación",
     "Bracket discreto", "'500 miles' exacto (sin overshoot)",
     "Negocio (Diana)", "ALMA FORCE 4452732", "VIGENTE", "commit 74932df"),
    ("R-007", "Progressive", "Other Business Insurance", "Q1 casilla GL",
     "Cuando hay GL en BlueQuote", "Marcar", "Negocio (Diana)",
     "ALMA FORCE 4452732", "VIGENTE", "commit 74932df"),
    # >>> la auditoría agrega el resto acá (defaults técnicos = EN-DUDA) <<<
]

INSTRUCCIONES = [
    "REGISTRO DE REGLAS DE DECISIÓN — Progressive y GEICO",
    "",
    "Qué es: una fila por cada decisión que el bot toma al cotizar (qué opción",
    "elige en cada bifurcación del wizard). El correo de análisis cita estas",
    "reglas por ID en la tabla 'Decisiones tomadas'.",
    "",
    "Estados:",
    "  VIGENTE          — regla confirmada e implementada en el bot.",
    "  EN-DUDA          — default técnico sin validar por negocios (agenda de",
    "                     la sesión de revisión).",
    "  PENDIENTE-código — negocios ya decidió; falta el cambio en el bot.",
    "",
    "Circuito de corrección:",
    "  1. Diana responde el correo de análisis señalando una decisión.",
    "  2. Programación actualiza la fila: Decisión nueva, Fuente=Negocio,",
    "     Quote de referencia, fecha en Notas, Estado=PENDIENTE-código.",
    "  3. Se ajusta el bot citando el ID en el commit (ej. 'aplica R-012').",
    "  4. Estado=VIGENTE. La próxima cotización ya muestra la regla nueva.",
    "",
    "El bot NO lee este Excel: el código es la fuente ejecutable, este archivo",
    "es la fuente humana. Si difieren, la tabla del correo lo hace visible.",
]


def main() -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "reglas"
    ws.append(HEADERS)
    for c in ws[1]:
        c.font = Font(bold=True)
    for row in ROWS:
        ws.append(row)
    ws.freeze_panes = "A2"
    widths = [8, 12, 24, 30, 22, 30, 20, 18, 16, 40]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w

    inst = wb.create_sheet("instrucciones")
    for line in INSTRUCCIONES:
        inst.append([line])
    inst.column_dimensions["A"].width = 80

    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT)
    print(f"Seed escrito: {OUT} ({len(ROWS)} reglas)")


if __name__ == "__main__":
    main()
```

Volcar los hallazgos de la auditoría del Step 1 como filas adicionales en `ROWS` (numeración R-008 en adelante, `Estado=EN-DUDA` para defaults técnicos y decisiones AI). Correr:

`<PY> scripts/generate_decision_rules_seed.py`

Run: `<PY> -m pytest tests/test_decision_rules_seed.py -v` → Expected: PASS.

- [ ] **Step 4: Citar rule_ids en los sitios hardcodeados**

En cada sitio hardcodeado con regla en el Excel, agregar el `record` (best-effort, no cambia el comportamiento del flow). Anclas obligatorias:

(a) `modules/progressive/pages/coverages_rates_page.py` — junto al bloque Roadside (~línea 179-185, comentario "Diana 2026-06-25"):

```python
from modules import decision_ledger   # import al tope del archivo
...
decision_ledger.record("Roadside Assistance", coverages.roadside_assistance,
                       page="Coverages/RATES", source="RULE", rule_id="R-001")
```

(b) `modules/geico/pages/business_owner_page.py` — donde se clickea Skip del interstitial (~línea 567):

```python
from modules import decision_ledger   # import al tope del archivo
...
decision_ledger.record("Verify USDOT Number", "Skip",
                       page="Step 2 Business Owner", source="RULE",
                       rule_id="R-004")
```

(c) Repetir el patrón en los sitios de R-002, R-003, R-005, R-006, R-007 y los EN-DUDA que la auditoría ubicó con archivo:línea (source="RULE" si VIGENTE-Negocio; source="DEFAULT" si EN-DUDA). Si un sitio es difícil de instrumentar sin tocar lógica (p.ej. dentro de un builder de payload), instrumentarlo en el caller más cercano — el objetivo es que la corrida real produzca la entrada.

- [ ] **Step 5: Verificar sin regresiones**

Run: `<PY> -m pytest tests/ -v -k "progressive or geico" --no-header -q`
Expected: PASS (los `record` son no-op fuera de una corrida y best-effort dentro).

- [ ] **Step 6: Commit**

```bash
git add scripts/generate_decision_rules_seed.py config/mga_decision_rules.xlsx tests/test_decision_rules_seed.py modules/progressive/pages/ modules/geico/pages/ modules/progressive/field_mapper.py
git commit -m "feat(reglas): seed config/mga_decision_rules.xlsx (auditoria) + rule_ids citados en sitios hardcodeados"
```

(Ajustar el `git add` a los archivos realmente tocados en el Step 4c.)

---

### Task 7: Tabla "Decisiones tomadas" en el correo

**Files:**
- Modify: `modules/quote_queue/messages.py` (`RpaQuoteOutcome.decisions`, `_decisions_table`, `_row`)
- Modify: `modules/quote_queue/worker.py` (`maybe_send_submission_email`: poblar `decisions`)
- Test: `tests/quote_queue/test_messages.py`, `tests/quote_queue/test_worker_email.py`

**Interfaces:**
- Consumes: `QuoteJob.decisions_json` (Tasks 1+5); entradas del ledger `{mga, page, field, chosen, options, source, rule_id, note}`.
- Produces: `RpaQuoteOutcome(..., decisions: Optional[List[dict]] = None)`; la fila RPA de una MGA **quoted** incluye la tabla de decisiones (dudosas ⚠️ arriba). MGAs no-quoted NUNCA muestran tabla ("si logra cotizar, se agrega" — Usuario).

- [ ] **Step 1: Escribir los tests que fallan**

En `tests/quote_queue/test_messages.py` agregar:

```python
class TestDecisionsTable:
    def _outcome(self, decisions, reason="ok"):
        return RpaQuoteOutcome(mga="PROGRESSIVE", status="quoted",
                               reason=reason, premium="$1,000",
                               decisions=decisions)

    def test_quoted_muestra_decisiones(self):
        html = render_rpa_section([self._outcome([
            {"field": "Roadside Assistance", "chosen": "Selected w/ $250 Deductible",
             "source": "RULE", "rule_id": "R-001", "page": "Coverages/RATES"},
        ])])
        assert "Decisiones tomadas" in html
        assert "Roadside Assistance" in html
        assert "R-001" in html

    def test_dudosas_van_primero_con_warning(self):
        html = render_rpa_section([self._outcome([
            {"field": "Con-Regla", "chosen": "A", "source": "RULE", "rule_id": "R-001"},
            {"field": "Sin-Regla", "chosen": "B", "source": "DEFAULTED", "rule_id": None},
        ])])
        assert html.index("Sin-Regla") < html.index("Con-Regla")
        assert "&#9888;" in html  # ⚠ en la dudosa

    def test_matched_no_es_dudosa(self):
        """MATCHED = dato del BlueQuote mapeado — no lleva warning."""
        html = render_rpa_section([self._outcome([
            {"field": "Body Type", "chosen": "Dump Truck", "source": "MATCHED",
             "rule_id": None},
        ])])
        assert "&#9888;" not in html

    def test_no_quoted_sin_tabla(self):
        out = RpaQuoteOutcome(mga="GEICO", status="halted", reason="not_eligible",
                              decisions=[{"field": "X", "chosen": "Y",
                                          "source": "DEFAULTED", "rule_id": None}])
        html = render_rpa_section([out])
        assert "Decisiones tomadas" not in html

    def test_decisions_none_no_rompe(self):
        html = render_rpa_section([self._outcome(None)])
        assert "PROGRESSIVE" in html
        assert "Decisiones tomadas" not in html
```

- [ ] **Step 2: Verificar que fallan**

Run: `<PY> -m pytest tests/quote_queue/test_messages.py -v -k Decisions`
Expected: FAIL (`RpaQuoteOutcome` no tiene `decisions`).

- [ ] **Step 3: Implementación**

En `modules/quote_queue/messages.py`:

(a) `RpaQuoteOutcome`: agregar campo

```python
decisions: Optional[List[dict]] = None   # entradas del decision_ledger (solo quoted)
```

(b) Función nueva:

```python
def _is_dudosa(d: dict) -> bool:
    """Dudosa = decisión SIN regla de negocio detrás y que tampoco es un
    simple mapeo del dato del BlueQuote (MATCHED). Van arriba con ⚠ para
    que negocios las revise primero."""
    return not d.get("rule_id") and d.get("source") != "MATCHED"


def _decisions_table(decisions: List[dict]) -> str:
    """Tabla 'Decisiones tomadas' bajo la fila de una MGA que cotizó."""
    ordered = sorted(decisions, key=lambda d: 0 if _is_dudosa(d) else 1)
    rows = ""
    for d in ordered:
        warn = "&#9888; " if _is_dudosa(d) else ""
        fuente = d.get("rule_id") or d.get("source", "")
        page = f' <span style="color:#8c95a6;">({d["page"]})</span>' if d.get("page") else ""
        rows += (
            f'<tr>'
            f'<td style="padding:4px 8px;font-family:Arial,Helvetica,sans-serif;'
            f'font-size:11px;color:#0a1628;border-top:1px solid #e8eaee;">'
            f'{warn}{d.get("field", "?")}{page}</td>'
            f'<td style="padding:4px 8px;font-family:Arial,Helvetica,sans-serif;'
            f'font-size:11px;font-weight:bold;color:#0a1628;border-top:1px solid #e8eaee;">'
            f'{d.get("chosen", "?")}</td>'
            f'<td style="padding:4px 8px;font-family:Arial,Helvetica,sans-serif;'
            f'font-size:11px;color:#5a6577;border-top:1px solid #e8eaee;">{fuente}</td>'
            f'</tr>'
        )
    return (
        '<p style="margin:8px 0 4px 0;font-family:Arial,Helvetica,sans-serif;'
        'font-size:11px;font-weight:bold;letter-spacing:1px;text-transform:uppercase;'
        'color:#8c95a6;">Decisiones tomadas</p>'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="border:1px solid #e8eaee;border-radius:4px;">'
        '<tr>'
        '<td style="padding:4px 8px;font-family:Arial,Helvetica,sans-serif;font-size:10px;'
        'text-transform:uppercase;color:#8c95a6;">Campo</td>'
        '<td style="padding:4px 8px;font-family:Arial,Helvetica,sans-serif;font-size:10px;'
        'text-transform:uppercase;color:#8c95a6;">Valor</td>'
        '<td style="padding:4px 8px;font-family:Arial,Helvetica,sans-serif;font-size:10px;'
        'text-transform:uppercase;color:#8c95a6;">Fuente</td>'
        '</tr>'
        f'{rows}'
        '</table>'
    )
```

(c) `_row`: después del `<p>` de `humanize(outcome)` y antes del cierre `</td></tr>`, insertar:

```python
quoted = outcome.reason in ("ok", "ok_no_pdf")
decisions_html = ""
if quoted and outcome.decisions:
    decisions_html = _decisions_table(outcome.decisions)
```

e interpolar `{decisions_html}` en el f-string de la fila (la variable `quoted` ya existe en `_row` — reusarla).

En `modules/quote_queue/worker.py` `maybe_send_submission_email`, al armar los outcomes:

```python
def _decisions_for(j) -> Optional[list]:
    """Deserializa el ledger del job. Best-effort: malformado → None."""
    if j.status != JobStatus.QUOTED.value or not j.decisions_json:
        return None
    try:
        return json.loads(j.decisions_json)
    except (ValueError, TypeError) as e:
        print(f"    [worker:{self.mga}] decisions_json malformado job {j.id}: {e}")
        return None

outcomes: List[RpaQuoteOutcome] = [
    RpaQuoteOutcome(
        mga=j.mga, status=j.status, reason=(j.error or "error"),
        premium=j.premium, pdf_path=j.pdf_path,
        decisions=_decisions_for(j),
    )
    for j in jobs
]
```

(`_decisions_for` como método privado o closure — mantener el estilo del archivo.)

- [ ] **Step 4: Verificar**

Run: `<PY> -m pytest tests/quote_queue/ -v`
Expected: PASS todos.

- [ ] **Step 5: Commit**

```bash
git add modules/quote_queue/messages.py modules/quote_queue/worker.py tests/quote_queue/test_messages.py tests/quote_queue/test_worker_email.py
git commit -m "feat(email): tabla 'Decisiones tomadas' por MGA cotizada - dudosas primero con warning"
```

---

### Task 8: Documentación del circuito + verificación final

**Files:**
- Modify: `docs/AGENTS_CONTEXT.md` (sección nueva)
- Modify: `CLAUDE.md` (nota breve en "Estado actual")
- Test: suite completa + simulador

**Interfaces:**
- Consumes: todo lo anterior.
- Produces: circuito documentado; suite verde.

- [ ] **Step 1: Documentar el circuito en `docs/AGENTS_CONTEXT.md`**

Agregar al final:

```markdown
## Decision Ledger + servicio transparente (2026-07-29)

**Servicio transparente:** el runner NO etiqueta, NO marca leído, NO responde
el hilo de ventas. Dedup por Gmail message-id en `seen_emails` (cola SQLite).
El análisis sale como correo NUEVO a `EMAIL_ANALYSIS_TO` (estabilización:
dianarubio@h2oins.com — cambiar en `.env` al salir de estabilización).

**Decision Ledger:** `modules/decision_ledger.py` (thread-local, best-effort).
`choice_resolver` registra automático; sitios hardcodeados citan `rule_id` del
Excel `config/mga_decision_rules.xlsx` (hojas `reglas` + `instrucciones`).
El worker persiste `decisions_json` en el job y el correo muestra la tabla
"Decisiones tomadas" por MGA cotizada (dudosas ⚠ arriba). El bot NO lee el
Excel en runtime: código = fuente ejecutable, Excel = fuente humana.

**Circuito de corrección:** Diana responde el correo → actualizar fila del
Excel (Decisión, Fuente=Negocio, Quote ref, Estado=PENDIENTE-código) → fix en
código citando el ID en el commit → Estado=VIGENTE. Filas EN-DUDA = agenda de
la sesión de validación con negocios.
```

- [ ] **Step 2: Nota en `CLAUDE.md`**

En la sección "Estado actual", agregar una línea:

```markdown
✅ Decision Ledger + servicio transparente (2026-07-29): dedup por message-id,
   análisis a EMAIL_ANALYSIS_TO, tabla "Decisiones tomadas" + "por qué" del
   rule engine en el correo. Registro: config/mga_decision_rules.xlsx.
```

- [ ] **Step 3: Suite completa**

Run: `<PY> -m pytest tests/ -q`
Expected: todo verde salvo las **2 fallas pre-existentes de `tests/test_rule_engine.py`**. Cualquier otra falla se arregla antes de seguir.

- [ ] **Step 4: Simulador end-to-end**

Run: `<PY> tests/simulate_progressive.py`
Expected: corre sin errores. Verificar en la salida (o agregando un print temporal al final del simulador) que `decision_ledger.entries()` quedó poblado tras la corrida simulada — si el simulador no pasa por `client.create_quote`, llamar `decision_ledger.start_run("PROGRESSIVE")` al inicio del script del simulador para que el hook registre.

- [ ] **Step 5: Commit final**

```bash
git add docs/AGENTS_CONTEXT.md CLAUDE.md
git commit -m "docs: circuito de correccion del decision ledger + estado actual"
```

---

## Self-Review (ya aplicado)

- **Spec coverage:** transparencia+dedup → Tasks 1-2; correo nuevo a Diana → Task 3; "por qué" rule engine → Task 4; ledger compartido + hook + GEICO → Task 5; auditoría + Excel + rule_ids → Task 6; tabla decisiones (solo quoted, dudosas primero) → Task 7; documentación circuito → Task 8. ✓
- **Divergencia deliberada del spec (documentada):** el spec decía "el resultado de quote_flow suma la clave `decisions`"; la implementación captura `entries()` en el worker tras `create_quote` — mismo contrato observable, sin tocar los múltiples puntos de construcción de `QuoteResult` de ambos MGAs, y con thread-local para aislar workers concurrentes.
- **Types:** `try_claim_email(str)->bool`, `mark_terminal(decisions_json=None)`, `QuoteJob.decisions_json`, `RpaQuoteOutcome.decisions`, `record(field, chosen, *, page, options, source, rule_id, note)` consistentes entre tasks. ✓
