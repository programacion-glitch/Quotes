"""
Field Mapper for GEICO

Maps QuoteProfile data to GEICO commercial auto form field values.
HYBRID strategy: hardcoded defaults for obvious/policy fields, BlueQuote data
where present, and None for critical missing fields so the orchestrator can
halt early instead of submitting bad data.

Policy rules encoded here (see docs/Proceso GEICO.md "Decisiones de diseno
aprobadas"):

  1. Marital Status is ALWAYS "Single". Never read from BlueQuote.
  2. owner_is_driver = NOT (owner is in drivers list AND that driver is
     excluded). If excluded, the form's "real driver" will naturally be the
     next non-excluded driver.
  3. Phone source: BlueQuote prevails over GEICO auto-pop. We always provide
     owner_phone; GEICO's auto-pop will not override an explicit fill.
  4. VIN decode > BlueQuote.vehicle_type when conflict. We still populate
     vehicle_type from BlueQuote as a fallback in case VIN decode fails; the
     page object lets GEICO's decode win when both are present.
  5. Coverage Start Date comes from the caller (parsed upstream from the
     email subject). If None, the page object accepts GEICO's default
     (tomorrow).
  6. Skip telematics opt-ins (DriveEasy Pro) - handled in the page object.
  7. PDF deliverable - handled in quote_flow / page object, not here.
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from modules.quote_profile import (
    CoveragesProfile,
    DriverProfile,
    QuoteProfile,
    VehicleProfile,
)


_SUFFIX_TOKENS = {"JR", "SR", "II", "III", "IV", "V", "2ND", "3RD"}

# Mapping from a normalized BlueQuote commodity descriptor to the exact
# label GEICO exposes in its 1,596-option Business Class combobox.
# The key is matched as a substring (case-insensitive, with punctuation
# stripped) against the BlueQuote commodity string. Order matters — first
# hit wins. Unmatched commodities pass through raw and the page object's
# search-then-select fallback will surface a clear RuntimeError if absent.
_COMMODITY_TO_GEICO_CLASS = (
    # (commodity-substring tokens, GEICO catalog label)
    (("DIRT", "SAND", "GRAVEL"), "Dirt Sand & Gravel (For A Fee)"),
    (("SAND", "GRAVEL"),         "Sand & Gravel (For A Fee)"),
    (("DIRT",),                  "Dirt Hauling (For A Fee)"),
    (("GRAVEL",),                "Gravel Hauling (For A Fee)"),
    (("DUMP", "TRUCK"),          "Dump Trucking"),
    (("FRACK", "SAND"),          "Fracking Sand Hauling"),
    (("AGGREGATE",),             "Sand & Gravel (For A Fee)"),
    (("ROCK",),                  "Rock Hauling (For A Fee)"),
)


def _map_commodity_to_geico_class(commodity: Optional[str]) -> Optional[str]:
    """Translate a BlueQuote commodity string to a GEICO Business Class label.

    Returns None for empty input. Falls back to the raw stripped commodity
    when no rule matches — the page object will raise if GEICO's combobox
    doesn't contain that label.
    """
    if not commodity:
        return None
    normalized = commodity.upper().replace(",", " ").replace(".", " ")
    tokens = [t for t in normalized.split() if t.isalpha()]
    token_set = set(tokens)
    for needles, geico_label in _COMMODITY_TO_GEICO_CLASS:
        if all(n in token_set for n in needles):
            return geico_label
    return commodity.strip() or None


# ---------- Dataclasses ------------------------------------------------------

@dataclass
class MappedVehicle:
    """Vehicle data ready to be filled in GEICO Vehicles step."""
    vin: Optional[str] = None
    year: Optional[int] = None
    make: Optional[str] = None
    model: Optional[str] = None
    vehicle_type: str = "Tractor"
    one_way_distance: str = "51-100"
    has_personal_use: bool = False
    has_comp_coll: bool = False
    garaging_zip: Optional[str] = None
    is_financed_or_leased: str = "Owned"  # "Owned" | "Leased" | "Financed"


@dataclass
class MappedDriver:
    """Driver data ready to be filled in GEICO Drivers step."""
    first_name: str = ""
    last_name: str = ""
    suffix: Optional[str] = None
    date_of_birth: Optional[str] = None  # mm/dd/yyyy
    license_state: str = "Texas"
    license_number: Optional[str] = None
    has_cdl: bool = False
    is_owner: bool = False
    is_excluded: bool = False
    has_incidents: bool = False


@dataclass
class MappedFields:
    """GEICO form field values ready to be filled."""
    # ---- Critical fields (halt if missing) ----
    usdot: Optional[str] = None
    business_name: Optional[str] = None
    zip_code: Optional[str] = None
    effective_date: Optional[str] = None  # mm/dd/yyyy

    # ---- Owner ----
    owner_first_name: Optional[str] = None
    owner_last_name: Optional[str] = None
    owner_dob: Optional[str] = None       # mm/dd/yyyy
    owner_phone: Optional[str] = None
    owner_email: Optional[str] = None
    owner_street: Optional[str] = None
    owner_city: Optional[str] = None
    owner_is_driver: bool = False

    # ---- Business defaults ----
    marital_status: str = "Single"
    business_ownership_type: str = "Individual/Sole Proprietorship"
    business_class: Optional[str] = None
    has_eld: bool = False
    has_hazmat_placard: bool = False

    # ---- Additional Business Info (Step 5) ----
    years_operating: str = "7+"
    employee_count: str = "1"
    has_current_insurance: bool = True
    years_with_insurer: str = "3-5 Years"
    current_bi_limits: str = "$500,000/$500,000 or $500,000 CSL"
    current_liability_type: str = "None"   # BOP / GL / None
    needs_additional_insured: bool = False
    has_blanket_additional: bool = False
    requires_filings: bool = False

    # ---- Final Quote Details (Step 7) ----
    has_workers_comp: bool = False

    # ---- Per-vehicle and per-driver lists ----
    vehicles: List[MappedVehicle] = field(default_factory=list)
    drivers: List[MappedDriver] = field(default_factory=list)

    # ---- Pass-through coverages ----
    coverages: CoveragesProfile = field(default_factory=CoveragesProfile)

    def missing_critical(self) -> List[str]:
        """Return critical fields that block the GEICO quote."""
        missing: List[str] = []
        if not self.usdot:
            missing.append("usdot")
        if not self.business_name:
            missing.append("business_name")
        if not self.zip_code:
            missing.append("zip_code")
        if not self.owner_first_name:
            missing.append("owner_first_name")
        if not self.owner_last_name:
            missing.append("owner_last_name")
        if not self.vehicles:
            missing.append("vehicles (at least one)")
        if not any(not d.is_excluded for d in self.drivers):
            missing.append("at least one non-excluded driver")
        return missing


# ---------- Parsing / bucketing helpers -------------------------------------

def _parse_name(full_name: str) -> Tuple[str, str, Optional[str]]:
    """Split a full name into (first, last, suffix).

    Examples:
        "CLIFTON JR THOMAS"  -> ("CLIFTON", "THOMAS", "JR")
        "JOHN SMITH"         -> ("JOHN", "SMITH", None)
        "MARY ANN DOE"       -> ("MARY", "DOE", None)
    """
    if not full_name:
        return ("", "", None)
    tokens = [t for t in full_name.strip().split() if t]
    if not tokens:
        return ("", "", None)
    if len(tokens) == 1:
        return (tokens[0], "", None)
    first = tokens[0]
    last = tokens[-1]
    suffix: Optional[str] = None
    for mid in tokens[1:-1]:
        if mid.upper().strip(".") in _SUFFIX_TOKENS:
            suffix = mid.upper().strip(".")
            break
    return (first, last, suffix)


def _derive_business_ownership_type(
    business_name: Optional[str],
    owner_name: Optional[str],
    dba: Optional[str],
) -> str:
    """Heuristic mapping for GEICO Business Ownership Type."""
    name = (business_name or "").upper()
    if "LLC" in name:
        return "Limited Liability Company"
    if "INC" in name or "CORP" in name:
        return "Corporation/Other"
    if owner_name and name and name.strip() == owner_name.strip().upper():
        return "Individual/Sole Proprietorship"
    if dba:
        return "Individual/Sole Proprietorship"
    return "Individual/Sole Proprietorship"


def _extract_int(raw) -> Optional[int]:
    """Best-effort int extraction; handles strings like '27 YEARS'."""
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    m = re.search(r"\d+", str(raw))
    return int(m.group(0)) if m else None


def _years_operating_bucket(years) -> str:
    """Bucket years-in-business into a GEICO option."""
    y = _extract_int(years)
    if y is None or y < 1:
        return "Less than 1"
    if y == 1:
        return "1"
    if y == 2:
        return "2"
    if 3 <= y <= 6:
        return "3-6"
    return "7+"


def _employees_bucket(driver_count: int, owner_in_drivers: bool) -> str:
    """Map effective employee count (excluding owner) to a GEICO bucket."""
    n = max(0, driver_count - (1 if owner_in_drivers else 0))
    if n == 0:
        return "None"
    if n == 1:
        return "1"
    if 2 <= n <= 3:
        return "2-3"
    if 4 <= n <= 5:
        return "4-5"
    if 6 <= n <= 10:
        return "6-10"
    if 11 <= n <= 20:
        return "11-20"
    return "21+"


def _years_with_insurer_bucket(years) -> str:
    """Map years with current insurer to a GEICO option."""
    y = _extract_int(years)
    if y is None or y < 1:
        return "Less Than 1 Year"
    if 1 <= y <= 3:
        return "1-3 Years"
    if 3 < y <= 5:
        return "3-5 Years"
    if 5 < y <= 10:
        return "5-10 Years"
    return "10+ Years"


def _bi_limits_to_geico(bluequote_limit: Optional[str]) -> str:
    """Translate BlueQuote BI limit string to a GEICO option label."""
    if not bluequote_limit:
        return "$1,000,000/$1,000,000 or $1,000,000 CSL"
    s = bluequote_limit.upper().replace(" ", "")
    # Combined Single Limit variants
    if "500" in s and ("CSL" in s or "COMBINED" in s or "SINGLELIMIT" in s):
        return "$500,000/$500,000 or $500,000 CSL"
    if ("1M" in s or "1,000,000" in s or "1000000" in s) and (
        "CSL" in s or "COMBINED" in s or "SINGLELIMIT" in s
    ):
        return "$1,000,000/$1,000,000 or $1,000,000 CSL"
    if "300" in s and ("CSL" in s or "COMBINED" in s or "SINGLELIMIT" in s):
        return "$300,000/$300,000 or $300,000 CSL"
    if "100" in s and ("CSL" in s or "COMBINED" in s or "SINGLELIMIT" in s):
        return "$100,000/$100,000 or $100,000 CSL"
    # Split limits
    if "250" in s and "500" in s:
        return "$250,000/$500,000"
    return "$1,000,000/$1,000,000 or $1,000,000 CSL"


# ---------- Per-record mappers ----------------------------------------------

def _map_driver(d: DriverProfile, owner_name: Optional[str]) -> MappedDriver:
    """Map a DriverProfile to a MappedDriver.

    Owner detection: compare (first, last) tuples after `_parse_name` so that
    "HUMBERTO F VILLARREAL" (driver, with middle initial) matches the owner
    name "HUMBERTO VILLARREAL". Direct string comparison breaks on middle
    initials, suffix differences, and extra whitespace.
    """
    first, last, suffix = _parse_name(d.name)
    o_first, o_last, _o_suf = _parse_name(owner_name or "")
    is_owner = bool(
        o_first and o_last and first and last
        and o_first.strip().upper() == first.strip().upper()
        and o_last.strip().upper() == last.strip().upper()
    )
    has_cdl = bool(
        (d.cdl_class and d.cdl_class.strip().upper() in {"A", "B"})
        or d.cdl_present
    )
    has_incidents = bool(
        d.has_accidents_or_violations
        or (d.mvr_present and not d.mvr_is_clean)
    )
    return MappedDriver(
        first_name=first,
        last_name=last,
        suffix=suffix,
        date_of_birth=d.date_of_birth,
        license_state=d.license_state or "Texas",
        license_number=d.license_number,
        has_cdl=has_cdl,
        is_owner=is_owner,
        is_excluded=bool(d.exclude_from_policy),
        has_incidents=has_incidents,
    )


def _vehicle_type_from_trailer(trailer_type: Optional[str]) -> str:
    """Default GEICO Vehicle Type based on a BlueQuote trailer/vehicle hint."""
    if not trailer_type:
        return "Tractor"
    t = trailer_type.upper()
    if "DUMP" in t:
        return "Dump Truck"
    if "TRACTOR" in t:
        return "Tractor"
    if "PICKUP" in t:
        return "Pickup Truck"
    return "Tractor"


def _distance_bucket(radius_miles: Optional[str]) -> str:
    """Map BlueQuote radius string to GEICO one-way distance option."""
    if not radius_miles:
        return "51-100"
    s = radius_miles.upper()
    if "500+" in s or "OVER 500" in s or "MORE THAN 500" in s:
        return "More than 500"
    nums = [int(n) for n in re.findall(r"\d+", s)]
    if not nums:
        return "51-100"
    # Use the largest number as the effective one-way distance.
    d = max(nums)
    if d <= 25:
        return "0-25"
    if d <= 50:
        return "26-50"
    if d <= 100:
        return "51-100"
    if d <= 200:
        return "101-200"
    if d <= 300:
        return "201-300"
    if d <= 500:
        return "301-500"
    return "More than 500"


def _financed_or_leased(has_loan: Optional[str]) -> str:
    """Map BlueQuote has_loan string to GEICO ownership option."""
    raw = (has_loan or "").strip().lower()
    if raw == "lease" or raw == "leased":
        return "Leased"
    if raw == "loan" or raw == "financed":
        return "Financed"
    return "Owned"


def _map_vehicle(
    v: VehicleProfile,
    fallback_zip: Optional[str],
    coverages: CoveragesProfile,
    requested_coverages: Optional[List[str]] = None,
) -> MappedVehicle:
    """Map a VehicleProfile to a MappedVehicle.

    has_comp_coll derivation: prefer the explicit per-policy `requested_coverages`
    list (codes like "APD" from the BlueQuote) over CoveragesProfile defaults.
    Reason: `CoveragesProfile` defaults to `comp_deductible="$1,000"`, which
    would make every vehicle default to comp+coll even when the customer
    explicitly declined APD. The list-of-codes from the BlueQuote is the
    authoritative source for whether APD was requested.
    """
    if requested_coverages is not None:
        has_comp_coll = "APD" in requested_coverages
    else:
        # No code list available — fall back to checking deductibles are TRUTHY
        # (mirrors Progressive's coverages_rates_page guard `if coverages.comp_deductible:`).
        has_comp_coll = bool(coverages.comp_deductible) or bool(coverages.coll_deductible)
    return MappedVehicle(
        vin=v.vin,
        year=v.year,
        make=v.make,
        model=v.model,
        vehicle_type=_vehicle_type_from_trailer(v.trailer_type),
        one_way_distance=_distance_bucket(v.radius_miles),
        has_personal_use=False,
        has_comp_coll=has_comp_coll,
        garaging_zip=v.garaging_zip or fallback_zip,
        is_financed_or_leased=_financed_or_leased(v.has_loan),
    )


# ---------- Top-level mapper -------------------------------------------------

def map_profile_to_fields(
    profile: QuoteProfile,
    effective_date: Optional[str] = None,
) -> MappedFields:
    """Map a QuoteProfile to GEICO MappedFields."""
    applicant = profile.applicant
    biz_name = (applicant.business_name or "").strip()

    # DBA split: must be a space-bounded "DBA" token, not just any substring.
    # Otherwise "ADBASE LLC" would match the unbounded "DBA" inside "ADBASE".
    dba: Optional[str] = None
    name_upper = biz_name.upper()
    for sep in (" DBA ", " DBA:"):
        if sep in name_upper:
            idx = name_upper.index(sep)
            dba = biz_name[idx + len(sep):].strip().strip(":").strip()
            break

    # Owner name -> first/last
    owner_first, owner_last, _owner_suffix = _parse_name(applicant.owner_name)

    # Drivers
    mapped_drivers = [
        _map_driver(d, applicant.owner_name) for d in profile.drivers
    ]

    # owner_is_driver = NOT (owner appears in drivers AND that driver excluded)
    owner_in_drivers_record = next(
        (md for md in mapped_drivers if md.is_owner), None
    )
    if owner_in_drivers_record is None:
        # Owner is not listed among drivers -> assume owner drives
        owner_is_driver = True
    else:
        owner_is_driver = not owner_in_drivers_record.is_excluded

    # owner_dob: GEICO Step 2 requires the owner's DOB. The BlueQuote stores
    # DOB on the driver records, not in applicant_info — so if the applicant
    # has no DOB but the owner appears in the drivers list, pull it from there.
    owner_dob = applicant.owner_dob
    if not owner_dob and owner_in_drivers_record is not None:
        owner_dob = owner_in_drivers_record.date_of_birth

    # Vehicles: prefer detailed records, otherwise synthesize from units count
    units = profile.units
    coverages = profile.coverages_detail
    fallback_zip = applicant.zip_code
    requested = profile.coverages   # list of codes like ["AL","GL","APD"]
    if units.vehicles:
        mapped_vehicles = [
            _map_vehicle(v, fallback_zip, coverages, requested)
            for v in units.vehicles
        ]
    else:
        count = max(units.count, len(units.trailer_types))
        if count <= 0:
            mapped_vehicles = []
        else:
            types = units.trailer_types or [None] * count
            mapped_vehicles = [
                _map_vehicle(
                    VehicleProfile(
                        trailer_type=types[i] if i < len(types) else None
                    ),
                    fallback_zip,
                    coverages,
                    requested,
                )
                for i in range(count)
            ]

    # Business Info buckets
    ownership_type = _derive_business_ownership_type(
        biz_name, applicant.owner_name, dba
    )
    years_op = _years_operating_bucket(applicant.business_years)
    owner_in_drv = owner_in_drivers_record is not None
    employees = _employees_bucket(len(profile.drivers), owner_in_drv)
    years_insurer = _years_with_insurer_bucket(
        applicant.years_continuous_coverage
    )
    bi_limits = _bi_limits_to_geico(coverages.bodily_injury_limit)
    has_current_ins = bool(applicant.current_carrier)

    return MappedFields(
        usdot=applicant.usdot or None,
        business_name=biz_name or None,
        zip_code=applicant.zip_code,
        effective_date=effective_date,
        owner_first_name=owner_first or None,
        owner_last_name=owner_last or None,
        owner_dob=owner_dob,
        owner_phone=applicant.phone,   # Rule 3: BlueQuote phone prevails over GEICO auto-pop
        owner_email=applicant.email,
        owner_street=applicant.street_address,
        owner_city=applicant.city,
        owner_is_driver=owner_is_driver,
        marital_status="Single",  # POLICY: always Single
        business_ownership_type=ownership_type,
        business_class=_map_commodity_to_geico_class(profile.commodity),
        has_eld=False,
        has_hazmat_placard=False,
        years_operating=years_op,
        employee_count=employees,
        has_current_insurance=has_current_ins,
        years_with_insurer=years_insurer,
        current_bi_limits=bi_limits,
        current_liability_type="None",
        needs_additional_insured=False,
        has_blanket_additional=False,
        requires_filings=False,
        has_workers_comp=False,
        vehicles=mapped_vehicles,
        drivers=mapped_drivers,
        coverages=coverages,
    )
