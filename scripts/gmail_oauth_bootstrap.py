"""
One-time Gmail API OAuth consent.

Runs the installed-app OAuth flow using data/credentials.json and writes a
data/token.json with a refresh token. After this, GmailAPIOTPReader reads mail
over HTTPS (port 443) without any further interaction.

Sign in as the OTP mailbox (quotes@h2oins.com) when the browser opens.

Usage:
    python scripts/gmail_oauth_bootstrap.py
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Google suele devolver scopes extra (openid/email) o en otro orden; relajamos
# la validación para que el flujo no falle por "Scope has changed".
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

from google_auth_oauthlib.flow import InstalledAppFlow

# Token COMBINADO para quotes@: Gmail (leer/enviar/etiquetar) + Drive (subir
# las indicaciones a '1) QUOTES', que es de quotes@). Los clientes en runtime
# piden cada uno su subconjunto (gmail.modify ó drive), así que un token con
# ambos scopes les sirve a todos.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/drive",
]

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
