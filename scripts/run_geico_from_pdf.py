"""
Live GEICO quote for ONE BlueQuote PDF (used standalone or by batch_geico.py).

Extracts the PDF, builds a QuoteProfile, runs the real
GEICOClient.create_quote(), and prints a RESULT block in the exact
label: value format the batch runner parses.

Usage:
    python scripts/run_geico_from_pdf.py <path-to-pdf> [effective_date]
"""

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
    print(f"WARN: could not load .env ({e}); relying on ambient env vars")

from modules.pdf_extractor import BlueQuotePDFExtractor
from modules.document_ai_extractor import DocumentAIExtractor
from modules.quote_profile import QuoteProfile
from modules.geico.client import GEICOClient


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: run_geico_from_pdf.py <pdf> [effective_date mm/dd/yyyy]")
        return 2
    pdf_path = Path(sys.argv[1])
    effective = sys.argv[2] if len(sys.argv) > 2 else None
    if not pdf_path.exists():
        print(f"PDF not found: {pdf_path}")
        return 2

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

    print(f"[runner] GEICOClient.create_quote() — live "
          f"(effective={effective or 'GEICO default'})...")
    result = GEICOClient.create_quote(profile, effective_date=effective)

    print("\n" + "=" * 70)
    print(f"RESULT ({pdf_path.name})")
    print("=" * 70)
    print(f"  success       : {result.success}")
    print(f"  step_reached  : {result.step_reached}")
    print(f"  error         : {result.error}")
    print(f"  halted        : {result.halted}")
    print(f"  screenshot_path: {result.screenshot_path}")
    print(f"  pdf_path      : {result.pdf_path}")
    if result.price:
        print(f"  annual_premium: {result.price.annual_premium}")
        print(f"  pay_in_full   : {result.price.pay_in_full_savings}")
        print(f"  quote_number  : {result.price.quote_number}")
        print(f"  term_months   : {result.price.term_months}")
    if result.warnings:
        print("  warnings:")
        for w in result.warnings:
            print(f"    - {w}")
    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
