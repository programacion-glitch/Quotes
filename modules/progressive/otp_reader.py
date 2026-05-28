"""
Gmail OTP Reader for Progressive

Polls Gmail via IMAP for the 6-digit OTP that Progressive sends
after login. Filters by timestamp to avoid stale codes.
"""

import imaplib
import email
import email.message
import email.utils
import re
import time
from datetime import datetime, timezone
from typing import Optional


class GmailOTPReader:
    """Read Progressive OTP codes from Gmail via IMAP."""

    IMAP_SERVER = "imap.gmail.com"
    IMAP_PORT = 993
    OTP_SUBJECT = "Progressive"
    OTP_PATTERN = re.compile(r"\b(\d{6})\b")
    POLL_INTERVAL = 3   # seconds between polls
    MAX_WAIT = 60        # total seconds to wait

    def __init__(self, email_address: str, app_password: str):
        self.email_address = email_address
        self.app_password = app_password

    def fetch_otp(self, sent_after: datetime) -> Optional[str]:
        """
        Poll Gmail for the Progressive OTP sent after `sent_after`.

        Args:
            sent_after: only accept OTP emails received after this UTC timestamp.

        Returns:
            6-digit OTP string, or None if timed out.
        """
        deadline = time.time() + self.MAX_WAIT

        while time.time() < deadline:
            otp = self._try_fetch(sent_after)
            if otp:
                return otp
            time.sleep(self.POLL_INTERVAL)

        return None

    def _try_fetch(self, sent_after: datetime) -> Optional[str]:
        """Single IMAP fetch attempt. Returns OTP or None."""
        mail = None
        try:
            mail = imaplib.IMAP4_SSL(self.IMAP_SERVER, self.IMAP_PORT)
            mail.login(self.email_address, self.app_password)
            mail.select("INBOX")

            # Search for recent Progressive emails
            date_str = sent_after.strftime("%d-%b-%Y")
            _, data = mail.search(None, f'(SINCE "{date_str}" SUBJECT "{self.OTP_SUBJECT}" UNSEEN)')

            if not data[0]:
                return None

            email_ids = data[0].split()
            # Process most recent first
            for eid in reversed(email_ids):
                _, msg_data = mail.fetch(eid, "(RFC822)")
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)

                # Check date
                msg_date = email.utils.parsedate_to_datetime(msg["Date"])
                if msg_date.astimezone(timezone.utc) < sent_after.astimezone(timezone.utc):
                    continue

                # Extract OTP from HTML body
                body_html = self._get_html_body(msg)
                if not body_html:
                    continue

                # Look for 6-digit code near "passcode"
                lower = body_html.lower()
                idx = lower.find("passcode")
                if idx == -1:
                    idx = 0
                # Search within 500 chars of "passcode"
                search_region = body_html[max(0, idx - 100):idx + 500]
                match = self.OTP_PATTERN.search(search_region)
                if match:
                    # Mark as read so we don't reuse it
                    mail.store(eid, "+FLAGS", "\\Seen")
                    return match.group(1)

            return None
        except Exception as e:
            print(f"    OTP fetch error: {e}")
            return None
        finally:
            if mail:
                try:
                    mail.close()
                    mail.logout()
                except Exception:
                    pass

    def _get_html_body(self, msg: email.message.Message) -> Optional[str]:
        """Extract HTML body from email message."""
        if msg.is_multipart():
            for part in msg.walk():
                ct = part.get_content_type()
                if ct == "text/html":
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
        else:
            if msg.get_content_type() == "text/html":
                payload = msg.get_payload(decode=True)
                charset = msg.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace")
        return None
