"""
Gmail API client (HTTPS / 443) para el flujo principal del bot.

Reemplaza el transporte IMAP/SMTP (modules/email_receiver.py / email_sender.py),
bloqueado en este host por eScan/Acronis. Reusa el mismo OAuth que el OTP reader
(data/credentials.json + data/token.json, scope gmail.modify — que autoriza
leer, enviar y modificar etiquetas).

El `service` de Gmail es inyectable (para tests sin red).
"""

import base64
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
