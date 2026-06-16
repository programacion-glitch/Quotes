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


def _ctx():
    return json.dumps({
        "recipient": "agente@h2o.com",
        "subject": "[ANALISIS] Submission // RYD",
        "body_html": f"<html>ANALISIS {RPA_SECTION_MARKER} FIN</html>",
        "attachment_paths": [],
    })


def test_email_not_sent_until_all_terminal(store):
    store.save_submission_context("sub-1", _ctx())
    j1 = store.enqueue("sub-1", "PROGRESSIVE", "{}", None, "111")
    store.enqueue("sub-1", "GEICO", "{}", None, "111")
    store.claim_next("PROGRESSIVE")
    store.mark_terminal(j1, JobStatus.QUOTED, premium="$44,621", pdf_path="p.pdf", error="ok")

    sender = FakeSender()
    worker = QuoteWorker("PROGRESSIVE", store, create_quote=lambda *a, **k: None,
                         email_sender=sender)
    worker.maybe_send_submission_email("sub-1")
    assert sender.sent == []


def test_email_sent_once_when_all_terminal_with_marker_replaced(store):
    store.save_submission_context("sub-1", _ctx())
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
    assert RPA_SECTION_MARKER not in msg["body"]
    assert "$44,621" in msg["body"] and "SSN" in msg["body"]
    assert "p.pdf" in msg["attachments"]

    worker.maybe_send_submission_email("sub-1")
    assert len(sender.sent) == 1
