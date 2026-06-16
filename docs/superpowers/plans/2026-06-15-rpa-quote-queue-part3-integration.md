# Cola de Cotización RPA — Parte 3: Integración del pipeline (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Conectar la cola (Parte 1) y la captura PDF (Parte 2) al pipeline real: encolar la cotización RPA cuando hay MGA elegible, cotizar en background con un worker por MGA, y enviar **un solo correo de análisis al agente** — con la impresión PDF adjunta y un mensaje humanizado por MGA — recién cuando las cotizaciones terminan.

**Architecture:** El orquestador, cuando hay MGA-RPA elegible, **pre-renderiza** el cuerpo del análisis con un marcador `<!--RPA_QUOTES_SECTION-->`, persiste el contexto (recipient, subject, body con marcador, paths de adjuntos originales) en `submissions`, y **encola un job por MGA** en vez de mandar el correo. Un `QuoteWorker` por MGA (en `runner.py`, hilos separados, serial intra-MGA) reclama jobs, llama `XClient.create_quote`, clasifica el resultado a un estado terminal + razón humanizable, y cuando **todos** los jobs de la submission terminaron, reclama el envío (anti doble-envío) y manda el correo: reemplaza el marcador por la sección RPA (`messages.render_rpa_section`) y adjunta los PDFs. Si NO hay MGA-RPA elegible, el correo sale al instante como hoy.

**Tech Stack:** Python 3.12, stdlib (`json`, `hashlib`, `threading`, `time`, `pathlib`), `pytest`. Reusa `modules/quote_queue/` (Parte 1), `EmailSender`, `build_analysis_email`, `ProgressiveClient`/`GEICOClient`.

**Depende de:** Parte 1 (`modules/quote_queue/{models,store}.py`) y Parte 2 (`pdf_path` en ambos `QuoteResult`). Implementar DESPUÉS de ambas.

**Spec:** `docs/superpowers/specs/2026-06-15-rpa-quote-queue-design.md`
**Intérprete Python:** `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe`

**Hechos verificados contra el código (no re-derivar):**
- `email_data['attachments']` = `list[{"filename", "data": bytes, "content_type"}]`. `email_data['raw_message'].get('Message-ID')` existe. `EmailSender.send_email(to_email, subject, body, ..., attachments=List[str]|List[dict], is_html=bool)` acepta paths o dicts `{filename,data}`.
- `build_analysis_email(profile, commodity, tipo_negocio, evaluations, mga_list, original_subject, confirmation_keyword="APROBAR") -> {"subject","body","is_html":True}`. Rinde un template `config/templates/analysis_email.html` vía `.format(...)` (el bloque `<!--[if mso]>` ya escapa `{{}}`).
- `ProgressiveClient.create_quote(profile, effective_date=None) -> QuoteResult`. Asumir `GEICOClient.create_quote(profile, effective_date=None) -> QuoteResult` (mismo shape — confirmar en `modules/geico/client.py` antes de cablear el runner).
- El orquestador hoy SOLO trata Progressive como web automation (`_dispatch_to_mgas` tiene rama `if mga_name.upper()=="PROGRESSIVE"`). NO dispatcha GEICO. `summary_to = self.test_email_override or self.summary_email` es el destinatario (agente interno).
- QuoteResult difiere por MGA: ambos tienen `success`, `error`, `price` (con `.annual_premium`, `.quote_number`), `pdf_path` (Progressive lo gana en Parte 2). GEICO ADEMÁS: `halted`, `needs_manual_review`, `is_stub`, `session_expired`. El clasificador usa `getattr(result, flag, False)` para tolerar la ausencia en Progressive.

**Decisión de alcance:** el gate `APROBAR` + dispatch a MGAs-por-email (`_pending_approvals`, `_handle_confirmation`) queda **igual** — la cola sólo enriquece y difiere el correo de análisis. Reemplazar `_pending_approvals` por la tabla `submissions` es trabajo futuro (no acá).

---

## File Structure

- **Create** `modules/quote_queue/messages.py` — `RpaQuoteOutcome`, `RPA_SECTION_MARKER`, `humanize`, `render_rpa_section`.
- **Modify** `modules/analysis_email_builder.py` — param `rpa_quotes_section: str = ""`.
- **Modify** `config/templates/analysis_email.html` — placeholder `{rpa_quotes_section}`.
- **Create** `modules/quote_queue/worker.py` — `classify_result` + `QuoteWorker`.
- **Modify** `workflow_orchestrator.py` — encolar + persistir contexto cuando hay MGA-RPA elegible; enviar al instante si no.
- **Create** `runner.py` — entrypoint: monitor de inbox (productor) + worker-threads (consumidores) + `reclaim_stale` al arrancar.
- **Modify** `.gitignore` — `data/quote_queue.db`, `data/submissions/`.
- **Create** tests: `tests/quote_queue/test_messages.py`, `tests/quote_queue/test_classify.py`, `tests/quote_queue/test_worker_email.py`, `tests/test_analysis_email_rpa_section.py`.

---

## Task 1: `messages.py` — catálogo humanizado dirigido al agente

**Files:**
- Create: `modules/quote_queue/messages.py`
- Test: `tests/quote_queue/test_messages.py`

- [ ] **Step 1: Escribir el test que falla**

Create `tests/quote_queue/test_messages.py`:

```python
from modules.quote_queue.messages import (
    RpaQuoteOutcome, RPA_SECTION_MARKER, humanize, render_rpa_section,
)


def test_quoted_with_pdf_shows_premium():
    msg = humanize(RpaQuoteOutcome(mga="PROGRESSIVE", status="quoted",
                                   reason="ok", premium="$44,621", pdf_path="x.pdf"))
    assert "PROGRESSIVE" in msg and "$44,621" in msg


def test_quoted_without_pdf_notes_missing_print():
    msg = humanize(RpaQuoteOutcome(mga="GEICO", status="quoted",
                                   reason="ok_no_pdf", premium="$15,512"))
    assert "$15,512" in msg
    assert "impresión" in msg.lower()


def test_needs_ssn_is_actionable_and_not_technical():
    msg = humanize(RpaQuoteOutcome(mga="GEICO", status="halted", reason="needs_ssn"))
    assert "SSN" in msg
    # No filtra jerga técnica:
    assert "needs_manual_review" not in msg
    assert "Traceback" not in msg


def test_not_eligible_message():
    msg = humanize(RpaQuoteOutcome(mga="PROGRESSIVE", status="halted", reason="not_eligible"))
    assert "elegibilidad" in msg.lower()


def test_pending_retry_message():
    msg = humanize(RpaQuoteOutcome(mga="GEICO", status="deferred", reason="pending_retry"))
    assert "pendiente" in msg.lower()


def test_failed_message_is_clean():
    msg = humanize(RpaQuoteOutcome(mga="PROGRESSIVE", status="failed",
                                   reason="error", detail="KeyError at line 99"))
    assert "manualmente" in msg.lower()
    assert "KeyError" not in msg  # el detalle técnico NO va al texto humano


def test_render_section_contains_marker_text_and_each_outcome():
    html = render_rpa_section([
        RpaQuoteOutcome(mga="PROGRESSIVE", status="quoted", reason="ok",
                        premium="$44,621", pdf_path="x.pdf"),
        RpaQuoteOutcome(mga="GEICO", status="halted", reason="needs_ssn"),
    ])
    assert "PROGRESSIVE" in html and "$44,621" in html
    assert "GEICO" in html and "SSN" in html


def test_marker_is_html_comment():
    assert RPA_SECTION_MARKER.startswith("<!--") and RPA_SECTION_MARKER.endswith("-->")
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/quote_queue/test_messages.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'modules.quote_queue.messages'`.

- [ ] **Step 3: Implementar el catálogo**

Create `modules/quote_queue/messages.py`:

```python
"""
Catálogo de mensajes humanizados de la cola RPA, dirigidos al AGENTE interno.

Dos capas: la TÉCNICA (status + reason code + detail crudo) vive en DB/logs;
esta capa traduce a español claro, con instrucción de acción/escalamiento,
SIN jerga ni rutas de archivo. El correo de análisis lo lee el agente, no el
cliente final.
"""

from dataclasses import dataclass
from typing import List, Optional


# Marcador que el orquestador deja en el cuerpo del correo (pre-render) y que
# el worker reemplaza por la sección RPA real una vez cotizado.
RPA_SECTION_MARKER = "<!--RPA_QUOTES_SECTION-->"


@dataclass
class RpaQuoteOutcome:
    """Desenlace de una cotización RPA para una MGA (lo que entra al correo)."""
    mga: str
    status: str                      # JobStatus value: quoted/failed/halted/deferred
    reason: str                      # reason code: ok/ok_no_pdf/needs_ssn/not_eligible/pending_retry/error
    premium: Optional[str] = None
    pdf_path: Optional[str] = None
    detail: Optional[str] = None     # detalle técnico — NUNCA se muestra al agente


def humanize(outcome: "RpaQuoteOutcome") -> str:
    """Mensaje claro para el agente. El `detail` técnico nunca se incluye."""
    mga = outcome.mga
    premium = outcome.premium or "(precio no capturado)"
    reason = outcome.reason

    if reason == "ok":
        return f"{mga} cotizó: {premium}. Impresión de la página de precio adjunta."
    if reason == "ok_no_pdf":
        return (f"{mga} cotizó: {premium}. No se pudo generar la impresión esta "
                f"vez; el precio quedó confirmado.")
    if reason == "needs_ssn":
        return (f"{mga} requiere el SSN del titular para verificar su identidad "
                f"antes de cotizar. Acción: solicitar el SSN al cliente y "
                f"reintentar — no se autocompleta por política de seguridad.")
    if reason == "not_eligible":
        return (f"{mga} no puede cotizar este negocio por sus reglas de "
                f"elegibilidad (verificación FMCSA/USDOT). No requiere reintento; "
                f"evaluar un MGA alternativo.")
    if reason == "pending_retry":
        return (f"Cotización de {mga} pendiente (producto no disponible o espera "
                f"de OTP). Se reintentará automáticamente; no requiere acción.")
    # reason == "error" (o desconocido)
    return (f"No se pudo completar la cotización de {mga} automáticamente. "
            f"Acción: revisar manualmente (detalle técnico en los logs internos).")


def _row(outcome: "RpaQuoteOutcome") -> str:
    quoted = outcome.reason in ("ok", "ok_no_pdf")
    accent = "#0d7a3f" if quoted else "#b8860b"
    return (
        f'<tr><td style="padding:12px 16px;border-bottom:1px solid #e8eaee;">'
        f'<p style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:14px;'
        f'font-weight:bold;color:{accent};">{outcome.mga}</p>'
        f'<p style="margin:4px 0 0 0;font-family:Arial,Helvetica,sans-serif;'
        f'font-size:13px;color:#0a1628;line-height:1.5;">{humanize(outcome)}</p>'
        f'</td></tr>'
    )


def render_rpa_section(outcomes: List["RpaQuoteOutcome"]) -> str:
    """Bloque HTML con las cotizaciones RPA, al estilo del resto del correo."""
    if not outcomes:
        return ""
    rows = "".join(_row(o) for o in outcomes)
    return (
        '<tr><td style="padding:8px 32px 4px 32px;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'border="0" style="background-color:#1a5276;border-radius:6px 6px 0 0;">'
        '<tr><td style="padding:14px 20px;">'
        '<p style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:12px;'
        'font-weight:bold;letter-spacing:1.5px;text-transform:uppercase;color:#ffffff;">'
        '&#9679; Cotizaciones automáticas (RPA)</p>'
        '</td></tr></table></td></tr>'
        '<tr><td style="padding:0 32px 20px 32px;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'border="0" style="border:1px solid #bcd2e8;border-top:none;'
        'border-radius:0 0 6px 6px;overflow:hidden;">'
        f'{rows}'
        '</table></td></tr>'
    )
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/quote_queue/test_messages.py -v`
Expected: PASS (8 passed).

- [ ] **Step 5: pyflakes + commit**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pyflakes modules/quote_queue/messages.py`
Expected: sin salida.

```bash
git add modules/quote_queue/messages.py tests/quote_queue/test_messages.py
git commit -m "feat(quote-queue): catalogo de mensajes humanizados al agente + render seccion RPA"
```

---

## Task 2: `build_analysis_email` — slot `{rpa_quotes_section}` + placeholder en el template

**Files:**
- Modify: `config/templates/analysis_email.html` (agregar placeholder)
- Modify: `modules/analysis_email_builder.py` (param + pasar al `.format`)
- Test: `tests/test_analysis_email_rpa_section.py`

- [ ] **Step 1: Escribir el test que falla**

Create `tests/test_analysis_email_rpa_section.py`:

```python
from modules.quote_profile import QuoteProfile
from modules.analysis_email_builder import build_analysis_email


def _email(**kw):
    return build_analysis_email(
        profile=QuoteProfile(),
        commodity="N/A",
        tipo_negocio="N/A",
        evaluations=[],
        mga_list=[],
        original_subject="Submission // TEST",
        **kw,
    )


def test_default_has_no_rpa_section():
    out = _email()
    assert "<!--RPA_QUOTES_SECTION-->" not in out["body"]  # default vacío, sin marcador


def test_passed_rpa_section_is_embedded():
    out = _email(rpa_quotes_section="<!--RPA_QUOTES_SECTION-->")
    assert "<!--RPA_QUOTES_SECTION-->" in out["body"]


def test_passed_html_block_is_embedded():
    out = _email(rpa_quotes_section="<tr><td>HOLA_RPA</td></tr>")
    assert "HOLA_RPA" in out["body"]
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/test_analysis_email_rpa_section.py -v`
Expected: FAIL — `test_passed_rpa_section_is_embedded` falla porque hoy no existe el slot (el `.format` ignoraría el kwarg extra... en realidad fallará distinto: ver nota). El objetivo es ver rojo antes de implementar.

> Nota: `str.format` IGNORA kwargs extra, así que sin el cambio el `body` no contendrá el bloque. Y `build_analysis_email` aún no acepta `rpa_quotes_section`, así que los tests fallan con `TypeError: unexpected keyword argument`. Eso es el rojo esperado.

- [ ] **Step 3: Agregar el placeholder al template**

En `config/templates/analysis_email.html`, JUSTO DESPUÉS de la línea del warnings banner (`{warnings_banner}`, línea 48) y antes del comentario `<!-- ====== CLIENT INFO ====== -->`, insertar una línea:

```html
{rpa_quotes_section}
```

(Queda como un slot que rinde el bloque RPA arriba del todo, debajo del banner de warnings.)

- [ ] **Step 4: Agregar el param a `build_analysis_email`**

En `modules/analysis_email_builder.py`:

1. Agregar el parámetro a la firma (al final, con default vacío):

```python
def build_analysis_email(
    profile: QuoteProfile,
    commodity: str,
    tipo_negocio: str,
    evaluations: List[MGAEvaluation],
    mga_list: List[Dict[str, str]],
    original_subject: str,
    confirmation_keyword: str = "APROBAR",
    rpa_quotes_section: str = "",
) -> Dict[str, str]:
```

2. En la llamada `template.format(...)` (la que arma `body`), agregar el kwarg:

```python
        rpa_quotes_section=rpa_quotes_section,
```

(agregalo junto a los demás, p.ej. después de `warnings_banner=warnings_banner,`).

- [ ] **Step 5: Correr y verificar que pasa**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/test_analysis_email_rpa_section.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: pyflakes + commit**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pyflakes modules/analysis_email_builder.py`
Expected: sin salida.

```bash
git add config/templates/analysis_email.html modules/analysis_email_builder.py tests/test_analysis_email_rpa_section.py
git commit -m "feat(analysis-email): slot rpa_quotes_section para inyectar las cotizaciones RPA"
```

---

## Task 3: `worker.py` — `classify_result` + `QuoteWorker`

**Files:**
- Create: `modules/quote_queue/worker.py`
- Test: `tests/quote_queue/test_classify.py`, `tests/quote_queue/test_worker_email.py`

- [ ] **Step 1: Escribir los tests que fallan (classify)**

Create `tests/quote_queue/test_classify.py`:

```python
from types import SimpleNamespace

from modules.quote_queue.worker import classify_result


def _price(premium=None, quote_number=None):
    return SimpleNamespace(annual_premium=premium, quote_number=quote_number)


def test_success_with_pdf_is_quoted_ok():
    r = SimpleNamespace(success=True, price=_price("$44,621", "CA1"), pdf_path="x.pdf", error=None)
    status, reason, premium, quote_number, pdf_path = classify_result(r)
    assert (status, reason) == ("quoted", "ok")
    assert premium == "$44,621" and quote_number == "CA1" and pdf_path == "x.pdf"


def test_success_without_pdf_is_quoted_no_pdf():
    r = SimpleNamespace(success=True, price=_price("$15,512"), pdf_path=None, error=None)
    status, reason, *_ = classify_result(r)
    assert (status, reason) == ("quoted", "ok_no_pdf")


def test_needs_manual_review_is_needs_ssn():
    r = SimpleNamespace(success=False, needs_manual_review=True, error="owner SSN required")
    status, reason, *_ = classify_result(r)
    assert (status, reason) == ("halted", "needs_ssn")


def test_halted_is_not_eligible():
    r = SimpleNamespace(success=False, halted=True, error="FMCSA reject")
    status, reason, *_ = classify_result(r)
    assert (status, reason) == ("halted", "not_eligible")


def test_session_expired_is_deferred():
    r = SimpleNamespace(success=False, session_expired=True, error="zombie session")
    status, reason, *_ = classify_result(r)
    assert (status, reason) == ("deferred", "pending_retry")


def test_progressive_ssn_via_error_text():
    # Progressive no tiene flags; se detecta por el texto del error.
    r = SimpleNamespace(success=False, error="HALT: Progressive pide SSN del driver")
    status, reason, *_ = classify_result(r)
    assert (status, reason) == ("halted", "needs_ssn")


def test_unknown_failure_is_error():
    r = SimpleNamespace(success=False, error="boom at line 42")
    status, reason, *_ = classify_result(r)
    assert (status, reason) == ("failed", "error")
```

- [ ] **Step 2: Escribir los tests que fallan (worker email assembly)**

Create `tests/quote_queue/test_worker_email.py`:

```python
import json

import pytest

from modules.quote_queue.models import JobStatus
from modules.quote_queue.store import QuoteQueueStore
from modules.quote_queue.messages import RPA_SECTION_MARKER
from modules.quote_queue.worker import QuoteWorker


class FakeSender:
    def __init__(self):
        self.sent = []

    def send_email(self, to_email, subject, body, attachments=None, is_html=False, **kw):
        self.sent.append({"to": to_email, "subject": subject, "body": body,
                          "attachments": attachments or [], "is_html": is_html})
        return True


@pytest.fixture()
def store(tmp_path):
    s = QuoteQueueStore(tmp_path / "q.db")
    yield s
    s.close()


def _ctx(tmp_path):
    return json.dumps({
        "recipient": "agente@h2o.com",
        "subject": "[ANALISIS] Submission // RYD",
        "body_html": f"<html>ANALISIS {RPA_SECTION_MARKER} FIN</html>",
        "attachment_paths": [],
    })


def test_email_not_sent_until_all_terminal(tmp_path, store):
    store.save_submission_context("sub-1", _ctx(tmp_path))
    j1 = store.enqueue("sub-1", "PROGRESSIVE", "{}", None, "111")
    store.enqueue("sub-1", "GEICO", "{}", None, "111")
    store.claim_next("PROGRESSIVE")
    store.mark_terminal(j1, JobStatus.QUOTED, premium="$44,621", pdf_path="p.pdf", error="ok")

    sender = FakeSender()
    worker = QuoteWorker("PROGRESSIVE", store, create_quote=lambda *a, **k: None,
                         email_sender=sender)
    # Sólo un job terminó → no se manda
    worker.maybe_send_submission_email("sub-1")
    assert sender.sent == []


def test_email_sent_once_when_all_terminal_with_marker_replaced(tmp_path, store):
    store.save_submission_context("sub-1", _ctx(tmp_path))
    j1 = store.enqueue("sub-1", "PROGRESSIVE", "{}", None, "111")
    j2 = store.enqueue("sub-1", "GEICO", "{}", None, "111")
    store.claim_next("PROGRESSIVE")
    store.mark_terminal(j1, JobStatus.QUOTED, premium="$44,621", pdf_path="p.pdf", error="ok")
    store.claim_next("GEICO")
    store.mark_terminal(j2, JobStatus.HALTED, error="needs_ssn")

    sender = FakeSender()
    worker = QuoteWorker("PROGRESSIVE", store, create_quote=lambda *a, **k: None,
                         email_sender=sender)
    worker.maybe_send_submission_email("sub-1")

    assert len(sender.sent) == 1
    msg = sender.sent[0]
    assert msg["to"] == "agente@h2o.com"
    assert msg["is_html"] is True
    assert RPA_SECTION_MARKER not in msg["body"]        # marcador reemplazado
    assert "$44,621" in msg["body"] and "SSN" in msg["body"]
    assert "p.pdf" in msg["attachments"]                # PDF adjuntado

    # Anti doble-envío: una segunda corrida no manda de nuevo
    worker.maybe_send_submission_email("sub-1")
    assert len(sender.sent) == 1
```

- [ ] **Step 3: Correr y verificar que fallan**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/quote_queue/test_classify.py tests/quote_queue/test_worker_email.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'modules.quote_queue.worker'`.

- [ ] **Step 4: Implementar `worker.py`**

Create `modules/quote_queue/worker.py`:

```python
"""
QuoteWorker — consumidor de la cola, uno por MGA.

Reclama jobs en serie (sesión única por MGA), corre create_quote, clasifica el
resultado a un estado terminal + reason code humanizable, y cuando TODOS los
jobs de una submission terminaron, manda el correo de análisis (una sola vez)
con la sección RPA inyectada y los PDFs adjuntos.
"""

import json
import time
from typing import Callable, List, Optional

from modules.quote_profile import QuoteProfile
from modules.quote_queue.models import JobStatus
from modules.quote_queue.messages import (
    RpaQuoteOutcome, RPA_SECTION_MARKER, render_rpa_section,
)


# Tras este nº de intentos, un job 'deferred' deja de bloquear el correo: se
# marca terminal (pending_retry → halted) para no esperar para siempre.
MAX_DEFER_ATTEMPTS = 3
# Backoff por defecto al diferir (producto no disponible / cooldown de OTP).
DEFER_SECONDS = 1800


def classify_result(result) -> tuple:
    """Mapa QuoteResult → (status, reason, premium, quote_number, pdf_path).

    `status` ∈ {quoted, halted, deferred, failed}. `reason` es un código
    humanizable (ver messages.humanize). Tolera QuoteResults sin los flags de
    GEICO vía getattr; para Progressive cae a matchear el texto del error.
    """
    price = getattr(result, "price", None)
    premium = getattr(price, "annual_premium", None) if price else None
    quote_number = getattr(price, "quote_number", None) if price else None
    pdf_path = getattr(result, "pdf_path", None)

    if getattr(result, "success", False):
        reason = "ok" if pdf_path else "ok_no_pdf"
        return ("quoted", reason, premium, quote_number, pdf_path)

    if getattr(result, "needs_manual_review", False):
        return ("halted", "needs_ssn", premium, quote_number, pdf_path)
    if getattr(result, "halted", False):
        return ("halted", "not_eligible", premium, quote_number, pdf_path)
    if getattr(result, "session_expired", False):
        return ("deferred", "pending_retry", premium, quote_number, pdf_path)

    # Progressive (sin flags): inferir por el texto del error.
    err = (getattr(result, "error", None) or "").lower()
    if "ssn" in err or "social security" in err:
        return ("halted", "needs_ssn", premium, quote_number, pdf_path)
    if "elegib" in err or "fmcsa" in err or "unable to complete" in err:
        return ("halted", "not_eligible", premium, quote_number, pdf_path)

    return ("failed", "error", premium, quote_number, pdf_path)


class QuoteWorker:
    def __init__(self, mga: str, store, create_quote: Callable, email_sender):
        self.mga = mga
        self.store = store
        self.create_quote = create_quote   # (profile, effective_date) -> QuoteResult
        self.email_sender = email_sender    # objeto con send_email(...)

    def run_once(self) -> bool:
        """Procesa un job. Devuelve True si tomó uno, False si la cola estaba vacía."""
        job = self.store.claim_next(self.mga)
        if job is None:
            return False
        self.store.mark_running(job.id)

        try:
            profile = QuoteProfile.from_dict(json.loads(job.profile_json))
            result = self.create_quote(profile, job.effective_date)
        except Exception as e:  # falla dura del cliente RPA
            self.store.mark_terminal(job.id, JobStatus.FAILED, error="error",
                                     screenshot_path=None)
            print(f"    [worker:{self.mga}] create_quote crashed: {e}")
            self.maybe_send_submission_email(job.submission_id)
            return True

        status, reason, premium, quote_number, pdf_path = classify_result(result)
        screenshot = getattr(result, "screenshot_path", None)

        if status == "deferred" and job.attempts < MAX_DEFER_ATTEMPTS:
            self.store.mark_deferred(job.id, retry_after=time.time() + DEFER_SECONDS)
            print(f"    [worker:{self.mga}] job {job.id} deferred "
                  f"(attempt {job.attempts}/{MAX_DEFER_ATTEMPTS})")
            return True

        # deferred agotado → no bloquear el correo: tratar como halted pendiente.
        if status == "deferred":
            status, reason = "halted", "pending_retry"

        self.store.mark_terminal(
            job.id, JobStatus(status), premium=premium, quote_number=quote_number,
            pdf_path=pdf_path, screenshot_path=screenshot, error=reason,
        )
        self.maybe_send_submission_email(job.submission_id)
        return True

    def maybe_send_submission_email(self, submission_id: str) -> bool:
        """Si todos los jobs terminaron, manda el correo de análisis UNA vez."""
        if not self.store.siblings_all_terminal(submission_id):
            return False
        if not self.store.try_claim_submission_email(submission_id):
            return False  # otro worker ya lo está mandando / lo mandó

        raw_ctx = self.store.get_submission_context(submission_id)
        if not raw_ctx:
            print(f"    [worker:{self.mga}] no context for {submission_id}; skip email")
            return False
        ctx = json.loads(raw_ctx)

        jobs = self.store.get_jobs(submission_id)
        outcomes: List[RpaQuoteOutcome] = [
            RpaQuoteOutcome(
                mga=j.mga, status=j.status, reason=(j.error or "error"),
                premium=j.premium, pdf_path=j.pdf_path,
            )
            for j in jobs
        ]
        body = ctx["body_html"].replace(RPA_SECTION_MARKER, render_rpa_section(outcomes))

        attachments = list(ctx.get("attachment_paths", []))
        attachments += [j.pdf_path for j in jobs if j.pdf_path]

        ok = self.email_sender.send_email(
            to_email=ctx["recipient"],
            subject=ctx["subject"],
            body=body,
            attachments=attachments,
            is_html=True,
        )
        print(f"    [worker:{self.mga}] analysis email for {submission_id} "
              f"sent={ok} (outcomes={len(outcomes)})")
        return ok
```

- [ ] **Step 5: Correr y verificar que pasan**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/quote_queue/test_classify.py tests/quote_queue/test_worker_email.py -v`
Expected: PASS (classify 7 + worker 2).

- [ ] **Step 6: pyflakes + commit**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pyflakes modules/quote_queue/worker.py`
Expected: sin salida.

```bash
git add modules/quote_queue/worker.py tests/quote_queue/test_classify.py tests/quote_queue/test_worker_email.py
git commit -m "feat(quote-queue): QuoteWorker + classify_result (resultado RPA -> estado + razon humanizable)"
```

> **Nota de validación:** el `classify_result` para Progressive usa matching de texto del error (`ssn`, `elegib`, `fmcsa`). Durante la validación LIVE, comparar contra los strings reales de error de Progressive (NoHit/HALT) y ajustar los tokens si hace falta. El default seguro es `failed/error` (revisión manual), nunca un falso "cotizó".

---

## Task 4: Orquestador — encolar + persistir contexto (o enviar al instante si no hay RPA)

**Files:**
- Modify: `workflow_orchestrator.py`
- Modify: `.gitignore` (agregar `data/quote_queue.db`, `data/submissions/`)

> **Validación:** wiring del pipeline real — se valida LIVE (con correo + extracción). Los unit tests de las piezas (store, worker, messages, email builder) ya cubren la lógica. Acá el foco es enganchar sin romper el flujo existente.

- [ ] **Step 1: Imports + store compartido en `__init__`**

En `workflow_orchestrator.py`, agregar imports arriba (junto a los demás `from modules...`):

```python
import hashlib
from pathlib import Path
from modules.quote_queue.store import QuoteQueueStore
from modules.quote_queue.messages import RPA_SECTION_MARKER
```

(`json` ya está importado arriba del archivo.)

Definir, a nivel de módulo (después de los imports):

```python
# Cola durable compartida entre el orquestador (productor) y el runner (workers).
QUOTE_DB_PATH = Path(__file__).resolve().parent / "data" / "quote_queue.db"
SUBMISSIONS_DIR = Path(__file__).resolve().parent / "data" / "submissions"

# MGAs que cotizan por RPA (web automation). GEICO detrás de flag.
def _rpa_mgas_enabled(config) -> set:
    mgas = {"PROGRESSIVE"}
    if str(config.get("rule_engine.geico_queue_enabled", False)).lower() in ("true", "1", "yes"):
        mgas.add("GEICO")
    return mgas
```

En `QuoteWorkflowOrchestrator.__init__`, al final, agregar:

```python
        # Cola de cotización RPA (durable). Productor: este orquestador.
        self.quote_store = QuoteQueueStore(QUOTE_DB_PATH)
        self.rpa_mgas = _rpa_mgas_enabled(self.config)
```

- [ ] **Step 2: Helpers de submission (id, persistencia de adjuntos)**

Agregar estos métodos a `QuoteWorkflowOrchestrator`:

```python
    @staticmethod
    def _submission_id(email_data: dict, profile) -> str:
        """ID estable de la submission: Message-ID si existe, si no hash(subject+usdot)."""
        raw = email_data.get("raw_message")
        msg_id = raw.get("Message-ID") if raw else None
        if msg_id:
            return msg_id.strip()
        usdot = (profile.applicant.usdot or "").strip()
        subject = email_data.get("subject", "")
        return "sub-" + hashlib.sha1(f"{subject}|{usdot}".encode("utf-8")).hexdigest()[:16]

    def _persist_attachments(self, submission_id: str, attachments: list) -> list:
        """Escribe los adjuntos originales a disco y devuelve sus paths."""
        safe = "".join(c if c.isalnum() else "_" for c in submission_id)[:40]
        out_dir = SUBMISSIONS_DIR / safe
        out_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for att in attachments:
            data = att.get("data")
            fname = att.get("filename") or "attachment.pdf"
            if not data:
                continue
            p = out_dir / fname
            p.write_bytes(data)
            paths.append(str(p))
        return paths
```

- [ ] **Step 3: Encolar en `_process_submission` (Step 5/6) en vez de enviar de una**

En `_process_submission`, REEMPLAZAR el bloque actual de "Step 5: Sending analysis summary" + "Step 8/Step 6" por la lógica nueva. Concretamente, después de calcular `evaluations` (Step 4), determinar los MGA-RPA elegibles y bifurcar:

```python
        # Step 5: build the analysis email body (rendered now; RPA section is a
        # placeholder marker filled in later by the worker, if we queue).
        eligible_rpa = self._eligible_rpa_mgas(evaluations, mga_list)

        analysis = build_analysis_email(
            profile=profile,
            commodity=commodity,
            tipo_negocio=tipo_negocio,
            evaluations=evaluations,
            mga_list=mga_list,
            original_subject=subject,
            confirmation_keyword=self.confirmation_keyword,
            rpa_quotes_section=(RPA_SECTION_MARKER if eligible_rpa else ""),
        )
        summary_to = self.test_email_override or self.summary_email

        if eligible_rpa and not self.dry_run:
            # Encolar: el worker manda el correo (con la impresión PDF) al terminar.
            submission_id = self._submission_id(email_data, profile)
            attachment_paths = self._persist_attachments(
                submission_id, email_data.get("attachments", []))
            self.quote_store.save_submission_context(submission_id, json.dumps({
                "recipient": summary_to,
                "subject": analysis["subject"],
                "body_html": analysis["body"],
                "attachment_paths": attachment_paths,
            }))
            eff_date = self._effective_date_from_subject(subject)
            now = time.time()
            queued = []
            for mga in sorted(eligible_rpa):
                if self.quote_store.recently_quoted(mga, profile.applicant.usdot or "", now - 86400) >= 3:
                    print(f"  [queue] SKIP {mga}: USDOT cotizado >=3x en 24h")
                    continue
                self.quote_store.enqueue(
                    submission_id, mga, json.dumps(profile.to_dict()),
                    eff_date, profile.applicant.usdot or "")
                queued.append(mga)
            print(f"  [queue] Encolado {submission_id}: {queued} "
                  f"(el correo de análisis sale al terminar la cotización)")
        else:
            # Sin MGA-RPA elegible (o dry_run): comportamiento actual — enviar ya.
            email_sender = EmailSender(self.email_address, self.email_password)
            if self.dry_run:
                print(f"  DRY RUN - Would send analysis to: {summary_to}")
            else:
                if email_sender.send_email(
                    to_email=summary_to, subject=analysis["subject"],
                    body=analysis["body"], is_html=analysis.get("is_html", False),
                    attachments=email_data.get("attachments", []),
                ):
                    print(f"  Analysis sent to {summary_to}")
                else:
                    print(f"  Failed to send analysis email")
```

Y agregar los helpers usados:

```python
    def _eligible_rpa_mgas(self, evaluations, mga_list) -> set:
        """MGA-RPA habilitados que quedaron elegibles para esta submission."""
        eval_by_name = {ev.mga_name: ev for ev in evaluations}
        out = set()
        for m in mga_list:
            name = m["mga"]
            if name.upper() not in self.rpa_mgas:
                continue
            ev = eval_by_name.get(name)
            if ev is None or ev.eligible:   # sin reglas específicas = elegible para RPA
                out.add(name.upper())
        return out

    def _effective_date_from_subject(self, subject: str):
        import re
        m = re.search(r'[Ee]ffective\s+date[:\s]+(\d{1,2}/\d{1,2}/\d{4})', subject)
        return m.group(1) if m else None
```

(El bloque viejo `_dispatch_to_progressive` y la rama `if mga_name.upper()=="PROGRESSIVE"` en `_dispatch_to_mgas` quedan, pero ya NO se usan para iniciar el quote — el quote ahora lo corre el worker. Para evitar doble cotización: en `_dispatch_to_mgas`, saltear los MGA que están en `self.rpa_mgas` — agregar al inicio del loop `if mga_name.upper() in self.rpa_mgas: continue`. El dispatch sólo maneja MGAs-por-email.)

- [ ] **Step 4: Evitar doble-cotización en `_dispatch_to_mgas`**

En `_dispatch_to_mgas`, dentro del `for mga in mga_list_eligible:`, al inicio del cuerpo del loop reemplazar la rama Progressive por un skip de TODOS los MGA-RPA (el quote lo hace el worker):

```python
            mga_name = mga['mga']
            # Los MGA-RPA (Progressive, GEICO) los cotiza el QuoteWorker desde la
            # cola — NO se dispatchan por email acá.
            if mga_name.upper() in self.rpa_mgas:
                continue
            print(f"\n  Processing MGA: {mga_name}")
```

(Borrar el viejo `if mga_name.upper() == "PROGRESSIVE": self._dispatch_to_progressive(...)`.)

- [ ] **Step 5: gitignore**

Agregar a `.gitignore` (si no están ya cubiertos por `data/`):

```
data/quote_queue.db
data/quote_queue.db-wal
data/quote_queue.db-shm
data/submissions/
```

- [ ] **Step 6: pyflakes + smoke import**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pyflakes workflow_orchestrator.py`
Expected: sin salida.

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -c "import workflow_orchestrator"`
Expected: sin error de import.

- [ ] **Step 7: Commit**

```bash
git add workflow_orchestrator.py .gitignore
git commit -m "feat(orchestrator): encolar cotizacion RPA + diferir el correo de analisis al worker"
```

---

## Task 5: `runner.py` — entrypoint con monitor de inbox + workers por MGA

**Files:**
- Create: `runner.py`

> **Validación:** entrypoint de proceso — se valida LIVE arrancándolo. Confirmá la firma `GEICOClient.create_quote(profile, effective_date=None)` en `modules/geico/client.py` antes de cablear el worker de GEICO.

- [ ] **Step 1: Implementar el runner**

Create `runner.py`:

```python
"""
Runner del pipeline RPA: productor (monitor de inbox) + consumidores (un
QuoteWorker por MGA, en hilos). La cola SQLite es durable, así que un reinicio
retoma donde quedó; al arrancar se llama reclaim_stale() para recuperar jobs
colgados por un crash a mitad de cotización.

Uso:
    <python> runner.py
"""

import threading
import time

from workflow_orchestrator import (
    QuoteWorkflowOrchestrator, QUOTE_DB_PATH,
)
from modules.quote_queue.store import QuoteQueueStore
from modules.quote_queue.worker import QuoteWorker
from modules.email_sender import EmailSender
from modules.progressive.client import ProgressiveClient


# create_quote por MGA. GEICO se agrega sólo si el flag lo habilita.
def _create_quote_fns(rpa_mgas: set) -> dict:
    fns = {"PROGRESSIVE": ProgressiveClient.create_quote}
    if "GEICO" in rpa_mgas:
        from modules.geico.client import GEICOClient
        fns["GEICO"] = GEICOClient.create_quote
    return fns


def _worker_loop(worker: QuoteWorker, stop: threading.Event, idle_sleep: float = 5.0):
    while not stop.is_set():
        try:
            took = worker.run_once()
        except Exception as e:
            print(f"    [worker:{worker.mga}] loop error: {e}")
            took = False
        if not took:
            stop.wait(idle_sleep)  # cola vacía → dormir un poco


def main():
    orch = QuoteWorkflowOrchestrator()
    store = QuoteQueueStore(QUOTE_DB_PATH)

    reclaimed = store.reclaim_stale()
    if reclaimed:
        print(f"  [runner] reclaim_stale: {reclaimed} job(s) colgado(s) → pending")

    sender = EmailSender(orch.email_address, orch.email_password)
    create_fns = _create_quote_fns(orch.rpa_mgas)

    stop = threading.Event()
    threads = []
    for mga in sorted(orch.rpa_mgas):
        worker = QuoteWorker(mga, store, create_quote=create_fns[mga], email_sender=sender)
        t = threading.Thread(target=_worker_loop, args=(worker, stop), name=f"worker-{mga}", daemon=True)
        t.start()
        threads.append(t)
        print(f"  [runner] worker {mga} arrancado")

    # El monitor de inbox corre en el hilo principal (bloqueante).
    try:
        orch.start_monitoring(check_interval=60)
    except KeyboardInterrupt:
        print("\n  [runner] deteniendo workers...")
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=5)
        store.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: pyflakes + smoke import**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pyflakes runner.py`
Expected: sin salida.

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -c "import runner"`
Expected: sin error de import.

- [ ] **Step 3: Suite completa (regresión) + commit**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/quote_queue/ tests/progressive/ tests/geico/ tests/test_analysis_email_rpa_section.py -q`
Expected: PASS (todo lo nuevo + sin romper Progressive).

```bash
git add runner.py
git commit -m "feat(runner): entrypoint con monitor de inbox + QuoteWorker por MGA (reclaim_stale al arrancar)"
```

---

## Self-review checklist (correr al final, antes de ejecutar)

- Cobertura del spec: catálogo humanizado al agente ✓ (T1); sección RPA en el correo ✓ (T1/T2); worker por MGA serial + completion + anti doble-envío ✓ (T3); encolado + diferir correo + idempotencia USDOT ✓ (T4); runner con reclaim_stale + GEICO tras flag ✓ (T5); enviar al instante si no hay RPA ✓ (T4).
- Sin placeholders: cada step trae código real + comando + salida esperada.
- Consistencia de tipos: `classify_result` → `(status:str, reason:str, premium, quote_number, pdf_path)`; `RpaQuoteOutcome(mga,status,reason,premium,pdf_path,detail)`; `QuoteWorker(mga, store, create_quote, email_sender)`; `EmailSender.send_email(to_email,subject,body,attachments,is_html)`. El worker guarda el reason code en el campo `error` del job (convención: el texto humano se deriva de (status, reason); el detalle crudo va a logs/screenshot).

## Decisiones / riesgos

- **`error` lleva el reason code** (ok/needs_ssn/...), no el traceback crudo — el detalle técnico va a `print`/logs y `screenshot_path`. Coherente con "lo técnico a logs, lo humano al correo".
- **`classify_result` de Progressive** depende de tokens de texto del error; verificar contra strings reales en validación LIVE (default seguro = `failed/error`).
- **Doble-cotización evitada**: `_dispatch_to_mgas` saltea los MGA-RPA; el quote lo corre sólo el worker.
- **`_pending_approvals`** (gate APROBAR → MGAs-por-email) queda intacto y en memoria — su reemplazo durable es trabajo futuro, fuera de alcance.
- **Adjuntos originales a disco** (`data/submissions/<id>/`) en vez de bytes en la DB — mantiene `context_json` chico. Limpieza de esa carpeta = trabajo futuro.

## Errata (refinamientos hechos durante la ejecución)

1. **Task 4 — NO borrar el bloque Step 6 (`_pending_approvals`).** El reemplazo en `_process_submission` cambia SOLO el envío del análisis (Step 5): build con marcador/“” + rama encolar-o-enviar. El bloque "Step 8: auto vs manual `_pending_approvals`" que sigue queda INTACTO (el gate APROBAR → MGAs-por-email no se toca).
2. **Task 4 — fallback anti-pérdida.** Si todos los MGA-RPA elegibles caen en el rate-limit (`recently_quoted >= 3`), `queued` queda vacío y nadie mandaría el correo. Fix: si `not queued`, enviar el análisis al instante (con `RPA_SECTION_MARKER` reemplazado por “”). Commit `6f95d61`.
3. **Task 5 — guard en el runner.** `for mga in rpa_mgas:` saltea con WARNING si `mga not in create_fns` (evita KeyError en startup ante un MGA desconocido). Commit `6a16b28`.

**Ejecutado 2026-06-16, subagent-driven:** commits e4c8d70..6a16b28. Suite: 464 passed, 2 failed (las 2 pre-existentes de rule_engine). pyflakes limpio en `modules/quote_queue/` + `runner.py`. Validación LIVE (correo real → quote → correo con PDF) y tuning de tokens de `classify_result` para Progressive = pendiente.
