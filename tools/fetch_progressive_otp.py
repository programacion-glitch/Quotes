"""
Fetch the most recent Progressive OTP from Gmail and DELETE that email.

Usage:
    python tools/fetch_progressive_otp.py

Used by Claude in live MCP Playwright sessions so that:
  - login form gets a fresh OTP
  - the email is removed from the inbox after use (no clutter)
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

import os
from modules.progressive.otp_reader import GmailOTPReader

email_user = os.environ["PROGRESSIVE_OTP_EMAIL"]
app_pw = os.environ["PROGRESSIVE_OTP_APP_PASSWORD"]

# Accept OTPs sent in the last 5 minutes (covers typical live-session latency).
sent_after = datetime.now(timezone.utc) - timedelta(minutes=5)

reader = GmailOTPReader(email_user, app_pw, delete_after_read=True)
print(f"[..] Polling {email_user} for Progressive OTP since {sent_after.isoformat()}...")
otp = reader.fetch_otp(sent_after)
if otp:
    print(f"OTP: {otp}")
else:
    print("OTP: <none received within timeout>")
