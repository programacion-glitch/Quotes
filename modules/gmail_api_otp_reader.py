"""
Gmail API OTP Reader (HTTPS / port 443).

Drop-in replacement for the IMAP-based OTP readers
(`modules/progressive/otp_reader.py`, `modules/geico/otp_reader.py`).

Why this exists: this machine's host network stack (eScan / Acronis mail
scanning) resets IMAP/SMTP TLS connections to Gmail (993/465) for host
processes — Python AND Node both get `WinError 10053/10054` reset, while
Docker containers (separate egress) are unaffected. HTTPS/443 is NOT blocked,
so reading mail via the Gmail REST API works from the host.

Auth: OAuth installed-app flow. A one-time consent (see
`scripts/gmail_oauth_bootstrap.py`) produces a `token.json` with a refresh
token; subsequent runs refresh silently over HTTPS. The mailbox is the same
`quotes@h2oins.com` the IMAP readers used.

Interface mirrors `GmailOTPReader.fetch_otp(sent_after) -> Optional[str]` so
the login pages can use it unchanged.
"""

import base64
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


# Read-only is enough: we filter by message timestamp instead of marking
# messages as read, so we never need write scope.
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_CREDENTIALS = _PROJECT_ROOT / "data" / "credentials.json"
_DEFAULT_TOKEN = _PROJECT_ROOT / "data" / "token.json"


class GmailAPIOTPReader:
    """Read OTP codes from Gmail via the REST API (HTTPS)."""

    OTP_PATTERN = re.compile(r"\b(\d{6})\b")
    POLL_INTERVAL = 3   # seconds between polls
    MAX_WAIT = 60       # total seconds to wait

    def __init__(
        self,
        email_address: str,
        subject: str = "Progressive",
        credentials_path: Optional[Path] = None,
        token_path: Optional[Path] = None,
    ):
        self.email_address = email_address
        self.subject = subject
        self.credentials_path = Path(credentials_path or _DEFAULT_CREDENTIALS)
        self.token_path = Path(token_path or _DEFAULT_TOKEN)
        self._service = None

    # ---- auth / service ----

    def _load_credentials(self) -> Credentials:
        """Load the cached token and refresh it if needed.

        Does NOT trigger the interactive consent flow — that is a one-time
        bootstrap (scripts/gmail_oauth_bootstrap.py). If no valid token exists
        we raise with a clear message so the operator knows to run it.
        """
        if not self.token_path.exists():
            raise RuntimeError(
                f"Gmail API token not found at {self.token_path}. Run "
                f"`python scripts/gmail_oauth_bootstrap.py` once to authorize "
                f"(sign in as {self.email_address})."
            )
        creds = Credentials.from_authorized_user_file(
            str(self.token_path), SCOPES
        )
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                self.token_path.write_text(creds.to_json(), encoding="utf-8")
            else:
                raise RuntimeError(
                    f"Gmail API token at {self.token_path} is invalid and has "
                    f"no refresh token. Re-run scripts/gmail_oauth_bootstrap.py."
                )
        return creds

    def _get_service(self):
        if self._service is None:
            creds = self._load_credentials()
            # cache_discovery=False avoids a noisy warning + a file-cache write.
            self._service = build(
                "gmail", "v1", credentials=creds, cache_discovery=False
            )
        return self._service

    # ---- public API ----

    def fetch_otp(self, sent_after: datetime) -> Optional[str]:
        """Poll Gmail for the OTP sent after `sent_after`. Returns the 6-digit
        code, or None if it never arrives within MAX_WAIT."""
        deadline = time.time() + self.MAX_WAIT
        # Gmail's `after:` query filter has 1-second resolution and uses the
        # account's notion of receipt time; subtract a small skew so we don't
        # miss a code that lands in the same second we started waiting.
        after_epoch = int(sent_after.timestamp()) - 5

        while time.time() < deadline:
            otp = self._try_fetch(sent_after, after_epoch)
            if otp:
                return otp
            time.sleep(self.POLL_INTERVAL)
        return None

    def _try_fetch(self, sent_after: datetime, after_epoch: int) -> Optional[str]:
        """Single Gmail API poll. Returns OTP or None."""
        try:
            svc = self._get_service()
            query = f'subject:{self.subject} after:{after_epoch}'
            resp = (
                svc.users()
                .messages()
                .list(userId="me", q=query, maxResults=10)
                .execute()
            )
            messages = resp.get("messages", [])
            if not messages:
                return None

            for ref in messages:
                msg = (
                    svc.users()
                    .messages()
                    .get(userId="me", id=ref["id"], format="full")
                    .execute()
                )
                # internalDate is epoch milliseconds (receipt time).
                internal_ms = int(msg.get("internalDate", "0"))
                msg_dt = datetime.fromtimestamp(
                    internal_ms / 1000, tz=timezone.utc
                )
                if msg_dt < sent_after.astimezone(timezone.utc):
                    continue

                body = self._extract_body(msg.get("payload", {}))
                if not body:
                    continue
                code = self._extract_code(body)
                if code:
                    return code
            return None
        except Exception as e:  # noqa: BLE001
            print(f"    OTP fetch error (Gmail API): {e}")
            return None

    # ---- body parsing ----

    def _extract_body(self, payload: dict) -> str:
        """Walk the MIME tree and return decoded text (HTML preferred, then
        plain). Gmail API base64url-encodes each part's data."""
        html, plain = "", ""

        def walk(part):
            nonlocal html, plain
            mime = part.get("mimeType", "")
            data = part.get("body", {}).get("data")
            if data:
                decoded = base64.urlsafe_b64decode(
                    data.encode("utf-8")
                ).decode("utf-8", errors="replace")
                if mime == "text/html":
                    html += decoded
                elif mime == "text/plain":
                    plain += decoded
            for sub in part.get("parts", []) or []:
                walk(sub)

        walk(payload)
        return html or plain

    def _extract_code(self, body: str) -> Optional[str]:
        """Find the 6-digit code, preferring one near the word 'passcode'."""
        lower = body.lower()
        idx = lower.find("passcode")
        if idx == -1:
            idx = lower.find("code")
        region = body[max(0, idx - 100):idx + 500] if idx != -1 else body
        match = self.OTP_PATTERN.search(region)
        if match:
            return match.group(1)
        # Fallback: any 6-digit run in the whole body.
        match = self.OTP_PATTERN.search(body)
        return match.group(1) if match else None
