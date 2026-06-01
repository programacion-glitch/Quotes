"""
Live GEICO wizard validation with an ELIGIBLE USDOT (HUMBERTO VILLARREAL,
USDOT 2033673). The HUMBERTO PDF is no longer in data/input, so we load the
raw BlueQuote extract JSON and run it through the (current, fixed) mapper.

Goal: exercise the full wizard Steps 1-7 + price capture + PDF download, which
the REPUBLIC run could not reach (its USDOT is not eligible).

Usage:
    python scripts/run_geico_live_humberto.py
"""

import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception as e:
    print(f"WARN: could not load .env ({e})")

from modules.document_ai_extractor import DocumentAIExtractor
from modules.quote_profile import QuoteProfile
from modules.geico.client import GEICOClient


def main():
    extract_json = (ROOT / "data" / "output" /
                    "extracted_20260113_BLUE_QUOTE_REVISION_500k_HUMBERTO_VILLAREAL.json")
    print(f"[runner] Loading raw extract: {extract_json.name}")
    with open(extract_json, "r", encoding="utf-8") as f:
        raw = json.load(f)

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

    print("[runner] Starting GEICOClient.create_quote() — live (eligible USDOT)...")
    result = GEICOClient.create_quote(profile, effective_date=None)

    print("\n" + "=" * 70)
    print("QUOTE RESULT (HUMBERTO — full wizard expected)")
    print("=" * 70)
    print(f"  success       : {result.success}")
    print(f"  step_reached  : {result.step_reached}")
    print(f"  error         : {result.error}")
    print(f"  halted        : {result.halted}")
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
