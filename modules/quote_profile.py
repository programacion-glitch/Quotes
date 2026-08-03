"""
Quote Profile Data Model

Standardized data structure for all extracted document data.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Optional


def _only_fields(dc_cls, data: dict) -> dict:
    """Keep only keys that are declared fields of the dataclass dc_cls.

    Makes deserialization tolerant of unknown keys (e.g. a JSON blob written
    by a newer schema and read back by older code), instead of raising
    TypeError on an unexpected keyword argument.
    """
    valid = dc_cls.__dataclass_fields__
    return {k: v for k, v in (data or {}).items() if k in valid}


@dataclass
class DriverProfile:
    """Data extracted for a single driver."""
    name: str = ""
    cdl_present: bool = False
    cdl_years: Optional[int] = None
    cdl_class: Optional[str] = None
    cdl_is_residential: bool = False
    mvr_present: bool = False
    mvr_years_covered: Optional[int] = None
    mvr_is_clean: bool = False
    # Fields required by Progressive's AddDriver form:
    license_number: Optional[str] = None
    license_state: Optional[str] = None  # e.g. "Texas". Defaults to TX if None.
    date_of_birth: Optional[str] = None  # mm/dd/yyyy
    exclude_from_policy: bool = False
    has_accidents_or_violations: bool = False


@dataclass
class LossRunProfile:
    """Data extracted from Loss Run document."""
    present: bool = False
    years_covered: Optional[int] = None
    is_clean: bool = False
    total_claims: int = 0


@dataclass
class IftasProfile:
    """Data extracted from IFTAS document."""
    present: bool = False
    is_registered: bool = False


@dataclass
class AppProfile:
    """Data extracted from New Venture Application."""
    present: bool = False
    ein_included: bool = False
    questions_filled: bool = False


@dataclass
class ApplicantProfile:
    """Applicant info from Blue Quote."""
    business_name: str = ""
    owner_name: str = ""
    owner_age: Optional[int] = None
    usdot: str = ""
    business_years: Optional[int] = None
    is_new_venture: bool = True
    industry_experience_years: Optional[int] = None
    current_carrier: str = ""
    years_continuous_coverage: Optional[int] = None
    # Required by Progressive BusinessOwnerInfo + AddVehicle + RATES pages:
    owner_dob: Optional[str] = None       # mm/dd/yyyy
    street_address: Optional[str] = None  # garaging address (usually owner address)
    city: Optional[str] = None
    state: str = "TX"                     # default; overridden by extractor when address parses
    zip_code: Optional[str] = None        # 5-digit ZIP
    # R-085 (Diana 2026-08-03, PANTHER): el garaging de vehículos usa el zip de
    # la PHYSICAL address; street/city/zip de arriba siguen siendo el contacto
    # (mailing-first). Fallback: zip del mailing si la physical no parsea.
    physical_zip: Optional[str] = None
    # Added 2026-05-28 for GEICO (Step 2 form needs explicit phone/email).
    # Source: Blue Quote applicant_info.phone / applicant_info.email.
    phone: Optional[str] = None           # e.g. "(409) 656-7240"
    email: Optional[str] = None           # owner/contact email


@dataclass
class VehicleProfile:
    """Per-vehicle data required by Progressive AddVehicle form."""
    vin: Optional[str] = None             # 17-char VIN; if present, lookup auto-populates Y/M/M
    year: Optional[int] = None
    make: Optional[str] = None
    model: Optional[str] = None
    trailer_type: Optional[str] = None    # e.g. FLATBED, DRY VAN, REEFER, PICKUP, TRACTOR
    gvw: Optional[str] = None             # e.g. "26,001 lbs or greater"
    radius_miles: Optional[str] = None    # e.g. "Over 500 miles"
    has_loan: str = "No"                  # "No" | "Loan" | "Lease"
    garaging_zip: Optional[str] = None    # defaults to applicant.zip_code if None
    value: Optional[str] = None           # Vehicle/Trailer market value from Blue Quote
                                          # "Value" column. Presence implies the customer
                                          # wants APD (Comprehensive + Collision); absence
                                          # means liability-only.
    # Explicit trailer flag set by the extractor when this VehicleProfile
    # came from the trailer table (vs. the trucks/tractors/pickups table).
    # Eliminates the previous _looks_like_trailer substring heuristic.
    is_trailer: bool = False


@dataclass
class UnitsProfile:
    """Vehicle/trailer info."""
    count: int = 0
    trailer_types: List[str] = field(default_factory=list)
    vehicles: List[VehicleProfile] = field(default_factory=list)


@dataclass
class ConfidenceFlag:
    """A flag indicating extraction uncertainty."""
    field: str
    reason: str


@dataclass
class ExtractionConfidence:
    """Overall extraction confidence."""
    overall: str = "high"  # "high" or "low"
    flags: List[ConfidenceFlag] = field(default_factory=list)


@dataclass
class CoveragesProfile:
    """Coverage limits and add-on coverages requested in the blue quote.

    Defaults reflect the most common Texas trucking quote (1M CSL liability,
    Comp/Coll with $1k deductibles, no extras).
    """
    # Primary auto liability
    bodily_injury_limit: str = "$1,000,000 CSL"   # e.g. "$1,000,000 CSL", "$300,000/$500,000"
    property_damage_limit: Optional[str] = None    # if separate from BI; usually CSL combined

    # Physical damage
    comp_deductible: Optional[str] = "$1,000"     # None = decline comp
    coll_deductible: Optional[str] = "$1,000"     # None = decline collision

    # Per-vehicle add-ons (apply to ALL vehicles)
    medical_payments_limit: Optional[str] = None         # e.g. "$5,000". None = decline
    rental_reimbursement_limit: Optional[str] = None     # e.g. "$30 per day, $900 max"
    roadside_assistance: str = "Selected w/ $250 Deductible"  # Diana 2026-06-25: debe ir seleccionado
    fire_theft_cac: Optional[str] = None                 # Fire & Theft w/ CAC limit; None = decline

    # Cargo
    motor_truck_cargo_limit: Optional[str] = None  # e.g. "$100,000". None = no MTC

    # Non-Owned Trailer Physical Damage
    non_owned_trailer_phys_damage_limit: Optional[str] = None  # e.g. "$25,000"
    # Progressive's subform asks for the COUNT, not a limit (live 2026-06-11).
    non_owned_trailer_count: int = 0

    # Trailer Interchange (BQ field 159, e.g. "$20.000" handwritten)
    trailer_interchange_limit: Optional[str] = None

    # Hired Auto Liability (see imagenesprogressive/image.png)
    hired_auto: bool = False
    hired_auto_spent_last_year: str = "$5,000 or less"   # "$5,000 or less" | "More than $5,000"
    hired_auto_contractual: bool = False
    hired_auto_brokers_trips: bool = False
    hired_auto_count_last_year: str = "1-2"              # "1-2" | "3-5" | ...
    hired_auto_freight_broker: bool = False
    hired_auto_limit: str = "Matching Bodily Injury and Property Damage Limits"

    # Employer Non-Owned Auto Liability (see imagenesprogressive/unnamed.webp)
    non_owned_auto: bool = False
    non_owned_used_in_business: bool = True
    non_owned_frequency: str = "3 or Less days a week"   # "3 or Less days a week" | "More than 3 days a week"
    non_owned_people_count: str = "0-10"                 # "0-10" | "11-25" | ...
    non_owned_limit: str = "Matching Bodily Injury and Property Damage Limits"

    # UM/UIM and PIP - leave None to use Progressive's default (no coverage)
    uninsured_motorist_limit: Optional[str] = None
    personal_injury_protection_limit: Optional[str] = None


@dataclass
class QuoteProfile:
    """Complete quote profile assembled from all 6 documents."""
    applicant: ApplicantProfile = field(default_factory=ApplicantProfile)
    commodity: str = ""
    coverages: List[str] = field(default_factory=list)
    coverages_detail: CoveragesProfile = field(default_factory=CoveragesProfile)
    units: UnitsProfile = field(default_factory=UnitsProfile)
    drivers: List[DriverProfile] = field(default_factory=list)
    loss_run: LossRunProfile = field(default_factory=LossRunProfile)
    iftas: IftasProfile = field(default_factory=IftasProfile)
    app: AppProfile = field(default_factory=AppProfile)
    documents_present: List[str] = field(default_factory=list)
    extraction_confidence: ExtractionConfidence = field(default_factory=ExtractionConfidence)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "QuoteProfile":
        """Reconstruct a QuoteProfile from the dict produced by to_dict().

        Inverse of to_dict(): rebuilds every nested dataclass. Tolerates
        missing keys (falls back to dataclass defaults) so an empty dict
        yields a default profile. Also ignores unrecognized keys so a blob
        written by a newer schema can be read back by older code without
        raising TypeError.
        """
        data = dict(data or {})

        units_data = dict(data.get("units", {}) or {})
        units = UnitsProfile(
            count=units_data.get("count", 0),
            trailer_types=list(units_data.get("trailer_types", []) or []),
            vehicles=[VehicleProfile(**_only_fields(VehicleProfile, v)) for v in units_data.get("vehicles", []) or []],
        )

        conf_data = dict(data.get("extraction_confidence", {}) or {})
        extraction_confidence = ExtractionConfidence(
            overall=conf_data.get("overall", "high"),
            flags=[ConfidenceFlag(**_only_fields(ConfidenceFlag, f)) for f in conf_data.get("flags", []) or []],
        )

        return cls(
            applicant=ApplicantProfile(**_only_fields(ApplicantProfile, data.get("applicant", {}) or {})),
            commodity=data.get("commodity", ""),
            coverages=list(data.get("coverages", []) or []),
            coverages_detail=CoveragesProfile(**_only_fields(CoveragesProfile, data.get("coverages_detail", {}) or {})),
            units=units,
            drivers=[DriverProfile(**_only_fields(DriverProfile, d)) for d in data.get("drivers", []) or []],
            loss_run=LossRunProfile(**_only_fields(LossRunProfile, data.get("loss_run", {}) or {})),
            iftas=IftasProfile(**_only_fields(IftasProfile, data.get("iftas", {}) or {})),
            app=AppProfile(**_only_fields(AppProfile, data.get("app", {}) or {})),
            documents_present=list(data.get("documents_present", []) or []),
            extraction_confidence=extraction_confidence,
        )
