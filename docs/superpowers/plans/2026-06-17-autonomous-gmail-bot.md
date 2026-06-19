# Bot autónomo vía Gmail API — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dejar el bot corriendo autónomo en este host: monitorea `quotes@h2oins.com` por la Gmail API, analiza+cotiza (Progressive+GEICO por la cola RPA), y responde EN EL HILO a `quotes@h2oins.com` con CC a `programacion@h2oins.com`, PDFs de cada cotización adjuntos, y etiqueta el correo original `Cotizado-Bot`.

**Architecture:** Un módulo nuevo `modules/gmail_client.py` reemplaza el transporte IMAP/SMTP (bloqueado en este host) por la Gmail API (HTTPS), reusando el OAuth de `data/token.json`. Un `modules/quote_queue/runner.py` nuevo levanta el monitor del inbox (productor) + un worker-thread por MGA (consumidores). El orquestador y el worker de la cola se migran al `GmailClient` con threading + CC + etiqueta.

**Tech Stack:** Python 3.12, Gmail REST API (`google-api-python-client`, `google-auth`), SQLite (cola ya existente), Playwright (RPA ya existente). Python intérprete: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe`.

**Spec:** `docs/superpowers/specs/2026-06-17-autonomous-gmail-bot-design.md`

**Notas para el ejecutor:**
- Intérprete: usar SIEMPRE `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe` (no `python` a secas).
- Tras cada tarea: correr `pyflakes` sobre los archivos tocados (atrapa NameErrors que `py_compile` no ve): `... -m pyflakes modules/gmail_client.py`.
- Tests NO tocan la red: el servicio Gmail se inyecta mockeado (`GmailClient(service=fake)`).
- Commits frecuentes. Branch actual: `progressive-basepage-hardening`. Mensajes de commit terminan con `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- NUNCA commitear `data/token.json`, `data/credentials.json`, PDFs de clientes ni `.env`.

---

## File Structure

| Archivo | Responsabilidad |
|---|---|
| `modules/gmail_client.py` (crear) | Transporte Gmail API: `fetch_unread`, `send_threaded`, `add_label`, `mark_read`. Auth reusa `data/token.json`. |
| `modules/quote_queue/runner.py` (crear) | Entrypoint del bot: `reclaim_stale` + loop monitor (productor) + N worker-threads (uno por MGA). |
| `modules/quote_queue/worker.py` (modificar) | Usar `GmailClient.send_threaded` (hilo+CC) + `add_label` en vez de `send_email` plano. |
| `workflow_orchestrator.py` (modificar) | Construir `GmailClient`; guardar `thread_id`/`message_id`/`cc` en el contexto; recipients = analysis_to/cc; `_submission_id` desde `message_id`; caminos inline (sin-RPA/rate-limit/not-found) → `send_threaded` + label. |
| `config/settings.yaml` (modificar) | `rule_engine.geico_queue_enabled`, `email.analysis_to`, `email.analysis_cc`, `email.label_processed`. |
| `.env` (modificar, NO commitear) | `GEICO_QUEUE_ENABLED=true`, `EMAIL_ANALYSIS_TO`, `EMAIL_ANALYSIS_CC`. |
| `tests/test_gmail_client.py` (crear) | Unit del GmailClient con servicio mockeado. |
| `tests/quote_queue/test_runner.py` (crear) | Unit del runner con FakeGmailClient + FakeMGAClient. |
| `tests/quote_queue/test_worker_email.py` (crear) | Worker arma send_threaded + label con el contexto extendido. |

---

## Task 1: Config — claves nuevas en settings.yaml

**Files:**
- Modify: `config/settings.yaml` (sección `email:` ~L78-114 y `rule_engine:` ~L177-191)

- [ ] **Step 1: Agregar claves a `config/settings.yaml`**

En la sección `email:`, después de `monitoring:` (tras la línea `check_interval_seconds: 60`), agregar:

```yaml
  # Análisis autónomo (Gmail API): destino y etiqueta
  analysis_to: "${EMAIL_ANALYSIS_TO}"      # default quotes@h2oins.com (.env)
  analysis_cc: "${EMAIL_ANALYSIS_CC}"      # programacion@h2oins.com (.env)
  label_processed: "Cotizado-Bot"          # etiqueta al correo original
```

En la sección `rule_engine:`, después de `confirmation_keyword: "APROBAR"`, agregar:

```yaml
  # Encender GEICO en la cola RPA (Progressive siempre ON)
  geico_queue_enabled: true
```

- [ ] **Step 2: Agregar variables a `.env`** (NO commitear)

Agregar al final de `.env`:

```
# Bot autónomo Gmail API
EMAIL_ANALYSIS_TO=quotes@h2oins.com
EMAIL_ANALYSIS_CC=programacion@h2oins.com
GEICO_QUEUE_ENABLED=true
```

- [ ] **Step 3: Verificar que la config carga**

Run:
```
C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -c "from modules.config_manager import get_config; c=get_config(); print(c.get('email.analysis_to'), c.get('email.analysis_cc'), c.get('email.label_processed'), c.get('rule_engine.geico_queue_enabled'))"
```
Expected: `quotes@h2oins.com programacion@h2oins.com Cotizado-Bot True`

- [ ] **Step 4: Commit**

```bash
git add config/settings.yaml
git commit -m "config(bot): claves del bot autonomo (analysis_to/cc, label, geico_queue_enabled)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```
(El `.env` NO se commitea.)

---

## Task 2: GmailClient — auth + fetch_unread

**Files:**
- Create: `modules/gmail_client.py`
- Test: `tests/test_gmail_client.py`

Patrón de auth: idéntico a `modules/gmail_api_otp_reader.py` (mismos `data/credentials.json` + `data/token.json`, scope `gmail.modify`). El servicio es inyectable para tests.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_gmail_client.py`:

```python
"""Unit del GmailClient (Gmail API mockeada — no toca la red)."""
from unittest.mock import MagicMock

import pytest

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
```

- [ ] **Step 2: Correr el test (debe fallar)**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/test_gmail_client.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'modules.gmail_client'`.

- [ ] **Step 3: Crear `modules/gmail_client.py` con auth + fetch_unread**

```python
"""
Gmail API client (HTTPS / 443) para el flujo principal del bot.

Reemplaza el transporte IMAP/SMTP (modules/email_receiver.py / email_sender.py),
bloqueado en este host por eScan/Acronis. Reusa el mismo OAuth que el OTP reader
(data/credentials.json + data/token.json, scope gmail.modify — que autoriza
leer, enviar y modificar etiquetas).

El `service` de Gmail es inyectable (para tests sin red).
"""

import base64
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_CREDENTIALS = _PROJECT_ROOT / "data" / "credentials.json"
_DEFAULT_TOKEN = _PROJECT_ROOT / "data" / "token.json"


class GmailClient:
    """Lee no-leídos, responde en hilo (con CC), etiqueta y marca leído."""

    def __init__(self, credentials_path=None, token_path=None, service=None):
        self.credentials_path = Path(credentials_path or _DEFAULT_CREDENTIALS)
        self.token_path = Path(token_path or _DEFAULT_TOKEN)
        self._service = service          # inyectable para tests
        self._label_ids: dict = {}       # cache nombre -> labelId

    # ---- auth ----

    def _load_credentials(self) -> Credentials:
        if not self.token_path.exists():
            raise RuntimeError(
                f"Gmail API token not found at {self.token_path}. Run "
                f"`python scripts/gmail_oauth_bootstrap.py` once."
            )
        creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                self.token_path.write_text(creds.to_json(), encoding="utf-8")
            else:
                raise RuntimeError(
                    f"Gmail API token at {self.token_path} invalid / no refresh "
                    f"token. Re-run scripts/gmail_oauth_bootstrap.py."
                )
        return creds

    def _svc(self):
        if self._service is None:
            self._service = build(
                "gmail", "v1", credentials=self._load_credentials(),
                cache_discovery=False,
            )
        return self._service

    # ---- recibir ----

    def fetch_unread(self, subject_filter: Optional[str] = None) -> List[dict]:
        """No-leídos que matchean el filtro de asunto, en el dict del flujo."""
        svc = self._svc()
        q = "is:unread"
        if subject_filter:
            q += f' subject:"{subject_filter}"'
        resp = (
            svc.users().messages()
            .list(userId="me", q=q, maxResults=25)
            .execute()
        )
        out = []
        for ref in resp.get("messages", []):
            msg = (
                svc.users().messages()
                .get(userId="me", id=ref["id"], format="full")
                .execute()
            )
            out.append(self._to_email_dict(svc, msg))
        return out

    @staticmethod
    def _header(payload: dict, name: str) -> str:
        for h in payload.get("headers", []):
            if h.get("name", "").lower() == name.lower():
                return h.get("value", "")
        return ""

    @staticmethod
    def _split_sender(from_header: str):
        if "<" in from_header and ">" in from_header:
            name = from_header.split("<")[0].strip().strip('"')
            addr = from_header.split("<")[1].split(">")[0].strip()
        else:
            name, addr = "", from_header.strip()
        return name, addr

    def _to_email_dict(self, svc, msg: dict) -> dict:
        payload = msg.get("payload", {})
        subject = self._header(payload, "Subject")
        from_header = self._header(payload, "From")
        message_id = self._header(payload, "Message-ID")
        sender_name, sender_email = self._split_sender(from_header)
        body, attachments = self._walk(svc, msg["id"], payload)
        return {
            "id": msg["id"],
            "thread_id": msg.get("threadId"),
            "message_id": message_id,
            "subject": subject,
            "sender_name": sender_name,
            "sender_email": sender_email,
            "from": from_header,
            "date": self._header(payload, "Date"),
            "body": body,
            "attachments": attachments,
            "raw_message": None,
        }

    def _walk(self, svc, msg_id: str, payload: dict):
        """Devuelve (body_text, attachments[]). HTML preferido sobre plain."""
        html, plain, atts = "", "", []

        def rec(part):
            nonlocal html, plain
            mime = part.get("mimeType", "")
            filename = part.get("filename") or ""
            body = part.get("body", {})
            if filename:  # adjunto
                data = body.get("data")
                if data is None and body.get("attachmentId"):
                    fetched = (
                        svc.users().messages().attachments()
                        .get(userId="me", messageId=msg_id,
                             id=body["attachmentId"]).execute()
                    )
                    data = fetched.get("data")
                if data:
                    atts.append({
                        "filename": filename,
                        "data": base64.urlsafe_b64decode(data.encode("utf-8")),
                        "content_type": mime,
                    })
            elif body.get("data"):
                decoded = base64.urlsafe_b64decode(
                    body["data"].encode("utf-8")
                ).decode("utf-8", errors="replace")
                if mime == "text/html":
                    html += decoded
                elif mime == "text/plain":
                    plain += decoded
            for sub in part.get("parts", []) or []:
                rec(sub)

        rec(payload)
        return (html or plain), atts
```

- [ ] **Step 4: Correr el test (debe pasar)**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/test_gmail_client.py -q`
Expected: 2 passed.

- [ ] **Step 5: pyflakes + commit**

```bash
C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pyflakes modules/gmail_client.py tests/test_gmail_client.py
git add modules/gmail_client.py tests/test_gmail_client.py
git commit -m "feat(gmail): GmailClient auth + fetch_unread (Gmail API, reemplaza IMAP)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: GmailClient — send_threaded

**Files:**
- Modify: `modules/gmail_client.py`
- Test: `tests/test_gmail_client.py`

- [ ] **Step 1: Agregar el test que falla**

Agregar a `tests/test_gmail_client.py`:

```python
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
```

- [ ] **Step 2: Correr (debe fallar)**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/test_gmail_client.py::test_send_threaded_builds_raw_with_cc_and_thread -q`
Expected: FAIL con `AttributeError: 'GmailClient' object has no attribute 'send_threaded'`.

- [ ] **Step 3: Implementar `send_threaded` (agregar a la clase)**

```python
    # ---- enviar ----

    def send_threaded(self, *, to: str, subject: str, body: str,
                      cc: Optional[str] = None, attachments=None,
                      is_html: bool = False, thread_id: Optional[str] = None,
                      in_reply_to: Optional[str] = None) -> bool:
        """Envía un correo (en el hilo si se da thread_id), con CC y adjuntos.

        attachments: lista de paths (str) o dicts {'filename','data'(bytes)}.
        """
        msg = MIMEMultipart()
        msg["To"] = to
        if cc:
            msg["Cc"] = cc
        msg["Subject"] = subject
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to
        msg.attach(MIMEText(body, "html" if is_html else "plain", "utf-8"))

        for att in (attachments or []):
            if isinstance(att, dict):
                self._attach_bytes(msg, att.get("filename", "attachment"),
                                   att.get("data", b""))
            else:
                self._attach_path(msg, att)

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        body_req = {"raw": raw}
        if thread_id:
            body_req["threadId"] = thread_id
        self._svc().users().messages().send(
            userId="me", body=body_req
        ).execute()
        print(f"    [Gmail] enviado -> {to}" + (f" (CC {cc})" if cc else ""))
        return True

    @staticmethod
    def _attach_bytes(msg, filename: str, data: bytes) -> None:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(data)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition",
                        f'attachment; filename="{filename}"')
        msg.attach(part)

    def _attach_path(self, msg, file_path: str) -> None:
        p = Path(file_path)
        if not p.exists():
            print(f"    [Gmail] adjunto no encontrado: {file_path}")
            return
        self._attach_bytes(msg, p.name, p.read_bytes())
```

- [ ] **Step 4: Correr (debe pasar)**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/test_gmail_client.py -q`
Expected: 3 passed.

- [ ] **Step 5: pyflakes + commit**

```bash
C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pyflakes modules/gmail_client.py
git add modules/gmail_client.py tests/test_gmail_client.py
git commit -m "feat(gmail): send_threaded (hilo + CC + adjuntos via Gmail API)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: GmailClient — add_label + mark_read

**Files:**
- Modify: `modules/gmail_client.py`
- Test: `tests/test_gmail_client.py`

- [ ] **Step 1: Agregar tests que fallan**

Agregar a `tests/test_gmail_client.py`:

```python
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
```

- [ ] **Step 2: Correr (debe fallar)**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/test_gmail_client.py -q`
Expected: FAIL (`add_label` / `mark_read` no existen).

- [ ] **Step 3: Implementar (agregar a la clase)**

```python
    # ---- etiquetas / leído ----

    def _label_id(self, svc, name: str) -> str:
        if name in self._label_ids:
            return self._label_ids[name]
        labels = (
            svc.users().labels().list(userId="me").execute().get("labels", [])
        )
        for lab in labels:
            if lab.get("name") == name:
                self._label_ids[name] = lab["id"]
                return lab["id"]
        created = svc.users().labels().create(
            userId="me",
            body={"name": name, "labelListVisibility": "labelShow",
                  "messageListVisibility": "show"},
        ).execute()
        self._label_ids[name] = created["id"]
        return created["id"]

    def add_label(self, message_id: str, label_name: str) -> None:
        svc = self._svc()
        lid = self._label_id(svc, label_name)
        svc.users().messages().modify(
            userId="me", id=message_id, body={"addLabelIds": [lid]}
        ).execute()

    def mark_read(self, message_id: str) -> None:
        self._svc().users().messages().modify(
            userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]}
        ).execute()
```

- [ ] **Step 4: Correr (debe pasar)**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/test_gmail_client.py -q`
Expected: 6 passed.

- [ ] **Step 5: pyflakes + commit**

```bash
C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pyflakes modules/gmail_client.py
git add modules/gmail_client.py tests/test_gmail_client.py
git commit -m "feat(gmail): add_label (create-if-missing) + mark_read

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Worker — enviar en hilo + etiquetar

**Files:**
- Modify: `modules/quote_queue/worker.py` (`QuoteWorker.__init__` y `maybe_send_submission_email`, ~L61-141)
- Test: `tests/quote_queue/test_worker_email.py`

El worker hoy recibe `email_sender` y llama `send_email(...)`. Pasa a recibir `gmail` (un GmailClient o doble) y usar `send_threaded` + `add_label`, leyendo del contexto los campos nuevos (`cc`, `thread_id`, `in_reply_to`, `message_id`). Mantiene el armado de adjuntos (BlueQuote + `j.pdf_path` de cada job) → **los PDFs van adjuntos**.

- [ ] **Step 1: Crear el test que falla**

Crear `tests/quote_queue/test_worker_email.py`:

```python
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
```

- [ ] **Step 2: Correr (debe fallar)**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/quote_queue/test_worker_email.py -q`
Expected: FAIL (`QuoteWorker.__init__() got an unexpected keyword argument 'gmail'`).

- [ ] **Step 3: Modificar `QuoteWorker.__init__`**

Reemplazar (en `modules/quote_queue/worker.py`):

```python
    def __init__(self, mga: str, store, create_quote: Callable, email_sender):
        self.mga = mga
        self.store = store
        self.create_quote = create_quote   # (profile, effective_date) -> QuoteResult
        self.email_sender = email_sender    # objeto con send_email(...)
```

por:

```python
    def __init__(self, mga: str, store, create_quote: Callable, gmail,
                 label_processed: str = "Cotizado-Bot"):
        self.mga = mga
        self.store = store
        self.create_quote = create_quote   # (profile, effective_date) -> QuoteResult
        self.gmail = gmail                  # GmailClient (send_threaded/add_label)
        self.label_processed = label_processed
```

- [ ] **Step 4: Modificar el envío en `maybe_send_submission_email`**

Reemplazar el bloque final (desde `body = ctx["body_html"].replace(...)` hasta el `return ok`):

```python
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

por:

```python
        body = ctx["body_html"].replace(RPA_SECTION_MARKER, render_rpa_section(outcomes))

        # Los PDFs de CADA cotización (j.pdf_path) van adjuntos, junto al
        # BlueQuote original.
        attachments = list(ctx.get("attachment_paths", []))
        attachments += [j.pdf_path for j in jobs if j.pdf_path]

        ok = self.gmail.send_threaded(
            to=ctx["recipient"],
            cc=ctx.get("cc"),
            subject=ctx["subject"],
            body=body,
            attachments=attachments,
            is_html=True,
            thread_id=ctx.get("thread_id"),
            in_reply_to=ctx.get("in_reply_to"),
        )
        if ok and ctx.get("message_id"):
            try:
                self.gmail.add_label(ctx["message_id"], self.label_processed)
            except Exception as e:  # etiquetar nunca debe tumbar el envío
                print(f"    [worker:{self.mga}] label warn: {e}")
        print(f"    [worker:{self.mga}] analysis email for {submission_id} "
              f"sent={ok} (outcomes={len(outcomes)})")
        return ok
```

- [ ] **Step 5: Correr (debe pasar) + suite de la cola**

Run:
```
C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/quote_queue/ -q
```
Expected: el test nuevo pasa. Si algún test viejo del worker construía `QuoteWorker(..., email_sender=...)`, actualizarlo a `gmail=` con un MagicMock cuyo `send_threaded` devuelve True (mismo patrón). Re-correr hasta verde.

- [ ] **Step 6: pyflakes + commit**

```bash
C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pyflakes modules/quote_queue/worker.py
git add modules/quote_queue/worker.py tests/quote_queue/test_worker_email.py
git commit -m "feat(queue): worker manda el analisis en hilo+CC con PDFs y etiqueta Cotizado-Bot

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Orquestador — migrar a GmailClient (contexto, recipients, _submission_id, inline)

**Files:**
- Modify: `workflow_orchestrator.py` (imports L18-19; `__init__` L51-103; `_process_submission` L226-296; `_submission_id` L472-481; `_send_not_found_email` L504-525; `start_monitoring` L527-548)

Cambios: construir un `GmailClient`; leer `analysis_to`/`analysis_cc`/`label_processed`; guardar `thread_id`/`message_id`/`cc` en el contexto; `_submission_id` desde `email_data["message_id"]`; los envíos inline (rate-limit, no-RPA, not-found) por `gmail.send_threaded` + etiqueta. El loop de monitoreo se mueve al runner (Task 7), así que `start_monitoring` se elimina/queda como no usado.

- [ ] **Step 1: Imports + `__init__`**

En `workflow_orchestrator.py`, reemplazar el import:

```python
from modules.email_receiver import EmailReceiver, extract_quote_body
from modules.email_sender import EmailSender
```

por:

```python
from modules.email_receiver import extract_quote_body  # solo el helper de texto
from modules.email_sender import EmailSender  # aún lo usa _dispatch_to_mgas (SMTP, fuera de alcance)
from modules.gmail_client import GmailClient
```

En `__init__`, después de `self.summary_email = ...` (L94), agregar:

```python
        # Transporte Gmail API (reemplaza IMAP/SMTP para el flujo de análisis).
        self.gmail = GmailClient()
        self.analysis_to = (self.config.get("email.analysis_to")
                            or self.summary_email)
        self.analysis_cc = self.config.get("email.analysis_cc") or None
        self.label_processed = self.config.get("email.label_processed",
                                               "Cotizado-Bot")
```

- [ ] **Step 2: `_submission_id` usa `message_id`**

Reemplazar el cuerpo de `_submission_id` (L472-481):

```python
    @staticmethod
    def _submission_id(email_data: dict, profile) -> str:
        """ID estable: Message-ID si existe, si no hash(subject+usdot)."""
        raw = email_data.get("raw_message")
        msg_id = raw.get("Message-ID") if raw else None
        if msg_id:
            return msg_id.strip()
        usdot = (profile.applicant.usdot or "").strip()
        subject = email_data.get("subject", "")
        return "sub-" + hashlib.sha1(f"{subject}|{usdot}".encode("utf-8")).hexdigest()[:16]
```

por:

```python
    @staticmethod
    def _submission_id(email_data: dict, profile) -> str:
        """ID estable: Message-ID (del dict de GmailClient) si existe, si no
        hash(subject+usdot)."""
        msg_id = (email_data.get("message_id") or "").strip()
        if msg_id:
            return msg_id
        usdot = (profile.applicant.usdot or "").strip()
        subject = email_data.get("subject", "")
        return "sub-" + hashlib.sha1(f"{subject}|{usdot}".encode("utf-8")).hexdigest()[:16]
```

- [ ] **Step 3: Contexto + envíos inline en `_process_submission`**

Reemplazar el bloque `summary_to = ...` + el `if eligible_rpa and not self.dry_run:` ... `else:` ... (L242-296) por:

```python
        analysis_to = self.analysis_to
        analysis_cc = self.analysis_cc

        if eligible_rpa and not self.dry_run:
            submission_id = self._submission_id(email_data, profile)
            attachment_paths = self._persist_attachments(submission_id, attachments)
            self.quote_store.save_submission_context(submission_id, json.dumps({
                "recipient": analysis_to,
                "cc": analysis_cc,
                "thread_id": email_data.get("thread_id"),
                "in_reply_to": email_data.get("message_id"),
                "message_id": email_data.get("id"),
                "subject": analysis["subject"],
                "body_html": analysis["body"],
                "attachment_paths": attachment_paths,
            }))
            eff_date = self._effective_date_from_subject(subject)
            now = time.time()
            queued = []
            for mga in sorted(eligible_rpa):
                if self.quote_store.recently_quoted(
                        mga, profile.applicant.usdot or "", now - 86400) >= 3:
                    print(f"  [queue] SKIP {mga}: USDOT cotizado >=3x en 24h")
                    continue
                self.quote_store.enqueue(
                    submission_id, mga, json.dumps(profile.to_dict()),
                    eff_date, profile.applicant.usdot or "")
                queued.append(mga)
            if not queued:
                # Todos rate-limited: mandar ahora (sin sección RPA) + etiquetar.
                body = analysis["body"].replace(RPA_SECTION_MARKER, "")
                self._send_analysis_now(email_data, analysis["subject"], body,
                                        attachments)
                print("  [queue] Nada encolado (rate-limit); análisis enviado ya")
            else:
                print(f"  [queue] Encolado {submission_id}: {queued} "
                      f"(el correo sale al terminar la cotización)")
        else:
            if self.dry_run:
                print(f"  DRY RUN - Would send analysis to: {analysis_to}")
            else:
                self._send_analysis_now(email_data, analysis["subject"],
                                        analysis["body"], attachments)
```

- [ ] **Step 4: Helper `_send_analysis_now` (envío inline en hilo + etiqueta)**

Agregar este método a la clase (p. ej. justo antes de `_send_not_found_email`):

```python
    def _send_analysis_now(self, email_data: dict, subject: str, body: str,
                           attachments: list) -> None:
        """Envía el análisis en el hilo (To analysis_to, CC analysis_cc) y
        etiqueta el correo original. Para los caminos sin cola (sin-RPA,
        rate-limited)."""
        ok = self.gmail.send_threaded(
            to=self.analysis_to,
            cc=self.analysis_cc,
            subject=subject,
            body=body,
            attachments=attachments,
            is_html=True,
            thread_id=email_data.get("thread_id"),
            in_reply_to=email_data.get("message_id"),
        )
        if ok and email_data.get("id"):
            try:
                self.gmail.add_label(email_data["id"], self.label_processed)
            except Exception as e:
                print(f"  label warn: {e}")
        print(f"  Analysis sent to {self.analysis_to} (ok={ok})")
```

Nota: `analysis["body"]` es HTML (build_analysis_email arma HTML); por eso `is_html=True`. Si en algún build `analysis.get("is_html")` fuera False, igual el HTML se renderiza bien; mantener `is_html=True` para el análisis.

- [ ] **Step 5: `_send_not_found_email` por Gmail + etiqueta**

Reemplazar el envío dentro de `_send_not_found_email` (el bloque `email_sender = EmailSender(...)` ... hasta el final):

```python
        email_sender = EmailSender(self.email_address, self.email_password)
        recipient = self.test_email_override or email_data.get('sender_email')

        if self.dry_run:
            print(f"  DRY RUN - Would send not-found email to: {recipient}")
        else:
            email_sender.send_email(
                to_email=recipient,
                subject=response['subject'],
                body=response['body']
            )
        print(f"{'='*60}\n")
```

por:

```python
        if self.dry_run:
            print(f"  DRY RUN - Would send not-found email")
        else:
            ok = self.gmail.send_threaded(
                to=self.analysis_to,
                cc=self.analysis_cc,
                subject=response['subject'],
                body=response['body'],
                is_html=False,
                thread_id=email_data.get("thread_id"),
                in_reply_to=email_data.get("message_id"),
            )
            if ok and email_data.get("id"):
                try:
                    self.gmail.add_label(email_data["id"], self.label_processed)
                except Exception as e:
                    print(f"  label warn: {e}")
        print(f"{'='*60}\n")
```

- [ ] **Step 6: Quitar `start_monitoring`/`main` IMAP**

Eliminar el método `start_monitoring` (L527-548) y la función `main()` + el bloque `if __name__ == "__main__"` (L551-558). El entrypoint pasa a ser `modules/quote_queue/runner.py` (Task 7). (Dejar `process_email` y `_process_submission` intactos salvo lo anterior.)

- [ ] **Step 7: Compilar + pyflakes**

Run:
```
C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pyflakes workflow_orchestrator.py
C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -c "import workflow_orchestrator"
```
Expected: sin errores (pyflakes limpio; import OK).

- [ ] **Step 8: Commit**

```bash
git add workflow_orchestrator.py
git commit -m "refactor(orchestrator): analisis por Gmail API en hilo+CC+etiqueta; submission_id desde message_id; quita monitor IMAP

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Runner — reclaim_stale + monitor + workers

**Files:**
- Create: `modules/quote_queue/runner.py`
- Test: `tests/quote_queue/test_runner.py`

El runner es el entrypoint del bot. Expone funciones testeable-en-unidad: `poll_once(gmail, orchestrator, subject_filter)` (un ciclo del monitor) y `build_workers(store, gmail, mgas, ...)`. El `run_forever()` las orquesta con threads + sleeps (no se testea en unidad).

- [ ] **Step 1: Crear el test que falla**

Crear `tests/quote_queue/test_runner.py`:

```python
"""Unit del runner: un ciclo de monitor procesa+marca-leído cada correo."""
from unittest.mock import MagicMock

from modules.quote_queue import runner


def test_poll_once_processes_and_marks_read():
    gmail = MagicMock()
    gmail.fetch_unread.return_value = [
        {"id": "m1", "subject": "Submission A"},
        {"id": "m2", "subject": "Submission B"},
    ]
    orch = MagicMock()

    n = runner.poll_once(gmail, orch, "Submission")

    assert n == 2
    assert orch.process_email.call_count == 2
    gmail.mark_read.assert_any_call("m1")
    gmail.mark_read.assert_any_call("m2")


def test_poll_once_marks_read_even_if_process_raises():
    gmail = MagicMock()
    gmail.fetch_unread.return_value = [{"id": "m1", "subject": "X"}]
    orch = MagicMock()
    orch.process_email.side_effect = RuntimeError("boom")

    n = runner.poll_once(gmail, orch, "Submission")

    assert n == 1
    gmail.mark_read.assert_called_once_with("m1")
```

- [ ] **Step 2: Correr (debe fallar)**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/quote_queue/test_runner.py -q`
Expected: FAIL (`No module named 'modules.quote_queue.runner'`).

- [ ] **Step 3: Crear `modules/quote_queue/runner.py`**

```python
"""
Runner del bot autónomo: productor (monitor del inbox) + consumidores (un
worker-thread por MGA), en un solo proceso, sobre la cola durable.

Entrypoint:  python -m modules.quote_queue.runner
"""

import threading
import time

from modules.config_manager import get_config
from modules.gmail_client import GmailClient
from modules.quote_queue.worker import QuoteWorker


def poll_once(gmail, orchestrator, subject_filter: str) -> int:
    """Un ciclo del monitor: procesa cada no-leído y lo marca leído (siempre,
    aun si el procesamiento falla, para no reprocesarlo). Devuelve cuántos vio."""
    emails = gmail.fetch_unread(subject_filter)
    for email_data in emails:
        try:
            orchestrator.process_email(email_data)
        except Exception as e:  # un correo malo no frena el monitor
            print(f"  [monitor] error procesando {email_data.get('subject','')[:50]}: {e}")
        finally:
            try:
                gmail.mark_read(email_data["id"])
            except Exception as e:
                print(f"  [monitor] no se pudo marcar leído: {e}")
    return len(emails)


def _create_quote_for(mga: str):
    """Devuelve la función create_quote(profile, eff_date) del cliente del MGA."""
    if mga == "PROGRESSIVE":
        from modules.progressive.client import ProgressiveClient
        return ProgressiveClient.create_quote
    if mga == "GEICO":
        from modules.geico.client import GEICOClient
        return GEICOClient.create_quote
    raise ValueError(f"MGA desconocido: {mga}")


def _worker_loop(worker: QuoteWorker, stop: threading.Event, idle_sleep: float = 5.0):
    while not stop.is_set():
        try:
            took = worker.run_once()
        except Exception as e:
            print(f"  [worker:{worker.mga}] loop error: {e}")
            took = False
        if not took:
            stop.wait(idle_sleep)


def run_forever(check_interval: int = 60) -> None:
    config = get_config()
    gmail = GmailClient()

    # Importar acá para evitar ciclos de import al cargar el módulo.
    from workflow_orchestrator import QuoteWorkflowOrchestrator
    orchestrator = QuoteWorkflowOrchestrator()
    store = orchestrator.quote_store
    subject_filter = config.get("email.monitoring.subject_filter", "Submission")
    label = config.get("email.label_processed", "Cotizado-Bot")

    # Recuperación de crash: jobs colgados vuelven a pending.
    reclaimed = store.reclaim_stale()
    print(f"[runner] reclaim_stale -> {reclaimed} jobs")

    # Un worker-thread por MGA habilitado.
    stop = threading.Event()
    threads = []
    for mga in sorted(orchestrator.rpa_mgas):
        worker = QuoteWorker(mga, store, _create_quote_for(mga), gmail,
                             label_processed=label)
        t = threading.Thread(target=_worker_loop, args=(worker, stop),
                             name=f"worker-{mga}", daemon=True)
        t.start()
        threads.append(t)
    print(f"[runner] workers: {sorted(orchestrator.rpa_mgas)}")

    print(f"[runner] monitoreando '{subject_filter}' cada {check_interval}s")
    try:
        while True:
            n = poll_once(gmail, orchestrator, subject_filter)
            if n:
                print(f"[monitor] procesados {n} correo(s)")
            time.sleep(check_interval)
    except KeyboardInterrupt:
        print("\n[runner] apagando...")
        stop.set()


if __name__ == "__main__":
    run_forever()
```

- [ ] **Step 4: Correr (debe pasar)**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/quote_queue/test_runner.py -q`
Expected: 2 passed.

- [ ] **Step 5: pyflakes + commit**

```bash
C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pyflakes modules/quote_queue/runner.py tests/quote_queue/test_runner.py
git add modules/quote_queue/runner.py tests/quote_queue/test_runner.py
git commit -m "feat(queue): runner.py (monitor inbox + worker-thread por MGA + reclaim_stale)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Smoke offline + suite completa

**Files:**
- Test: (sin archivos nuevos) — correr la suite y un import-smoke del runner.

- [ ] **Step 1: Suite completa verde**

Run:
```
C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/ -q
```
Expected: todo verde salvo los 2 fallos PRE-EXISTENTES de `tests/test_rule_engine.py` (TestBusinessYears::test_business_years_too_low, TestInformational::test_informational_passed_through) — NO son de este trabajo. Cualquier otro fallo se arregla antes de seguir.

- [ ] **Step 2: Import-smoke del runner (sin red, sin arrancar)**

Run:
```
C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -c "from modules.quote_queue import runner; from modules.gmail_client import GmailClient; print('imports OK')"
```
Expected: `imports OK` (sin tocar Gmail ni la red — el `GmailClient()` no llama al API hasta el primer uso).

- [ ] **Step 3: pyflakes global de lo tocado**

Run:
```
C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pyflakes modules/gmail_client.py modules/quote_queue/runner.py modules/quote_queue/worker.py workflow_orchestrator.py
```
Expected: sin salida (limpio).

- [ ] **Step 4: Commit (si hubo ajustes)**

```bash
git add -A
git commit -m "test(bot): suite verde + smoke de imports del runner

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Validación LIVE (post-implementación, fuera del subagent-driven)

Estos pasos los corre el operador en este host (tocan la red real). NO son parte de los commits automáticos:

1. **Verificar que el token Gmail permite enviar:**
   ```
   C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -c "from modules.gmail_client import GmailClient; GmailClient().send_threaded(to='programacion@h2oins.com', subject='[ANALISIS] prueba bot', body='ping', is_html=False)"
   ```
   - Si llega el correo → `gmail.modify` cubre send. ✓
   - Si da 403 `insufficientPermissions` → agregar `gmail.send` a `SCOPES` en `gmail_client.py` Y en `gmail_api_otp_reader.py`, borrar `data/token.json` y re-correr `scripts/gmail_oauth_bootstrap.py` (consentir una vez como quotes@h2oins.com). Re-probar.
2. **Arrancar el bot:** `python -m modules.quote_queue.runner`. Mandar a `quotes@h2oins.com` un correo de prueba con asunto que matchee el filtro + una BlueQuote adjunta. Verificar: se cotiza, llega la respuesta EN EL HILO a quotes@ con CC a programacion@ y el PDF adjunto, y el correo original queda con la etiqueta `Cotizado-Bot` + leído.
3. Vigilar las primeras corridas de GEICO por el quote-resume (USDOT repetido).
4. (Opcional) dejarlo como servicio de Windows persistente.

---

## Self-Review (hecho por el autor del plan)

**Cobertura del spec:**
- GmailClient (fetch/send/label/mark_read) → Tasks 2-4. ✓
- runner.py (reclaim_stale + monitor + workers) → Task 7. ✓
- Orquestador a GmailClient + contexto + recipients + _submission_id + inline → Task 6. ✓
- Worker send_threaded + label + PDFs adjuntos → Task 5. ✓
- Config (geico_queue_enabled, analysis_to/cc, label) → Task 1. ✓
- Captura PDF Progressive → YA implementado (spec corregido); no hay tarea (correcto). ✓
- Scope gmail.modify→send → verificación LIVE documentada. ✓

**Placeholders:** ninguno — cada step tiene código/comando real.

**Consistencia de tipos/firmas:** `GmailClient.send_threaded(to, subject, body, cc=, attachments=, is_html=, thread_id=, in_reply_to=)` se define en Task 3 y se usa idéntico en worker (Task 5) y orquestador (Task 6). `add_label(message_id, label_name)` / `mark_read(message_id)` consistentes (def Task 4). `QuoteWorker.__init__(mga, store, create_quote, gmail, label_processed=)` consistente entre Task 5 (def) y Task 7 (uso). El contexto de submission (`recipient/cc/thread_id/in_reply_to/message_id/subject/body_html/attachment_paths`) es idéntico entre el productor (Task 6) y el consumidor (Task 5). ✓
