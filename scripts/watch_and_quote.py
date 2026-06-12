"""
Watch GEICO for the Commercial Auto product to return, then QUOTE.

GEICO temporarily removed Commercial Auto/Trucking from the dashboard
(FMCSA banner, 2026-06-11 night). Quoting is impossible until it's back.
This script does ONE cheap check per invocation:

  1. Fresh login (trusted device -> usually no OTP) and navigate /quote.
  2. If the Commercial Auto widget is ABSENT -> print 'PRODUCT_DOWN' and
     exit 2 (the caller reschedules — no quote attempt is burned).
  3. If PRESENT -> the product is back: run the full RPA quote for the
     given BlueQuote and print the QuoteResult. exit 0 on QUOTED.

Designed to be driven on an interval (ScheduleWakeup / /loop) so the moment
GEICO restores the product, the RPA quotes automatically.

Usage:
    python scripts/watch_and_quote.py <pdf>
"""

import asyncio
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

from modules.geico import stealth
from modules.geico.client import GEICOConfig, _SESSION_STATE
from modules.geico.pages.login_page import LoginPage
from modules.gmail_api_otp_reader import GmailAPIOTPReader


async def _product_available() -> bool:
    """Cheap check: fresh login, navigate /quote, is the Commercial Auto
    widget present? Saves the session so a follow-up quote reuses it."""
    config = GEICOConfig.from_env()
    reader = GmailAPIOTPReader(config.otp_email, subject="GEICO")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            **stealth.launch_kwargs(headless=config.headless)
        )
        ctx = await browser.new_context(**stealth.context_kwargs())
        await stealth.apply_stealth(ctx)
        ctx.set_default_timeout(30_000)
        page = await ctx.new_page()
        try:
            ok = await LoginPage(page, reader, config.login_url).login(
                config.username, config.password
            )
            if not ok:
                print("[watch] login failed — see logs/geico_login_*.png")
                return False
            try:
                await ctx.storage_state(path=str(_SESSION_STATE))
            except Exception:
                pass
            await page.goto("https://gateway.geico.com/quote",
                            wait_until="networkidle", timeout=45_000)
            present = await page.evaluate(
                """() => {
                    const byId = !!document.querySelector('#labelForCommercialAuto');
                    const byText = (document.body.innerText || '')
                        .includes('Commercial Auto/Trucking');
                    return byId || byText;
                }"""
            )
            return bool(present)
        finally:
            await browser.close()


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: watch_and_quote.py <pdf>")
        return 3
    pdf = Path(sys.argv[1])

    print("[watch] checking GEICO Commercial Auto product availability...")
    available = asyncio.run(_product_available())
    if not available:
        print("PRODUCT_DOWN — GEICO Commercial Auto still removed from the "
              "dashboard; no quote attempted.")
        return 2

    print("PRODUCT_UP — Commercial Auto is back! Running the RPA quote...")
    # Import here so the cheap down-path doesn't load the full quote stack.
    from modules.pdf_extractor import BlueQuotePDFExtractor
    from modules.document_ai_extractor import DocumentAIExtractor
    from modules.quote_profile import QuoteProfile
    from modules.geico.client import GEICOClient

    raw = BlueQuotePDFExtractor(str(pdf)).extract()
    ex = object.__new__(DocumentAIExtractor)
    applicant, commodity, coverages, units, drivers, cov_detail = \
        ex._map_blue_quote_to_profile(raw)
    profile = QuoteProfile(
        applicant=applicant, commodity=commodity, coverages=coverages,
        coverages_detail=cov_detail, units=units, drivers=drivers,
    )
    result = GEICOClient.create_quote(profile, effective_date=None)
    print("\n" + "=" * 60)
    print(f"RESULT ({pdf.name})")
    print("=" * 60)
    print(f"  success       : {result.success}")
    print(f"  step_reached  : {result.step_reached}")
    print(f"  error         : {result.error}")
    print(f"  pdf_path      : {result.pdf_path}")
    if result.price:
        print(f"  annual_premium: {result.price.annual_premium}")
        print(f"  quote_number  : {result.price.quote_number}")
    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
