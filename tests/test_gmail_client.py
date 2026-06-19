"""Unit del GmailClient (Gmail API mockeada — no toca la red)."""
from unittest.mock import MagicMock

from modules.gmail_client import GmailClient


def _fake_service_with_messages(messages):
    """Servicio Gmail falso: list() devuelve refs, get(id) devuelve el msg dict."""
    svc = MagicMock()
    by_id = {m["id"]: m for m in messages}
    svc.users().messages().list().execute.return_value = {
        "messages": [{"id": m["id"]} for m in messages]
    }

    def _get(userId=None, id=None, format=None):
        call = MagicMock()
        call.execute.return_value = by_id[id]
        return call

    svc.users().messages().get.side_effect = _get
    return svc


def _msg(mid, subject, frm, body_text, msgid="<x@mail>"):
    import base64
    b64 = base64.urlsafe_b64encode(body_text.encode()).decode()
    return {
        "id": mid,
        "threadId": f"thread-{mid}",
        "payload": {
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": frm},
                {"name": "Message-ID", "value": msgid},
                {"name": "Date", "value": "Mon, 1 Jan 2026 00:00:00 -0000"},
            ],
            "mimeType": "text/plain",
            "body": {"data": b64},
        },
    }


def test_fetch_unread_maps_fields():
    svc = _fake_service_with_messages([
        _msg("m1", "Submission ACME", "Ana <ana@x.com>", "cuerpo de prueba")
    ])
    client = GmailClient(service=svc)
    emails = client.fetch_unread("Submission")
    assert len(emails) == 1
    e = emails[0]
    assert e["id"] == "m1"
    assert e["thread_id"] == "thread-m1"
    assert e["message_id"] == "<x@mail>"
    assert e["subject"] == "Submission ACME"
    assert e["sender_email"] == "ana@x.com"
    assert e["sender_name"] == "Ana"
    assert "cuerpo de prueba" in e["body"]
    assert e["attachments"] == []


def test_fetch_unread_query_includes_unread_and_subject():
    svc = _fake_service_with_messages([])
    client = GmailClient(service=svc)
    client.fetch_unread("Submission")
    # La última llamada a list() debe llevar is:unread + subject.
    _, kwargs = svc.users().messages().list.call_args
    assert "is:unread" in kwargs["q"]
    assert "Submission" in kwargs["q"]


def test_send_threaded_builds_raw_with_cc_and_thread():
    svc = MagicMock()
    sent = {}

    def _send(userId=None, body=None):
        sent.update(body)
        call = MagicMock()
        call.execute.return_value = {"id": "sent1"}
        return call

    svc.users().messages().send.side_effect = _send
    client = GmailClient(service=svc)

    ok = client.send_threaded(
        to="quotes@h2oins.com", cc="programacion@h2oins.com",
        subject="[ANALISIS] ACME", body="<b>hola</b>", is_html=True,
        thread_id="thread-m1", in_reply_to="<x@mail>",
        attachments=[{"filename": "p.pdf", "data": b"%PDF-1.4 x"}],
    )
    assert ok is True
    assert sent["threadId"] == "thread-m1"
    import base64
    raw = base64.urlsafe_b64decode(sent["raw"].encode()).decode("utf-8", "replace")
    assert "To: quotes@h2oins.com" in raw
    assert "Cc: programacion@h2oins.com" in raw
    assert "In-Reply-To: <x@mail>" in raw
    assert "References: <x@mail>" in raw
    assert "p.pdf" in raw
