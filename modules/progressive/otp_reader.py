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

    def __init__(
        self,
        email_address: str,
        app_password: str,
        delete_after_read: bool = True,
    ):
        """
        Args:
            email_address: Gmail address.
            app_password: Gmail app-password.
            delete_after_read: if True, move the OTP email to Trash after
                extracting the code. Default True so the workflow doesn't
                leave dozens of stale OTP emails in the inbox over time.
        """
        self.email_address = email_address
        self.app_password = app_password
        self.delete_after_read = delete_after_read

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
                    self._dispose(mail, eid)
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

    def _dispose(self, mail, eid) -> None:
        """Mark the OTP message as consumed.

        If `delete_after_read=True`, move it to Trash so the inbox stays clean.
        Otherwise just mark it as Seen so the next poll doesn't reprocess it.
        Failures are non-fatal — we already extracted the OTP.
        """
        try:
            if self.delete_after_read:
                # Gmail Trash: setting the Deleted flag + selecting Trash folder
                # would permanently delete. To move to Trash safely, use the
                # MOVE command (RFC 6851). Most Gmail IMAP servers support it.
                try:
                    mail.uid  # ensure attribute access works
                    mail._simple_command("MOVE", eid, "[Gmail]/Trash")
                except Exception:
                    # Fallback: COPY then mark Deleted + expunge in INBOX
                    mail.copy(eid, "[Gmail]/Trash")
                    mail.store(eid, "+FLAGS", "\\Deleted")
                    mail.expunge()
            else:
                mail.store(eid, "+FLAGS", "\\Seen")
        except Exception as e:
            # Don't fail the login just because cleanup couldn't complete.
            print(f"    OTP cleanup warning ({'delete' if self.delete_after_read else 'seen'}): {e}")

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
