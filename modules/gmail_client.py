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
    """Lee el inbox, responde en hilo (con CC), etiqueta y marca leído."""

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

    def fetch_unread(self, subject_filter: Optional[str] = None,
                     after_epoch: Optional[float] = None,
                     exclude_label: Optional[str] = None,
                     from_allowlist: Optional[List[str]] = None,
                     skip_message_id=None,
                     unread_only: bool = True,
                     metadata_filter=None) -> List[dict]:
        """Correos que matchean el filtro de asunto, en el dict del flujo.

        after_epoch: si se da, solo correos recibidos DESPUÉS de ese epoch
        (término Gmail `after:`), para ignorar el backlog viejo sin tocarlo.

        exclude_label: si se da, excluye los que ya tengan esa etiqueta
        (término Gmail `-label:`). Así el bot puede dejar los correos NO LEÍDOS
        y aún no reprocesarlos: se marcan con la etiqueta en vez de leídos.

        from_allowlist: si se da, restringe a remitentes en la lista
        (término Gmail `from:(a OR b ...)`). Así los correos fuera de la
        lista ni se descargan.

        skip_message_id: callable(id) -> bool. Se evalúa sobre los IDs del
        listado ANTES de messages.get: un correo ya visto no se vuelve a
        descargar (cuerpo + adjuntos). Imprescindible con polling agresivo —
        un pendiente se re-descargaría en CADA ciclo.

        unread_only: con False NO filtra por is:unread — el dedup queda 100%
        a cargo del caller (seen_emails + corte). Así un correo que ventas
        leyó antes que el bot (o durante una caída) NO se pierde.

        metadata_filter: callable(msg_id, sender_email, subject) -> bool.
        Se evalúa con un messages.get de SOLO headers, ANTES de la descarga
        completa (cuerpo + adjuntos): lo rechazado (p.ej. "Re: ..." de un
        hilo viejo) nunca se baja entero. Crítico sin is:unread, donde el
        listado incluye todas las respuestas del período.
        """
        svc = self._svc()
        q = "is:unread" if unread_only else ""
        if subject_filter:
            q += f' subject:"{subject_filter}"'
        if after_epoch:
            q += f" after:{int(after_epoch)}"
        if exclude_label:
            q += f' -label:"{exclude_label}"'
        if from_allowlist:
            # from:(a@x OR b@x ...) — los remitentes fuera de la lista ni se
            # descargan (no messages.get, no se etiquetan).
            addrs = " OR ".join(from_allowlist)
            q += f" from:({addrs})"
        q = q.strip()

        # Sin is:unread el resultado crece con el período: paginar para que
        # un backlog (p.ej. tras una caída) no quede fuera de la primera página.
        refs, token = [], None
        for _ in range(10):  # tope de seguridad: 10 páginas x 50
            req = {"userId": "me", "q": q, "maxResults": 50}
            if token:
                req["pageToken"] = token
            resp = svc.users().messages().list(**req).execute()
            refs.extend(resp.get("messages", []))
            token = resp.get("nextPageToken")
            if not token:
                break

        out = []
        for ref in refs:
            if skip_message_id is not None and skip_message_id(ref["id"]):
                continue
            if metadata_filter is not None:
                meta = (
                    svc.users().messages()
                    .get(userId="me", id=ref["id"], format="metadata",
                         metadataHeaders=["From", "Subject"])
                    .execute()
                )
                payload = meta.get("payload", {})
                _, sender_email = self._split_sender(
                    self._header(payload, "From"))
                if not metadata_filter(ref["id"], sender_email,
                                       self._header(payload, "Subject")):
                    continue
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
