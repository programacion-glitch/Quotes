"""NON OWNED trailers must be removed from MappedFields.vehicles and routed
to CoveragesProfile.non_owned_trailer_phys_damage_limit."""

from __future__ import annotations

from modules.quote_profile import (
    QuoteProfile, ApplicantProfile, VehicleProfile, UnitsProfile, CoveragesProfile,
)
from modules.progressive.field_mapper import map_profile_to_fields


def _profile_with(vehicles, coverages=None):
    return QuoteProfile(
        applicant=ApplicantProfile(business_name="TEST", owner_name="OWNER"),
        units=UnitsProfile(count=len(vehicles), vehicles=vehicles),
        coverages_detail=coverages or CoveragesProfile(),
    )


def test_non_owned_trailer_removed_from_vehicles():
    """A trailer with VIN='NON OWNED' must not appear in mapped_vehicles."""
    profile = _profile_with([
        VehicleProfile(vin="1FUJGLDR8LSLT1234", year=2020, make="FREIGHT",
                       model="CASCADIA", is_trailer=False),
        VehicleProfile(vin="NON OWNED", year=2018, make="UTILITY",
                       model="END DUMP", is_trailer=True),
    ])
    fields = map_profile_to_fields(profile, effective_date="06/15/2026")
    assert len(fields.vehicles) == 1
    assert fields.vehicles[0].vin == "1FUJGLDR8LSLT1234"


def test_non_owned_bumps_coverage_to_default_when_unset():
    """non_owned_trailer_phys_damage_limit defaults to $25,000 if operator didn't set."""
    profile = _profile_with([
        VehicleProfile(vin="1FUJGLDR8LSLT1234", year=2020, make="FREIGHT",
                       model="CASCADIA", is_trailer=False),
        VehicleProfile(vin="NON OWNED", year=2018, make="UTILITY",
                       model="END DUMP", is_trailer=True),
    ])
    fields = map_profile_to_fields(profile, effective_date="06/15/2026")
    assert fields.coverages.non_owned_trailer_phys_damage_limit == "$25,000"


def test_operator_set_coverage_is_respected():
    """If the operator set non_owned coverage to $50k, do not overwrite to $25k."""
    cov = CoveragesProfile(non_owned_trailer_phys_damage_limit="$50,000")
    profile = _profile_with(
        [VehicleProfile(vin="NON OWNED", year=2018, make="X", model="Y", is_trailer=True)],
        coverages=cov,
    )
    fields = map_profile_to_fields(profile, effective_date="06/15/2026")
    assert fields.coverages.non_owned_trailer_phys_damage_limit == "$50,000"


def test_no_non_owned_means_no_coverage_bump():
    """No NON OWNED trailers → coverage stays at its prior value (None)."""
    profile = _profile_with([
        VehicleProfile(vin="1FUJGLDR8LSLT1234", year=2020, make="X", model="Y", is_trailer=False),
    ])
    fields = map_profile_to_fields(profile, effective_date="06/15/2026")
    assert fields.coverages.non_owned_trailer_phys_damage_limit is None


def test_non_owned_via_make_field():
    """Some PDFs put 'NON OWNED' in make/model instead of VIN."""
    profile = _profile_with([
        VehicleProfile(vin=None, year=2018, make="NON OWNED", model="TRAILER", is_trailer=True),
    ])
    fields = map_profile_to_fields(profile, effective_date="06/15/2026")
    assert len(fields.vehicles) == 0
    assert fields.coverages.non_owned_trailer_phys_damage_limit == "$25,000"
