"""
Field Mapper for Progressive

Maps QuoteProfile data to Progressive form field values.
HYBRID strategy: defaults for obvious fields, None for critical missing fields.
"""

from dataclasses import dataclass, field
from typing import Optional, List

from modules.quote_profile import (
    QuoteProfile,
    VehicleProfile,
    DriverProfile,
    CoveragesProfile,
)


@dataclass
class MappedVehicle:
    """Vehicle data ready to be filled in Progressive AddVehicle form."""
    vin: Optional[str] = None
    year: Optional[int] = None
    make: Optional[str] = None
    model: Optional[str] = None
    trailer_type: str = "FLATBED"
    gvw: str = "26,001 lbs or greater"
    radius_miles: str = "Over 500 miles"
    has_loan: str = "No"           # "No" | "Loan" | "Lease"
    garaging_zip: Optional[str] = None


@dataclass
class MappedDriver:
    """Driver data ready to be filled in Progressive AddDriver form."""
    name: str = ""
    license_state: str = "Texas"
    license_number: Optional[str] = None
    date_of_birth: Optional[str] = None
    exclude_from_policy: bool = False
    has_driving_history: bool = False
    is_policyholder: bool = False   # True for the owner (pre-filled by Progressive)


@dataclass
class MappedFields:
    """Progressive form field values ready to be filled."""
    # ---- Critical fields (halt if any is None) ----
    usdot: Optional[str] = None
    business_name: Optional[str] = None
    effective_date: Optional[str] = None  # mm/dd/yyyy

    # ---- BusinessOwnerInfo defaults ----
    entity_type: str = "Corporation or LLC"
    state: str = "TX"

    # ---- Applicant / owner ----
    owner_name: Optional[str] = None
    owner_dob: Optional[str] = None        # mm/dd/yyyy
    owner_street: Optional[str] = None
    owner_city: Optional[str] = None
    owner_zip: Optional[str] = None
    commodity: Optional[str] = None
    dba_name: Optional[str] = None

    # ---- Per-unit and per-driver lists ----
    vehicles: List[MappedVehicle] = field(default_factory=list)
    drivers: List[MappedDriver] = field(default_factory=list)

    # ---- Coverages ----
    coverages: CoveragesProfile = field(default_factory=CoveragesProfile)

    # ---- Critical-field detection ----

    def missing_critical(self) -> List[str]:
        """Return critical fields that block the entire quote."""
        missing = []
        if not self.usdot:
            missing.append("usdot")
        if not self.business_name:
            missing.append("business_name")
        if not self.effective_date:
            missing.append("effective_date")
        if not self.owner_name:
            missing.append("owner_name")
        if not self.vehicles:
            missing.append("vehicles (at least one)")
        return missing

    def missing_for_accurate_price(self) -> List[str]:
        """
        Fields that have defaults but materially change the premium.
        These don't block the quote but the price will be approximate.
        """
        missing = []
        if not self.owner_dob:
            missing.append("owner_dob (rates depend on driver age)")
        if not self.owner_zip:
            missing.append("owner_zip (garaging ZIP drives territory rating)")
        for i, v in enumerate(self.vehicles):
            if not v.vin and not (v.year and v.make and v.model):
                missing.append(f"vehicle[{i}].vin OR (year+make+model)")
        for i, d in enumerate(self.drivers):
            if not d.license_number:
                missing.append(f"driver[{i}].license_number (MVR lookup will fail without it)")
            if not d.date_of_birth and not d.is_policyholder:
                missing.append(f"driver[{i}].date_of_birth")
        return missing


# ---------- Mapping helpers --------------------------------------------------

def _map_vehicle(v: VehicleProfile, fallback_zip: Optional[str], fallback_type: str) -> MappedVehicle:
    """Map a single VehicleProfile to MappedVehicle, applying defaults."""
    loan_map = {"loan": "Loan", "lease": "Lease", "no": "No", "": "No", None: "No"}
    loan_raw = (v.has_loan or "No").lower()
    has_loan = loan_map.get(loan_raw, "No")

    return MappedVehicle(
        vin=v.vin,
        year=v.year,
        make=v.make,
        model=v.model,
        trailer_type=(v.trailer_type or fallback_type or "FLATBED"),
        gvw=v.gvw or "26,001 lbs or greater",
        radius_miles=v.radius_miles or "Over 500 miles",
        has_loan=has_loan,
        garaging_zip=v.garaging_zip or fallback_zip,
    )


def _map_driver(d: DriverProfile, owner_name: Optional[str]) -> MappedDriver:
    """Map a DriverProfile to MappedDriver."""
    is_owner = bool(
        owner_name
        and d.name
        and owner_name.strip().upper() == d.name.strip().upper()
    )
    return MappedDriver(
        name=d.name,
        license_state=d.license_state or "Texas",
        license_number=d.license_number,
        date_of_birth=d.date_of_birth,
        exclude_from_policy=d.exclude_from_policy,
        has_driving_history=d.has_accidents_or_violations or (
            d.mvr_present and not d.mvr_is_clean
        ),
        is_policyholder=is_owner,
    )


def map_profile_to_fields(
    profile: QuoteProfile,
    effective_date: Optional[str] = None,
) -> MappedFields:
    """Map a QuoteProfile to Progressive form fields."""
    biz_name = (profile.applicant.business_name or "").strip()

    # Entity type
    name_upper = biz_name.upper()
    if "LLC" in name_upper or "INC" in name_upper or "CORP" in name_upper:
        entity = "Corporation or LLC"
    else:
        entity = "Individual / Sole Proprietor"

    # DBA split
    dba = None
    if " DBA " in name_upper or " DBA:" in name_upper:
        idx = biz_name.upper().index("DBA")
        dba = biz_name[idx + 3:].strip().strip(":").strip()

    # Vehicles: prefer profile.units.vehicles, otherwise derive from trailer_types/count
    fallback_zip = profile.applicant.zip_code
    units = profile.units
    if units.vehicles:
        mapped_vehicles = [
            _map_vehicle(v, fallback_zip, units.trailer_types[i] if i < len(units.trailer_types) else "FLATBED")
            for i, v in enumerate(units.vehicles)
        ]
    else:
        # No detailed vehicle records — synthesize one placeholder per count
        count = max(units.count, len(units.trailer_types))
        types = units.trailer_types or ["FLATBED"] * count
        if not count:
            mapped_vehicles = []
        else:
            mapped_vehicles = [
                _map_vehicle(
                    VehicleProfile(trailer_type=types[i] if i < len(types) else "FLATBED"),
                    fallback_zip,
                    types[i] if i < len(types) else "FLATBED",
                )
                for i in range(count)
            ]

    # Drivers
    mapped_drivers = [_map_driver(d, profile.applicant.owner_name) for d in profile.drivers]

    return MappedFields(
        usdot=profile.applicant.usdot or None,
        business_name=biz_name or None,
        effective_date=effective_date,
        entity_type=entity,
        state="TX",
        owner_name=profile.applicant.owner_name or None,
        owner_dob=profile.applicant.owner_dob,
        owner_street=profile.applicant.street_address,
        owner_city=profile.applicant.city,
        owner_zip=profile.applicant.zip_code,
        commodity=profile.commodity or None,
        dba_name=dba,
        vehicles=mapped_vehicles,
        drivers=mapped_drivers,
        coverages=profile.coverages_detail,
    )
