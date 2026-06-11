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
from modules.progressive.unit_matching import NON_OWNED_MARKERS, looks_non_owned


@dataclass
class MappedVehicle:
    """Vehicle data ready to be filled in Progressive AddVehicle form."""
    vin: Optional[str] = None
    year: Optional[int] = None
    make: Optional[str] = None
    model: Optional[str] = None
    trailer_type: str = "FLATBED"
    gvw: Optional[str] = None       # raw Blue Quote GVW; resolved by resolve_gvw
    radius_miles: str = "Over 500 miles"
    has_loan: str = "No"           # "No" | "Loan" | "Lease"
    garaging_zip: Optional[str] = None
    value: Optional[str] = None    # Blue Quote "Value" column. If set, the
                                   # customer wants APD (Comp+Coll); fill this
                                   # value in the Vehicle Value textbox. If
                                   # None, set Comp/Coll = No (liability-only).
    # Propagated from VehicleProfile by _map_vehicle. Drives the powered-vs-
    # trailer split in quote_flow._add_all_vehicles (replaces substring heuristic).
    is_trailer: bool = False


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
    owner_phone: Optional[str] = None      # e.g. "(210) 668-1522" — REQUIRED on START page (2026-06)
    owner_email: Optional[str] = None
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

def _is_non_owned(
    vin: Optional[str], make: Optional[str], model: Optional[str]
) -> bool:
    """True when the unit is a 'non-owned' trailer marker — must be routed
    to Non-Owned Trailer Phys Damage coverage instead of Add Trailer.

    Detection by vin first (only when the VIN field is non-empty and matches
    a known marker like 'NON OWNED' / 'NONOWNED' / 'N/A'), then make/model
    fallback (some PDFs surface the marker on a different column). A unit
    with NO vin AND no NON OWNED text in make/model is NOT classified as
    non-owned — that's just an extraction gap, not a non-ownership signal.
    """
    vin_clean = (vin or "").strip().upper()
    if vin_clean and (vin_clean in NON_OWNED_MARKERS or looks_non_owned(vin_clean)):
        return True
    for s in (make, model):
        if s and looks_non_owned(s):
            return True
    return False


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
        gvw=(v.gvw or None),               # raw; resolve_gvw defaults if absent
        radius_miles=v.radius_miles or "Over 500 miles",
        has_loan=has_loan,
        garaging_zip=v.garaging_zip or fallback_zip,
        value=(v.value or None),           # raw; resolve_vehicle_value validates
        is_trailer=v.is_trailer,
    )


def _same_person(a: Optional[str], b: Optional[str]) -> bool:
    """True if two names denote the same person, tolerant of the variants the
    owner section and the driver row disagree on (the owner's DOB is sourced
    from the matching driver; a miss leaves DOB blank and Progressive rejects
    the START page). Match = same FIRST name AND at least one shared surname
    token. This covers:
      - middle name vs initial:   'JOSE ANDRES DELGADO' ~ 'JOSE A DELGADO'
      - one vs two surnames:      'JERSSON MEDINA' ~ 'JERSSON STIVEN MEDINA ROBAYO'
      - extra/absent middle name: 'JUAN ROJAS' ~ 'JUAN QUEVEDO ROJAS'
    """
    if not a or not b:
        return False
    ta = a.strip().upper().split()
    tb = b.strip().upper().split()
    if not ta or not tb:
        return False
    if ta == tb:
        return True

    def first_substantive(tokens: list) -> str:
        """First token that isn't a single-letter initial ('J', 'A.') —
        driver rows sometimes lead with one ('J ANTONIO GONZALEZ' vs owner
        'ANTONIO S GONZALEZ', live 2026-06-10)."""
        for t in tokens:
            if len(t.rstrip(".")) > 1:
                return t
        return tokens[0]

    fa, fb = first_substantive(ta), first_substantive(tb)
    if fa != fb:
        return False
    # Beyond the first name, require at least one shared surname/middle token
    # (drop only the matched first-name occurrence; surnames can repeat).
    ra, rb = list(ta), list(tb)
    ra.remove(fa)
    rb.remove(fb)
    return bool(set(ra) & set(rb))


_US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
    "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "DC": "District of Columbia",
}


def _normalize_license_state(raw: Optional[str]) -> str:
    """'GA' -> 'Georgia'. Feeding abbreviations to the License State combo's
    tolerant partial match is a trap: 'GA' substring-matched 'MichiGAn' live
    (DDH driver 4, 2026-06-10) and the license number then failed validation
    for the wrong state. Full names pass through unchanged."""
    s = (raw or "").strip()
    if not s:
        return "Texas"
    return _US_STATES.get(s.upper(), s)


def _map_driver(d: DriverProfile, owner_name: Optional[str]) -> MappedDriver:
    """Map a DriverProfile to MappedDriver."""
    is_owner = _same_person(owner_name, d.name)
    return MappedDriver(
        name=d.name,
        license_state=_normalize_license_state(d.license_state),
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

    # Route NON OWNED trailers to Non-Owned Trailer Phys Damage coverage —
    # Progressive's Add Trailer form requires a real VIN. The rates-page
    # handler at coverages_rates_page.py:1030 picks up the bumped limit.
    non_owned_count = sum(
        1 for mv in mapped_vehicles if _is_non_owned(mv.vin, mv.make, mv.model)
    )
    mapped_vehicles = [
        mv for mv in mapped_vehicles if not _is_non_owned(mv.vin, mv.make, mv.model)
    ]
    coverages_out = profile.coverages_detail
    if non_owned_count and not coverages_out.non_owned_trailer_phys_damage_limit:
        # CoveragesProfile is a dataclass; mutate the field on the existing
        # instance so RATES picks it up. Tests confirm the default does not
        # override an operator-set value.
        coverages_out.non_owned_trailer_phys_damage_limit = "$25,000"
        print(
            f"    [Progressive] field_mapper: {non_owned_count} NON OWNED "
            f"trailer(s) -> Non-Owned Trailer Phys Damage = $25,000 (default)"
        )

    # Drivers
    mapped_drivers = [_map_driver(d, profile.applicant.owner_name) for d in profile.drivers]

    # Owner DOB: the BlueQuote applicant block rarely carries the owner's DOB,
    # but the owner is almost always also listed as a driver (even when excluded
    # from the policy). Progressive REQUIRES the DOB on the START page for an
    # Individual / Sole Proprietor, so fall back to the matching driver's DOB.
    owner_driver = next((d for d in mapped_drivers if d.is_policyholder), None)
    owner_dob_val = profile.applicant.owner_dob or (
        owner_driver.date_of_birth if owner_driver else None
    )

    # Commodity defaults to "Trucker" when missing — Progressive's START page
    # requires the Business Type combobox to be filled, and any quote with a
    # valid USDOT is, by definition, a trucking operation. Without this default,
    # PDFs that omit the commodity column block at START with "This field is
    # required". Explicit commodities from the PDF win over the default.
    commodity_resolved = (profile.commodity or "").strip() or None
    if not commodity_resolved and (profile.applicant.usdot or "").strip():
        commodity_resolved = "Trucker"
        print(
            "    [Progressive] field_mapper: commodity unset in PDF; "
            "defaulting to 'Trucker' (USDOT present)"
        )

    return MappedFields(
        # Strip: a trailing space ('4518340 ') makes Progressive reject the
        # lookup as "not a valid USDOT number". Defensive across extraction paths.
        usdot=(profile.applicant.usdot or "").strip() or None,
        business_name=biz_name or None,
        effective_date=effective_date,
        entity_type=entity,
        state="TX",
        owner_name=profile.applicant.owner_name or None,
        owner_dob=owner_dob_val,
        owner_street=profile.applicant.street_address,
        owner_city=profile.applicant.city,
        owner_zip=profile.applicant.zip_code,
        owner_phone=profile.applicant.phone,
        owner_email=profile.applicant.email,
        commodity=commodity_resolved,
        dba_name=dba,
        vehicles=mapped_vehicles,
        drivers=mapped_drivers,
        coverages=coverages_out,
    )
