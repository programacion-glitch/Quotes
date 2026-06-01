"""Gmail OTP reader for GEICO (Azure B2C verification codes).

Reuses the IMAP polling logic from Progressive but with GEICO-specific
subject filter and extraction context. Progressive emails say "passcode"
while GEICO/Azure B2C emails say "verification code", so we override
`_try_fetch` with a minimal patched body-search region.
"""

import email
import email.utils
import imaplib
from datetime import timezone
from datetime import datetime as _dt
from typing import Optional

from modules.progressive.otp_reader import GmailOTPReader as _BaseReader


class GeicoOTPReader(_BaseReader):
    """Read GEICO MFA verification codes from Gmail via IMAP."""

    # GEICO sends from "Microsoft on behalf of GEICO Extend" with a subject
    # like "GEICO Extend account email verification code". Keep broad.
    OTP_SUBJECT = "GEICO"

    # Body anchors to scope the 6-digit search. Progressive used "passcode";
    # Azure B2C uses "verification code" / "code is".
    _BODY_ANCHORS = ("verification code", "verification", "code is", "code:", "passcode")

    def _try_fetch(self, sent_after: _dt) -> Optional[str]:
        """Single IMAP fetch attempt scoped to GEICO body anchors."""
        mail = None
        try:
            mail = imaplib.IMAP4_SSL(self.IMAP_SERVER, self.IMAP_PORT)
            mail.login(self.email_address, self.app_password)
            mail.select("INBOX")

            date_str = sent_after.strftime("%d-%b-%Y")
            _, data = mail.search(
                None, f'(SINCE "{date_str}" SUBJECT "{self.OTP_SUBJECT}" UNSEEN)'
            )
            if not data[0]:
                return None

            for eid in reversed(data[0].split()):
                _, msg_data = mail.fetch(eid, "(RFC822)")
                msg = email.message_from_bytes(msg_data[0][1])

                msg_date = email.utils.parsedate_to_datetime(msg["Date"])
                if msg_date.astimezone(timezone.utc) < sent_after.astimezone(timezone.utc):
                    continue

                body_html = self._get_html_body(msg)
                if not body_html:
                    continue

                lower = body_html.lower()
                idx = -1
                for anchor in self._BODY_ANCHORS:
                    idx = lower.find(anchor)
                    if idx != -1:
                        break
                if idx == -1:
                    idx = 0

                search_region = body_html[max(0, idx - 100):idx + 500]
                match = self.OTP_PATTERN.search(search_region)
                if match:
                    mail.store(eid, "+FLAGS", "\\Seen")
                    return match.group(1)

            return None
        except Exception as e:
            print(f"    [GEICO] OTP fetch error: {e}")
            return None
        finally:
            if mail:
                try:
                    mail.close()
                    mail.logout()
                except Exception:
                    pass
