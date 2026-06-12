"""One-off: print SOLANO's mapped GEICO fields for the MCP mapping session."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from modules.pdf_extractor import BlueQuotePDFExtractor
from modules.document_ai_extractor import DocumentAIExtractor
from modules.quote_profile import QuoteProfile
from modules.geico.field_mapper import map_profile_to_fields

PDF = ROOT / "data" / "input 10 Junio" / "20260603  BLUE QUOTE - Oscar Humberto Solano - 2003793.pdf"

raw = BlueQuotePDFExtractor(str(PDF)).extract()
ex = object.__new__(DocumentAIExtractor)
applicant, commodity, coverages, units, drivers, cov_detail = \
    ex._map_blue_quote_to_profile(raw)
profile = QuoteProfile(applicant=applicant, commodity=commodity,
                       coverages=coverages, coverages_detail=cov_detail,
                       units=units, drivers=drivers)
f = map_profile_to_fields(profile)
print("USDOT:", f.usdot, "| ZIP:", f.zip_code, "| business:", f.business_name)
print("class:", f.business_class)
print("owner:", f.owner_first_name, f.owner_last_name, "| dob:", f.owner_dob,
      "| phone:", f.owner_phone, "| email:", f.owner_email)
print("street:", f.owner_street, "| city:", f.owner_city,
      "| ownership:", f.business_ownership_type,
      "| owner_is_driver:", f.owner_is_driver)
print("years_op:", f.years_operating, "| employees:", f.employee_count,
      "| cur_ins:", f.has_current_insurance,
      "| yrs_insurer:", f.years_with_insurer, "| BI:", f.current_bi_limits)
for i, v in enumerate(f.vehicles):
    print(f"veh[{i}]: vin={v.vin} {v.year} {v.make} {v.model} "
          f"type={v.vehicle_type} dist={v.one_way_distance} "
          f"compcoll={v.has_comp_coll} fin={v.is_financed_or_leased}")
for i, d in enumerate(f.drivers):
    print(f"drv[{i}]: {d.first_name} {d.last_name} sfx={d.suffix} "
          f"dob={d.date_of_birth} st={d.license_state} dl={d.license_number} "
          f"cdl={d.has_cdl} owner={d.is_owner} excl={d.is_excluded}")
