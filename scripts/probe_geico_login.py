"""
One controlled GEICO login to validate Fase 3: Gmail-API OTP + persistent session.

Runs the full LoginPage flow (Azure B2C credentials -> conditional MFA ->
OTP via Gmail REST API -> gateway), saves the session to
data/geico_session.json, then opens a SECOND context reusing that state to
prove the next quote would skip login/OTP entirely.

NO quote is started — this never leaves the gateway dashboard.

Usage: python scripts/probe_geico_login.py
"""

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for s in (sys.stdout, sys.stderr):
    try:
        s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception as e:
    print("WARN dotenv", e)

from playwright.async_api import async_playwright

from modules.geico.client import GEICOConfig, _SESSION_STATE
from modules.geico.pages.login_page import LoginPage, _host_is_gateway
from modules.gmail_api_otp_reader import GmailAPIOTPReader


async def main() -> int:
    config = GEICOConfig.from_env()
    error = config.validate()
    if error:
        print(f"[probe] Config error: {error}")
        return 1

    reader = GmailAPIOTPReader(config.otp_email, subject="GEICO")
    # Check Gmail auth before touching the browser. NOT fatal: GEICO's MFA
    # is conditional (trusted device/IP logs straight through), so the
    # login may succeed without ever needing an OTP. If MFA does appear,
    # the login fails with a clear screenshot and this warning explains why.
    try:
        reader._get_service()
        print("[probe] Gmail API auth OK")
    except Exception as e:
        print(f"[probe] WARN: Gmail API auth unavailable: {e}")
        print(
            "[probe] continuing — if GEICO asks for MFA this login will "
            "fail; copy data/credentials.json + data/token.json from the "
            "other machine or run scripts/gmail_oauth_bootstrap.py"
        )

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=config.headless)

        # ---- Pass 1: login (reusing prior session if one exists) ----
        storage = str(_SESSION_STATE) if _SESSION_STATE.exists() else None
        print(f"[probe] prior session state: {'YES' if storage else 'no'}")
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            storage_state=storage,
        )
        ctx.set_default_timeout(30_000)
        page = await ctx.new_page()

        ok = await LoginPage(page, reader, config.login_url).login(
            config.username, config.password
        )
        if not ok:
            print("[probe] LOGIN FAILED — see logs/geico_login_*.png")
            await browser.close()
            return 1

        try:
            await ctx.storage_state(path=str(_SESSION_STATE))
            print(f"[probe] session saved -> {_SESSION_STATE}")
        except Exception as e:
            print(f"[probe] WARN: could not save session state: {e}")
        await ctx.close()

        # ---- Pass 2: prove the saved session skips login ----
        print("[probe] verifying session reuse in a fresh context...")
        ctx2 = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            storage_state=str(_SESSION_STATE),
        )
        ctx2.set_default_timeout(30_000)
        page2 = await ctx2.new_page()
        await page2.goto(
            "https://gateway.geico.com/quote",
            wait_until="networkidle",
            timeout=45_000,
        )
        login_form = page2.get_by_role("textbox", name="Username")
        bounced_to_login = await login_form.count() > 0
        on_gateway = _host_is_gateway(page2.url)
        if on_gateway and not bounced_to_login:
            print(f"[probe] SESSION REUSE OK -> {page2.url}")
            result = 0
        else:
            print(
                f"[probe] SESSION REUSE FAILED (url={page2.url}, "
                f"login_form={bounced_to_login}) — next quote will need OTP"
            )
            result = 1
        await browser.close()
        return result


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
