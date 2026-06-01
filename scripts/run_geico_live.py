"""
Live GEICO quote run for one BlueQuote (end-to-end integration test).

Extracts the BlueQuote PDF, builds a QuoteProfile, and runs the real
GEICOClient.create_quote() against the live portal. Prints the QuoteResult.

Usage:
    python scripts/run_geico_live.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Load .env so GEICO_* credentials are available.
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception as e:
    print(f"WARN: could not load .env ({e}); relying on ambient env vars")

from modules.pdf_extractor import BlueQuotePDFExtractor
from modules.document_ai_extractor import DocumentAIExtractor
from modules.quote_profile import QuoteProfile
from modules.geico.client import GEICOClient


def main():
    pdf_path = ROOT / "data" / "input" / "20260528 BLUE QUOTE.pdf"
    print(f"[runner] Extracting BlueQuote: {pdf_path.name}")
    raw = BlueQuotePDFExtractor(str(pdf_path)).extract()

    extractor = object.__new__(DocumentAIExtractor)
    applicant, commodity, coverages, units, drivers, cov_detail = \
        extractor._map_blue_quote_to_profile(raw)
    profile = QuoteProfile(
        applicant=applicant, commodity=commodity, coverages=coverages,
        coverages_detail=cov_detail, units=units, drivers=drivers,
    )
    print(f"[runner] Profile: {applicant.business_name!r} "
          f"USDOT={applicant.usdot!r} ZIP={applicant.zip_code!r} "
          f"vehicles={len(units.vehicles)} drivers={len(drivers)}")

    # effective_date: use the BlueQuote exp_date if present, else None.
    # (For testing GEICO accepts its default of tomorrow.)
    print("[runner] Starting GEICOClient.create_quote() — live...")
    result = GEICOClient.create_quote(profile, effective_date=None)

    print("\n" + "=" * 70)
    print("QUOTE RESULT")
    print("=" * 70)
    print(f"  success       : {result.success}")
    print(f"  step_reached  : {result.step_reached}")
    print(f"  error         : {result.error}")
    print(f"  is_stub       : {result.is_stub}")
    print(f"  screenshot    : {result.screenshot_path}")
    print(f"  pdf_path      : {result.pdf_path}")
    if result.price:
        print(f"  premium       : {result.price.annual_premium}")
        print(f"  pay_in_full   : {result.price.pay_in_full_savings}")
        print(f"  quote_number  : {result.price.quote_number}")
        print(f"  term_months   : {result.price.term_months}")
    if result.warnings:
        print("  warnings:")
        for w in result.warnings:
            print(f"    - {w}")


if __name__ == "__main__":
    main()
