"""
Step-by-step GEICO pipeline test (no network).

Runs the BlueQuote PDF through each stage and prints the output so we can
verify correctness before a live GEICO run:

  1. BlueQuotePDFExtractor.extract()          -> raw form dict
  2. DocumentAIExtractor._map_blue_quote_to_profile()  -> profile components
  3. map_profile_to_fields()                  -> GEICO MappedFields
  4. missing_critical() + per-field summary
"""

import sys
import json
from pathlib import Path

# Ensure project root on path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.pdf_extractor import BlueQuotePDFExtractor
from modules.document_ai_extractor import DocumentAIExtractor
from modules.quote_profile import QuoteProfile
from modules.geico.field_mapper import map_profile_to_fields


def hr(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def main():
    pdf_path = ROOT / "data" / "input" / "20260528 BLUE QUOTE.pdf"
    print(f"PDF: {pdf_path}")
    assert pdf_path.exists(), "PDF not found"

    # ---- STEP 1: raw form extraction ----
    hr("STEP 1: BlueQuotePDFExtractor.extract() -- raw form data")
    raw = BlueQuotePDFExtractor(str(pdf_path)).extract()
    print(json.dumps(raw, indent=2, ensure_ascii=False, default=str))

    # ---- STEP 2: map to profile components ----
    hr("STEP 2: _map_blue_quote_to_profile() -- structured profile")
    extractor = object.__new__(DocumentAIExtractor)  # bypass __init__ (needs API key)
    applicant, commodity, coverages, units, drivers, cov_detail = \
        extractor._map_blue_quote_to_profile(raw)

    print("APPLICANT:")
    print(f"  business_name : {applicant.business_name!r}")
    print(f"  owner_name    : {applicant.owner_name!r}")
    print(f"  usdot         : {applicant.usdot!r}")
    print(f"  street        : {applicant.street_address!r}")
    print(f"  city          : {applicant.city!r}")
    print(f"  state         : {applicant.state!r}")
    print(f"  zip_code      : {applicant.zip_code!r}")
    print(f"  phone         : {applicant.phone!r}")
    print(f"  email         : {applicant.email!r}")
    print(f"  business_years: {applicant.business_years!r}")
    print(f"  current_carrier      : {applicant.current_carrier!r}")
    print(f"  years_continuous_cov : {applicant.years_continuous_coverage!r}")
    print(f"\nCOMMODITY: {commodity!r}")
    print(f"COVERAGE CODES: {coverages}")
    print(f"\nCOVERAGES_DETAIL:")
    print(f"  bodily_injury_limit : {cov_detail.bodily_injury_limit!r}")
    print(f"  comp_deductible     : {cov_detail.comp_deductible!r}")
    print(f"  coll_deductible     : {cov_detail.coll_deductible!r}")
    print(f"  motor_truck_cargo   : {cov_detail.motor_truck_cargo_limit!r}")
    print(f"\nUNITS (count={units.count}, trailer_types={units.trailer_types}):")
    for i, v in enumerate(units.vehicles):
        print(f"  vehicle[{i}]: vin={v.vin!r} year={v.year!r} make={v.make!r} "
              f"model={v.model!r} type={v.trailer_type!r} gvw={v.gvw!r}")
    print(f"\nDRIVERS ({len(drivers)}):")
    for i, d in enumerate(drivers):
        print(f"  driver[{i}]: name={d.name!r} dob={d.date_of_birth!r} "
              f"class={d.cdl_class!r} dl={d.license_number!r} "
              f"state={d.license_state!r} excluded={d.exclude_from_policy}")

    # ---- STEP 3: build QuoteProfile + map to GEICO fields ----
    hr("STEP 3: map_profile_to_fields() -- GEICO MappedFields")
    profile = QuoteProfile(
        applicant=applicant, commodity=commodity, coverages=coverages,
        coverages_detail=cov_detail, units=units, drivers=drivers,
    )
    mapped = map_profile_to_fields(profile, effective_date=None)

    print("-- Dashboard / Step 1 --")
    print(f"  usdot               : {mapped.usdot!r}")
    print(f"  zip_code            : {mapped.zip_code!r}")
    print(f"  business_class      : {mapped.business_class!r}")
    print(f"  has_eld             : {mapped.has_eld}")
    print(f"  has_hazmat_placard  : {mapped.has_hazmat_placard}")
    print("-- Step 2 (Owner) --")
    print(f"  owner_first/last    : {mapped.owner_first_name!r} / {mapped.owner_last_name!r}")
    print(f"  owner_dob           : {mapped.owner_dob!r}")
    print(f"  owner_phone         : {mapped.owner_phone!r}")
    print(f"  owner_email         : {mapped.owner_email!r}")
    print(f"  marital_status      : {mapped.marital_status!r}")
    print(f"  business_ownership  : {mapped.business_ownership_type!r}")
    print(f"  owner_is_driver     : {mapped.owner_is_driver}")
    print("-- Step 3 (Vehicles) --")
    for i, v in enumerate(mapped.vehicles):
        print(f"  vehicle[{i}]: vin={v.vin!r} type={v.vehicle_type!r} "
              f"dist={v.one_way_distance!r} comp_coll={v.has_comp_coll} "
              f"financed={v.is_financed_or_leased!r}")
    print("-- Step 4 (Drivers) --")
    for i, d in enumerate(mapped.drivers):
        print(f"  driver[{i}]: {d.first_name!r} {d.suffix or ''} {d.last_name!r} "
              f"owner={d.is_owner} excluded={d.is_excluded} cdl={d.has_cdl} "
              f"dl={d.license_number!r} state={d.license_state!r}")
    print("-- Step 5 (Additional Business) --")
    print(f"  years_operating       : {mapped.years_operating!r}")
    print(f"  employee_count        : {mapped.employee_count!r}")
    print(f"  has_current_insurance : {mapped.has_current_insurance}")
    print(f"  years_with_insurer    : {mapped.years_with_insurer!r}")
    print(f"  current_bi_limits     : {mapped.current_bi_limits!r}")
    print(f"  current_liability_type: {mapped.current_liability_type!r}")
    print("-- Step 7 (Final) --")
    print(f"  has_workers_comp      : {mapped.has_workers_comp}")

    # ---- STEP 4: critical-field check ----
    hr("STEP 4: missing_critical() -- gate before quoting")
    missing = mapped.missing_critical()
    if missing:
        print(f"  HALT: missing critical fields -> {missing}")
    else:
        print("  OK: all critical fields present, profile is quotable.")


if __name__ == "__main__":
    main()
