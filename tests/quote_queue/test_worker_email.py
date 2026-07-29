"""El worker manda el análisis como correo NUEVO (sin hilo, sin CC, sin
etiqueta) con los PDFs adjuntos."""
import json
from unittest.mock import MagicMock

from modules import decision_ledger
from modules.quote_queue.store import QuoteQueueStore
from modules.quote_queue.worker import QuoteWorker
from modules.quote_queue.models import JobStatus


def _store(tmp_path):
    return QuoteQueueStore(tmp_path / "q.db")


def test_worker_sends_new_email_with_pdfs_no_label(tmp_path):
    store = _store(tmp_path)
    sub = "sub-1"
    # Contexto reducido (lo pone el orquestador): sin cc/thread_id/message_id.
    store.save_submission_context(sub, json.dumps({
        "recipient": "dianarubio@h2oins.com",
        "subject": "[ANALISIS] ACME LLC | ACME",
        "body_html": "<!--RPA_QUOTES_SECTION-->",
        "attachment_paths": [],
    }))
    jid = store.enqueue(sub, "GEICO", "{}", None, "123")
    store.mark_terminal(jid, JobStatus.QUOTED, premium="$10,000",
                        quote_number="Q1", pdf_path="data/quote_pdfs/g.pdf")

    gmail = MagicMock()
    gmail.send_threaded.return_value = True
    worker = QuoteWorker("GEICO", store, create_quote=lambda *a: None, gmail=gmail)

    sent = worker.maybe_send_submission_email(sub)

    assert sent is True
    _, kwargs = gmail.send_threaded.call_args
    assert kwargs["to"] == "dianarubio@h2oins.com"
    assert "cc" not in kwargs
    assert "thread_id" not in kwargs
    assert "in_reply_to" not in kwargs
    assert "data/quote_pdfs/g.pdf" in kwargs["attachments"]
    gmail.add_label.assert_not_called()


def test_worker_attaches_decline_screenshot_as_evidence(tmp_path):
    """Diana 2026-06-25: cuando un MGA web declina, adjuntar el screenshot de
    evidencia. Un job no-quoted con screenshot_path se adjunta; uno quoted NO
    (ese tiene su PDF)."""
    store = _store(tmp_path)
    sub = "sub-ev"
    store.save_submission_context(sub, json.dumps({
        "recipient": "quotes@h2oins.com",
        "subject": "[ANALISIS]", "body_html": "<!--RPA_QUOTES_SECTION-->",
        "attachment_paths": [],
    }))
    declined = store.enqueue(sub, "GEICO", "{}", None, "1")
    store.mark_terminal(declined, JobStatus.HALTED, error="not_eligible",
                        screenshot_path="logs/geico_not_eligible.png")
    quoted = store.enqueue(sub, "PROGRESSIVE", "{}", None, "1")
    store.mark_terminal(quoted, JobStatus.QUOTED, premium="$1", quote_number="Q",
                        pdf_path="data/quote_pdfs/p.pdf",
                        screenshot_path="logs/progressive_final.png")

    gmail = MagicMock()
    gmail.send_threaded.return_value = True
    worker = QuoteWorker("GEICO", store, create_quote=lambda *a: None, gmail=gmail)

    assert worker.maybe_send_submission_email(sub) is True
    _, kwargs = gmail.send_threaded.call_args
    atts = kwargs["attachments"]
    assert "logs/geico_not_eligible.png" in atts, "evidencia de decline adjunta"
    assert "data/quote_pdfs/p.pdf" in atts, "PDF de la cotización exitosa adjunto"
    assert "logs/progressive_final.png" not in atts, \
        "el screenshot de un job EXITOSO no se adjunta (ya tiene su PDF)"


def _ctx(**over):
    base = {
        "recipient": "quotes@h2oins.com",
        "subject": "[ANALISIS]", "body_html": "<!--RPA_QUOTES_SECTION-->",
        "attachment_paths": [],
    }
    base.update(over)
    return json.dumps(base)


def test_not_sent_until_all_siblings_terminal(tmp_path):
    """Con un job aún pending, NO se manda el correo (espera a todos los MGAs)."""
    store = _store(tmp_path)
    sub = "sub-2"
    store.save_submission_context(sub, _ctx())
    g = store.enqueue(sub, "GEICO", "{}", None, "1")
    store.enqueue(sub, "PROGRESSIVE", "{}", None, "1")  # sigue pending
    store.mark_terminal(g, JobStatus.QUOTED, premium="$1", quote_number="Q",
                        pdf_path=None)

    gmail = MagicMock()
    worker = QuoteWorker("GEICO", store, create_quote=lambda *a: None, gmail=gmail)

    assert worker.maybe_send_submission_email(sub) is False
    gmail.send_threaded.assert_not_called()


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
    store = _store(tmp_path)
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


def test_run_once_captura_decisiones_en_mark_terminal(tmp_path):
    """Lo que el bot registró en el decision_ledger durante create_quote queda
    guardado en el job terminal (decisions_json) para el correo de análisis."""
    store = _store(tmp_path)
    store.enqueue("sub-dec", "PROGRESSIVE", "{}", None, "1")

    class _Result:
        success = True
        price = None
        pdf_path = None

    def fake_create_quote(profile, effective_date):
        decision_ledger.start_run("PROGRESSIVE")
        decision_ledger.record("Roadside", "Yes", source="RULE", rule_id="R-1")
        return _Result()

    gmail = MagicMock()
    worker = QuoteWorker("PROGRESSIVE", store, create_quote=fake_create_quote,
                         gmail=gmail)

    assert worker.run_once() is True

    (job,) = store.get_jobs("sub-dec")
    assert job.decisions_json is not None
    decisions = json.loads(job.decisions_json)
    assert len(decisions) == 1
    assert decisions[0]["field"] == "Roadside"
    assert decisions[0]["chosen"] == "Yes"
    assert decisions[0]["rule_id"] == "R-1"


def test_run_once_captura_decisiones_aunque_create_quote_truene(tmp_path):
    """Si create_quote truena a medio camino, lo que alcanzó a registrarse
    antes del crash igual se guarda (sirve de diagnóstico)."""
    store = _store(tmp_path)
    store.enqueue("sub-crash", "GEICO", "{}", None, "1")

    def crashing_create_quote(profile, effective_date):
        decision_ledger.start_run("GEICO")
        decision_ledger.record("VIN", "match", source="MATCHED")
        raise RuntimeError("boom")

    gmail = MagicMock()
    worker = QuoteWorker("GEICO", store, create_quote=crashing_create_quote,
                         gmail=gmail)

    assert worker.run_once() is True

    (job,) = store.get_jobs("sub-crash")
    assert job.decisions_json is not None
    decisions = json.loads(job.decisions_json)
    assert decisions[0]["field"] == "VIN"
    assert decisions[0]["chosen"] == "match"


def test_sent_once_under_contention(tmp_path):
    """Con todos terminales, el correo sale UNA sola vez (idempotencia de la
    carrera Progressive+GEICO terminando juntos)."""
    store = _store(tmp_path)
    sub = "sub-3"
    store.save_submission_context(sub, _ctx())
    g = store.enqueue(sub, "GEICO", "{}", None, "1")
    p = store.enqueue(sub, "PROGRESSIVE", "{}", None, "1")
    store.mark_terminal(g, JobStatus.QUOTED, premium="$1", quote_number="Q",
                        pdf_path=None)
    store.mark_terminal(p, JobStatus.FAILED, error="error")

    gmail = MagicMock()
    gmail.send_threaded.return_value = True
    worker = QuoteWorker("GEICO", store, create_quote=lambda *a: None, gmail=gmail)

    assert worker.maybe_send_submission_email(sub) is True    # gana
    assert worker.maybe_send_submission_email(sub) is False   # ya enviado
    assert gmail.send_threaded.call_count == 1
