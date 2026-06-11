"""
One controlled GEICO login to validate Fase 3: Gmail-API OTP + persistent session.

Runs the full LoginPage flow (Azure B2C credentials -> conditional MFA ->
OTP via Gmail REST API -> gateway), saves the session to
data/geico_session.json, then opens a SECOND context reusing that state to
prove the next quote would skip login/OTP entirely.

NO quote is started — this never leaves the gateway dashboard.

Usage:
    python scripts/probe_geico_login.py                # full: login + reuse check
    python scripts/probe_geico_login.py --reuse-only   # no fresh login/OTP: only
                                                       # verify the saved session
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

# 1920px wide: the wizard's right-hand Dashboard sidebar DOCKS at desktop
# width; at 1280px it floats as a drawer OVER the form (2026-06-11).
_VIEWPORT = {"width": 1920, "height": 1080}


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

    reuse_only = "--reuse-only" in sys.argv
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=config.headless)

        if not reuse_only:
            # ---- Pass 1: login (reusing prior session if one exists) ----
            storage = str(_SESSION_STATE) if _SESSION_STATE.exists() else None
            print(f"[probe] prior session state: {'YES' if storage else 'no'}")
            ctx = await browser.new_context(
                viewport=_VIEWPORT,
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
        elif not _SESSION_STATE.exists():
            print(f"[probe] --reuse-only but no session at {_SESSION_STATE}")
            await browser.close()
            return 1

        # ---- Pass 2: prove the saved session skips login ----
        # Navigate like a real quote would: entry point first (gateway ->
        # ecams bounce decides authenticated-or-not), then the /quote
        # dashboard. The success signal is the Commercial Auto eligibility
        # widget actually RENDERING — host checks alone are fooled by
        # gateway.geico.com/sessionexpireddashboard (single-session-per-agent
        # symptom, see project memory).
        print("[probe] verifying session reuse in a fresh context...")
        ctx2 = await browser.new_context(
            viewport=_VIEWPORT,
            storage_state=str(_SESSION_STATE),
        )
        ctx2.set_default_timeout(30_000)
        page2 = await ctx2.new_page()
        await page2.goto(
            config.login_url, wait_until="networkidle", timeout=45_000
        )
        bounced_to_login = (
            await page2.get_by_role("textbox", name="Username").count() > 0
        )
        if bounced_to_login:
            print(f"[probe] SESSION REUSE FAILED: bounced to sign-in form "
                  f"({page2.url}) — next quote will need OTP")
            await browser.close()
            return 1

        await page2.goto(
            "https://gateway.geico.com/quote",
            wait_until="networkidle",
            timeout=45_000,
        )
        expired = "sessionexpired" in page2.url.lower()
        widget = page2.locator("#labelForCommercialAuto")
        try:
            await widget.wait_for(state="visible", timeout=15_000)
            widget_ok = True
        except Exception:
            widget_ok = False

        if _host_is_gateway(page2.url) and widget_ok and not expired:
            print(f"[probe] SESSION REUSE OK (Commercial Auto widget rendered) "
                  f"-> {page2.url}")
            result = 0
        else:
            await page2.screenshot(
                path=str(ROOT / "logs" / "geico_probe_reuse_failed.png"),
                full_page=True,
            )
            print(
                f"[probe] SESSION REUSE FAILED (url={page2.url}, "
                f"expired={expired}, widget={widget_ok}) — next quote will "
                f"need OTP; screenshot: logs/geico_probe_reuse_failed.png"
            )
            result = 1
        await browser.close()
        return result


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
