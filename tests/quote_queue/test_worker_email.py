"""El worker manda el análisis en el hilo (CC) con los PDFs y etiqueta."""
import json
from unittest.mock import MagicMock

from modules.quote_queue.store import QuoteQueueStore
from modules.quote_queue.worker import QuoteWorker
from modules.quote_queue.models import JobStatus


def _store(tmp_path):
    return QuoteQueueStore(tmp_path / "q.db")


def test_worker_sends_threaded_with_pdfs_and_labels(tmp_path):
    store = _store(tmp_path)
    sub = "sub-1"
    # Contexto con los campos nuevos (los pone el orquestador).
    store.save_submission_context(sub, json.dumps({
        "recipient": "quotes@h2oins.com",
        "cc": "programacion@h2oins.com",
        "thread_id": "thread-1",
        "in_reply_to": "<orig@mail>",
        "message_id": "m-orig",
        "subject": "[ANALISIS] ACME",
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
    assert kwargs["to"] == "quotes@h2oins.com"
    assert kwargs["cc"] == "programacion@h2oins.com"
    assert kwargs["thread_id"] == "thread-1"
    assert kwargs["in_reply_to"] == "<orig@mail>"
    assert "data/quote_pdfs/g.pdf" in kwargs["attachments"]
    gmail.add_label.assert_called_once_with("m-orig", "Cotizado-Bot")


def _ctx(**over):
    base = {
        "recipient": "quotes@h2oins.com", "cc": None,
        "thread_id": None, "in_reply_to": None, "message_id": None,
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
