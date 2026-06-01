"""
One-time Gmail API OAuth consent.

Runs the installed-app OAuth flow using data/credentials.json and writes a
data/token.json with a refresh token. After this, GmailAPIOTPReader reads mail
over HTTPS (port 443) without any further interaction.

Sign in as the OTP mailbox (quotes@h2oins.com) when the browser opens.

Usage:
    python scripts/gmail_oauth_bootstrap.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from google_auth_oauthlib.flow import InstalledAppFlow

from modules.gmail_api_otp_reader import SCOPES

CREDENTIALS = ROOT / "data" / "credentials.json"
TOKEN = ROOT / "data" / "token.json"


def main():
    if not CREDENTIALS.exists():
        print(f"ERROR: credentials.json not found at {CREDENTIALS}")
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS), SCOPES)
    # Opens the system browser and runs a localhost server to catch the
    # redirect. Sign in as quotes@h2oins.com and grant read access.
    creds = flow.run_local_server(port=0, prompt="consent")
    TOKEN.write_text(creds.to_json(), encoding="utf-8")
    print(f"OK: token saved to {TOKEN}")


if __name__ == "__main__":
    main()
