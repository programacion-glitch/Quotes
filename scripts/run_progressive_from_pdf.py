"""
Run ProgressiveClient.create_quote() live from a raw Blue Quote PDF.

Unlike run_progressive_live.py (which takes a pre-extracted JSON), this
script does the full pipeline:
  1. Read the PDF file
  2. Run DocumentAIExtractor.extract_all() over a one-element attachments list
     -> QuoteProfile
  3. Dispatch to ProgressiveClient.create_quote()
  4. Print the QuoteResult (price, quote number, warnings, error, etc.)

Usage:
    python scripts/run_progressive_from_pdf.py <pdf_path> [effective_date]

Example:
    python scripts/run_progressive_from_pdf.py \
        "C:/Users/Desarrollo/Downloads/20260601 BLUE QUOTE RYD LLC.pdf" \
        06/15/2026
"""

import sys
from pathlib import Path

# Force UTF-8 on Windows consoles so Unicode chars (→, ✓, etc.) printed
# by the pipeline don't crash with charmap errors on cp1252 terminals.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception as e:
    print(f"WARN: could not load .env ({e})")

from modules.document_ai_extractor import DocumentAIExtractor
from modules.progressive.client import ProgressiveClient


DEFAULT_EFFECTIVE_DATE = "06/15/2026"


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    pdf_path = Path(sys.argv[1])
    effective_date = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_EFFECTIVE_DATE

    if not pdf_path.exists():
        print(f"[ERR] PDF not found: {pdf_path}")
        return 2

    print(f"[runner] Reading PDF: {pdf_path.name} ({pdf_path.stat().st_size:,} bytes)")
    pdf_bytes = pdf_path.read_bytes()
    attachments = [{"filename": pdf_path.name, "data": pdf_bytes}]

    print(f"[runner] Running DocumentAIExtractor.extract_all()...")
    extractor = DocumentAIExtractor()
    profile = extractor.extract_all(attachments)

    a = profile.applicant
    print()
    print("=" * 70)
    print("EXTRACTED QUOTE PROFILE")
    print("=" * 70)
    print(f"  business_name      : {a.business_name!r}")
    print(f"  owner_name         : {a.owner_name!r}")
    print(f"  usdot              : {a.usdot!r}")
    print(f"  owner_dob          : {a.owner_dob!r}")
    print(f"  street_address     : {a.street_address!r}")
    print(f"  city / state / zip : {a.city!r} / {a.state!r} / {a.zip_code!r}")
    print(f"  phone / email      : {a.phone!r} / {a.email!r}")
    print(f"  commodity          : {profile.commodity!r}")
    print(f"  coverages          : {profile.coverages}")
    print(f"  vehicles ({len(profile.units.vehicles)}):")
    for i, v in enumerate(profile.units.vehicles):
        # value drives APD intent: presence → Comp/Coll = Yes; absence → No
        apd_hint = f"value={v.value!r} → APD=Yes" if v.value else "value=None → APD=No"
        print(
            f"    [{i}] vin={v.vin!r} y/m/m={v.year}/{v.make}/{v.model} "
            f"type={v.trailer_type!r} gvw={v.gvw!r} radius={v.radius_miles!r} "
            f"loan={v.has_loan!r} {apd_hint}"
        )
    print(f"  drivers ({len(profile.drivers)}):")
    for i, d in enumerate(profile.drivers):
        print(
            f"    [{i}] {d.name!r} license={d.license_number!r} "
            f"state={d.license_state!r} dob={d.date_of_birth!r}"
        )

    print()
    print(f"[runner] Starting ProgressiveClient.create_quote() — live "
          f"(effective_date={effective_date})...")
    result = ProgressiveClient.create_quote(profile, effective_date=effective_date)

    print()
    print("=" * 70)
    print("PROGRESSIVE QUOTE RESULT")
    print("=" * 70)
    for attr in ("success", "step_reached", "error", "screenshot_path"):
        print(f"  {attr:<14}: {getattr(result, attr, '(n/a)')}")
    price = getattr(result, "price", None)
    if price:
        for attr in ("annual_premium", "pay_in_full_amount",
                     "pay_in_full_savings", "quote_provided_by", "quote_number"):
            print(f"  {attr:<22}: {getattr(price, attr, '(n/a)')}")
    warnings = getattr(result, "warnings", None) or []
    if warnings:
        print("  warnings:")
        for w in warnings:
            print(f"    - {w}")

    return 0 if result.success else 3


if __name__ == "__main__":
    raise SystemExit(main())
