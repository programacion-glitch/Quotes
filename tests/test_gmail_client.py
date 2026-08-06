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


def test_fetch_unread_only_false_omite_is_unread():
    """unread_only=False: el dedup es del caller (seen_emails + corte) —
    un correo que ventas leyó antes que el bot NO se pierde."""
    svc = _fake_service_with_messages([])
    client = GmailClient(service=svc)
    client.fetch_unread("Submission", unread_only=False)
    _, kwargs = svc.users().messages().list.call_args
    assert "is:unread" not in kwargs["q"]
    assert 'subject:"Submission"' in kwargs["q"]


def test_fetch_metadata_filter_evita_la_descarga_completa():
    """Lo rechazado por metadata_filter (headers) nunca se baja entero."""
    svc = MagicMock()
    svc.users().messages().list().execute.return_value = {
        "messages": [{"id": "m1"}, {"id": "m2"}]
    }
    full = {
        "m1": _msg("m1", "Re: Submission A", "Ana <ana@h2oins.com>", "uno"),
        "m2": _msg("m2", "Submission B", "Bea <bea@h2oins.com>", "dos"),
    }
    gets = []

    def _get(userId=None, id=None, format=None, metadataHeaders=None):
        gets.append((id, format))
        call = MagicMock()
        call.execute.return_value = full[id]  # headers presentes en ambos formatos
        return call

    svc.users().messages().get.side_effect = _get
    client = GmailClient(service=svc)
    rechazados = []

    def _filtro(msg_id, sender_email, subject):
        if subject.lower().startswith("re:"):
            rechazados.append((msg_id, sender_email))
            return False
        return True

    emails = client.fetch_unread("Submission", unread_only=False,
                                 metadata_filter=_filtro)

    assert [e["id"] for e in emails] == ["m2"]
    assert rechazados == [("m1", "ana@h2oins.com")]
    # m1: SOLO metadata; m2: metadata + full.
    assert ("m1", "full") not in gets
    assert ("m1", "metadata") in gets
    assert ("m2", "full") in gets


def test_fetch_pagina_hasta_agotar_next_page_token():
    """Sin is:unread el backlog puede exceder una página: se pagina."""
    svc = MagicMock()
    pages = [
        {"messages": [{"id": "m1"}], "nextPageToken": "t2"},
        {"messages": [{"id": "m2"}]},
    ]
    calls = []

    def _list(**kw):
        calls.append(kw)
        call = MagicMock()
        call.execute.return_value = pages[len(calls) - 1]
        return call

    svc.users().messages().list.side_effect = _list
    by_id = {
        "m1": _msg("m1", "Submission A", "a@x.com", "uno"),
        "m2": _msg("m2", "Submission B", "b@x.com", "dos"),
    }

    def _get(userId=None, id=None, format=None, metadataHeaders=None):
        call = MagicMock()
        call.execute.return_value = by_id[id]
        return call

    svc.users().messages().get.side_effect = _get
    client = GmailClient(service=svc)

    emails = client.fetch_unread("Submission", unread_only=False)

    assert [e["id"] for e in emails] == ["m1", "m2"]
    assert "pageToken" not in calls[0]
    assert calls[1]["pageToken"] == "t2"


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


def test_add_label_creates_if_missing_then_modifies():
    svc = MagicMock()
    svc.users().labels().list().execute.return_value = {"labels": []}
    svc.users().labels().create().execute.return_value = {"id": "Label_99"}
    modified = {}

    def _modify(userId=None, id=None, body=None):
        modified["id"] = id
        modified["body"] = body
        call = MagicMock()
        call.execute.return_value = {}
        return call

    svc.users().messages().modify.side_effect = _modify
    client = GmailClient(service=svc)
    client.add_label("m1", "Cotizado-Bot")
    assert modified["id"] == "m1"
    assert modified["body"] == {"addLabelIds": ["Label_99"]}


def test_add_label_reuses_existing():
    svc = MagicMock()
    svc.users().labels().list().execute.return_value = {
        "labels": [{"id": "Label_7", "name": "Cotizado-Bot"}]
    }
    modified = {}
    svc.users().messages().modify.side_effect = (
        lambda userId=None, id=None, body=None: _ret(modified, id, body)
    )
    client = GmailClient(service=svc)
    client.add_label("m2", "Cotizado-Bot")
    assert modified["body"] == {"addLabelIds": ["Label_7"]}
    svc.users().labels().create.assert_not_called()


def test_mark_read_removes_unread():
    svc = MagicMock()
    removed = {}
    svc.users().messages().modify.side_effect = (
        lambda userId=None, id=None, body=None: _ret(removed, id, body)
    )
    client = GmailClient(service=svc)
    client.mark_read("m3")
    assert removed["body"] == {"removeLabelIds": ["UNREAD"]}


def _ret(store, id, body):
    store["id"] = id
    store["body"] = body
    call = MagicMock()
    call.execute.return_value = {}
    return call


def test_fetch_unread_includes_after_when_given():
    svc = _fake_service_with_messages([])
    client = GmailClient(service=svc)
    client.fetch_unread("Submission", after_epoch=1750000000)
    _, kwargs = svc.users().messages().list.call_args
    assert "after:1750000000" in kwargs["q"]
    assert "is:unread" in kwargs["q"]


def test_fetch_unread_excludes_label_when_given():
    svc = _fake_service_with_messages([])
    client = GmailClient(service=svc)
    client.fetch_unread("Submission", exclude_label="Procesado-Bot")
    _, kwargs = svc.users().messages().list.call_args
    assert '-label:"Procesado-Bot"' in kwargs["q"]
    assert "is:unread" in kwargs["q"]


def test_fetch_unread_includes_from_allowlist_when_given():
    svc = _fake_service_with_messages([])
    client = GmailClient(service=svc)
    client.fetch_unread("Submission",
                        from_allowlist=["a@h2oins.com", "b@h2oins.com"])
    _, kwargs = svc.users().messages().list.call_args
    assert "from:(a@h2oins.com OR b@h2oins.com)" in kwargs["q"]
    assert "is:unread" in kwargs["q"]


def test_fetch_unread_no_from_clause_when_allowlist_absent():
    svc = _fake_service_with_messages([])
    client = GmailClient(service=svc)
    client.fetch_unread("Submission")
    _, kwargs = svc.users().messages().list.call_args
    assert "from:(" not in kwargs["q"]


def test_fetch_unread_skip_message_id_evita_el_get(client=None):
    """skip_message_id filtra por ID ANTES de messages.get: el correo ya
    visto no se vuelve a descargar (cuerpo + adjuntos)."""
    svc = _fake_service_with_messages([
        _msg("m1", "Submission A", "a@x.com", "uno"),
        _msg("m2", "Submission B", "b@x.com", "dos"),
    ])
    client = GmailClient.__new__(GmailClient)
    client._svc = lambda: svc

    emails = client.fetch_unread("Submission", skip_message_id=lambda i: i == "m1")

    assert [e["id"] for e in emails] == ["m2"]
    # messages.get solo se llamó para m2
    called_ids = [kw["id"] for _, kw in svc.users().messages().get.call_args_list if kw]
    assert "m1" not in called_ids
