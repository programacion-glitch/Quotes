"""
Live Progressive web-automation validation from a pre-extracted BlueQuote JSON.

Mirrors scripts/run_geico_live_humberto.py: load a raw BlueQuote extract,
run it through the (current) DocumentAI mapper to build a QuoteProfile, and
dispatch it to ProgressiveClient.create_quote — the same call the
workflow_orchestrator makes for the PROGRESSIVE MGA.

Usage:
    python scripts/run_progressive_live.py [extract_json_name]

Defaults to the FREIGHTZONE LLC extract.
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
from modules.progressive.client import ProgressiveClient


DEFAULT_EXTRACT = "extracted_20260127_BLUE_QUOTE_FREIGHTZONE_LLC.json"
# effective_date is a critical field (normally parsed from the email subject).
# For a manual test we pass a near-future date. Override via argv[2].
DEFAULT_EFFECTIVE_DATE = "06/15/2026"


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_EXTRACT
    effective_date = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_EFFECTIVE_DATE
    extract_json = ROOT / "data" / "output" / name
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

    print(f"[runner] Starting ProgressiveClient.create_quote() — live "
          f"(effective_date={effective_date})...")
    result = ProgressiveClient.create_quote(profile, effective_date=effective_date)

    print("\n" + "=" * 70)
    print("PROGRESSIVE QUOTE RESULT")
    print("=" * 70)
    for attr in ("success", "step_reached", "error", "halted", "is_stub",
                 "screenshot_path", "pdf_path"):
        print(f"  {attr:<14}: {getattr(result, attr, '(n/a)')}")
    price = getattr(result, "price", None)
    if price:
        for attr in ("annual_premium", "pay_in_full_savings", "quote_number",
                     "term_months"):
            print(f"  {attr:<14}: {getattr(price, attr, '(n/a)')}")
    warnings = getattr(result, "warnings", None)
    if warnings:
        print("  warnings:")
        for w in warnings:
            print(f"    - {w}")


if __name__ == "__main__":
    main()
