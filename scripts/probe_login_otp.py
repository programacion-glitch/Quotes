"""
One controlled Progressive login to measure OTP delivery.

Triggers a single login (which makes Progressive send an OTP), then polls the
Gmail API for up to 180s, printing exactly if/when the OTP email lands. This
distinguishes "OTP just slow (>60s)" from "OTP not being delivered at all
(account throttled/locked)".

Usage: python scripts/probe_login_otp.py
"""

import asyncio
import os
import sys
import time
from datetime import datetime, timezone
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
from modules.gmail_api_otp_reader import GmailAPIOTPReader


async def main():
    user = os.getenv("PROGRESSIVE_USER", "")
    pw = os.getenv("PROGRESSIVE_PASS", "")
    otp_email = os.getenv("PROGRESSIVE_OTP_EMAIL", "")
    reader = GmailAPIOTPReader(otp_email, subject="Progressive")

    # Confirm Gmail auth before we even touch the browser.
    try:
        reader._get_service()
        print("[probe] Gmail API auth OK")
    except Exception as e:
        print("[probe] Gmail API auth FAILED:", repr(e))
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1280, "height": 900})
        page = await ctx.new_page()
        print("[probe] navigating to login...")
        await page.goto("https://www.foragentsonly.com/home/?Welcome=584",
                        wait_until="networkidle", timeout=30_000)
        await page.get_by_role("textbox", name="User ID").fill(user)
        await page.get_by_role("textbox", name="User Password").fill(pw)
        login_time = datetime.now(timezone.utc)
        print(f"[probe] clicking Log In at {login_time.isoformat()}")
        await page.get_by_role("button", name="Log In").click(force=True, timeout=10_000)
        await page.wait_for_load_state("networkidle", timeout=15_000)

        # Is the OTP page shown?
        otp_page = False
        for t in ["passcode", "one-time", "verification code", "OTP"]:
            if await page.get_by_text(t, exact=False).count() > 0:
                otp_page = True
                break
        print(f"[probe] OTP page detected: {otp_page}  url={page.url}")
        await page.screenshot(path=str(ROOT / "logs" / "probe_after_login.png"))

        # Poll up to 180s for the OTP, reporting elapsed time when found.
        deadline = time.time() + 180
        found = None
        while time.time() < deadline:
            code = reader.fetch_otp(sent_after=login_time)  # internal 60s loop
            if code:
                found = code
                break
        elapsed = round(time.time() - login_time.timestamp(), 1)
        if found:
            print(f"[probe] OTP RECEIVED after ~{elapsed}s: {found[:2]}****")
        else:
            print(f"[probe] NO OTP after {elapsed}s -> Progressive did not deliver "
                  f"one (account likely throttled/locked, or login rejected).")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
