"""NON OWNED trailers must be removed from MappedFields.vehicles and routed
to CoveragesProfile.non_owned_trailer_phys_damage_limit."""

from __future__ import annotations

from modules.quote_profile import (
    QuoteProfile, ApplicantProfile, VehicleProfile, UnitsProfile, CoveragesProfile,
    DriverProfile,
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


def test_non_owner_spelling_variant_is_non_owned():
    """Live (SHALOM WAY): the Blue Quote VIN field read 'NON OWNER' — a spelling
    variant of NON OWNED. It must route to non-owned coverage, not be treated as
    a real trailer to add (which would fail with no VIN/make)."""
    profile = _profile_with([
        VehicleProfile(vin="1FUJGLDR8LSLT1234", year=2020, make="KW",
                       model="T680", is_trailer=False),
        VehicleProfile(vin="NON OWNER", year=2026, make=None,
                       model=None, is_trailer=True),
    ])
    fields = map_profile_to_fields(profile, effective_date="06/15/2026")
    assert len(fields.vehicles) == 1
    assert fields.vehicles[0].vin == "1FUJGLDR8LSLT1234"
    assert fields.coverages.non_owned_trailer_phys_damage_limit == "$25,000"


def test_non_owned_via_make_field():
    """Some PDFs put 'NON OWNED' in make/model instead of VIN."""
    profile = _profile_with([
        VehicleProfile(vin=None, year=2018, make="NON OWNED", model="TRAILER", is_trailer=True),
    ])
    fields = map_profile_to_fields(profile, effective_date="06/15/2026")
    assert len(fields.vehicles) == 0
    assert fields.coverages.non_owned_trailer_phys_damage_limit == "$25,000"


def test_vin_less_powered_vehicle_is_not_non_owned():
    """Regression: a powered vehicle with no extracted VIN must NOT be
    classified as NON OWNED — that's a PDF extraction gap, not a coverage
    routing signal.
    """
    profile = _profile_with([
        VehicleProfile(vin=None, year=2020, make="FREIGHTLINER",
                       model="CASCADIA", is_trailer=False),
    ])
    fields = map_profile_to_fields(profile, effective_date="06/15/2026")
    assert len(fields.vehicles) == 1
    assert fields.vehicles[0].make == "FREIGHTLINER"
    assert fields.coverages.non_owned_trailer_phys_damage_limit is None


def test_vin_less_trailer_with_normal_make_is_not_non_owned():
    """A trailer with no VIN but a normal make/model is still an owned
    trailer, not a NON OWNED marker. (NOTE: it will be a Phase 1 add-trailer
    candidate; only the make/model 'NON OWNED' string flips routing.)
    """
    profile = _profile_with([
        VehicleProfile(vin=None, year=2018, make="UTILITY",
                       model="DRY VAN", is_trailer=True),
    ])
    fields = map_profile_to_fields(profile, effective_date="06/15/2026")
    assert len(fields.vehicles) == 1
    assert fields.coverages.non_owned_trailer_phys_damage_limit is None


def test_empty_string_vin_with_normal_make_is_not_non_owned():
    """Equivalent to vin=None but as empty string — still an extraction
    artifact, not a NON OWNED signal."""
    profile = _profile_with([
        VehicleProfile(vin="", year=2020, make="FREIGHTLINER",
                       model="CASCADIA", is_trailer=False),
    ])
    fields = map_profile_to_fields(profile, effective_date="06/15/2026")
    assert len(fields.vehicles) == 1
    assert fields.coverages.non_owned_trailer_phys_damage_limit is None


def test_owner_dob_sourced_from_driver_despite_middle_name_mismatch():
    """Live (JOSE DELGADO, Sole Proprietor): owner 'JOSE ANDRES DELGADO' vs
    driver 'JOSE A DELGADO'. The owner DOB (required by Progressive's START
    page) comes from the matching driver — an exact-name match missed it and
    left DOB blank. First+last token match must still identify the owner driver.
    """
    profile = QuoteProfile(
        applicant=ApplicantProfile(
            business_name="JOSE A DELGADO", owner_name="JOSE ANDRES DELGADO",
            usdot="2896210",
        ),
        units=UnitsProfile(count=1, vehicles=[
            VehicleProfile(vin="1FUJGLDR8LSLT1234", year=2018, make="FRHT",
                           model="DUMP", is_trailer=False),
        ]),
        drivers=[
            DriverProfile(name="JOSE A DELGADO", date_of_birth="03/07/1969",
                          license_number="X", license_state="Texas"),
        ],
        coverages_detail=CoveragesProfile(),
    )
    fields = map_profile_to_fields(profile, effective_date="06/15/2026")
    assert fields.owner_dob == "03/07/1969"
    assert fields.drivers[0].is_policyholder is True


def test_owner_dob_matches_two_surname_hispanic_name():
    """Live (KATYLAND): owner 'JERSSON MEDINA' (one surname) vs driver
    'JERSSON STIVEN MEDINA ROBAYO' (two surnames). First+last token match
    misses (MEDINA != ROBAYO); first-name + shared-surname must still match so
    the owner DOB is sourced from the driver."""
    profile = QuoteProfile(
        applicant=ApplicantProfile(
            business_name="KATYLAND TRANSPORT INC",
            owner_name="JERSSON MEDINA", usdot="4576096",
        ),
        units=UnitsProfile(count=1, vehicles=[
            VehicleProfile(vin="1FUJGLDR8LSLT1234", year=2020, make="FRHT",
                           model="CASCADIA", is_trailer=False),
        ]),
        drivers=[
            DriverProfile(name="JERSSON STIVEN MEDINA ROBAYO",
                          date_of_birth="12/11/1992", license_number="X",
                          license_state="Texas"),
        ],
        coverages_detail=CoveragesProfile(),
    )
    fields = map_profile_to_fields(profile, effective_date="06/15/2026")
    assert fields.owner_dob == "12/11/1992"
    assert fields.drivers[0].is_policyholder is True


def test_different_people_same_first_name_not_matched():
    """Two different people who share only a first name must NOT match (the
    surname-overlap guard prevents a wrong policyholder/DOB)."""
    profile = QuoteProfile(
        applicant=ApplicantProfile(business_name="X", owner_name="JUAN GARCIA",
                                   usdot="1"),
        units=UnitsProfile(count=1, vehicles=[
            VehicleProfile(vin="1FUJGLDR8LSLT1234", year=2020, make="X",
                           model="Y", is_trailer=False),
        ]),
        drivers=[
            DriverProfile(name="JUAN LOPEZ", date_of_birth="01/01/1980",
                          license_number="X", license_state="Texas"),
        ],
        coverages_detail=CoveragesProfile(),
    )
    fields = map_profile_to_fields(profile, effective_date="06/15/2026")
    assert fields.drivers[0].is_policyholder is False


def test_usdot_trailing_space_is_stripped():
    """Live (SHALOM WAY): usdot extracted as '4518340 ' (trailing space) made
    Progressive reject the lookup as 'not a valid USDOT number'. It must be
    stripped before use."""
    profile = QuoteProfile(
        applicant=ApplicantProfile(business_name="X", owner_name="O", usdot="4518340 "),
        units=UnitsProfile(count=1, vehicles=[
            VehicleProfile(vin="1ABCDEFGHJKLMNPRS", year=2024, make="KW", model="T680", is_trailer=False),
        ]),
        coverages_detail=CoveragesProfile(),
    )
    fields = map_profile_to_fields(profile, effective_date="06/15/2026")
    assert fields.usdot == "4518340"


def test_missing_commodity_with_usdot_defaults_to_trucker():
    """A PDF that omits commodity but provides a USDOT must default to
    'Trucker' so Progressive's required Business Type combobox is filled."""
    profile = QuoteProfile(
        applicant=ApplicantProfile(
            business_name="JUAREZ LOGISTICS LLC",
            owner_name="OWNER",
            usdot="4535088",
        ),
        units=UnitsProfile(count=1, vehicles=[
            VehicleProfile(vin="3C6UR5FL8RG195691", year=2024, make="RAM", model="250", is_trailer=False),
        ]),
        coverages_detail=CoveragesProfile(),
    )
    profile.commodity = ""   # missing in PDF
    fields = map_profile_to_fields(profile, effective_date="06/15/2026")
    assert fields.commodity == "Trucker"


def test_explicit_commodity_wins_over_trucker_default():
    """Explicit commodity from the PDF is preserved even when USDOT is present."""
    profile = QuoteProfile(
        applicant=ApplicantProfile(
            business_name="X", owner_name="O", usdot="123",
        ),
        units=UnitsProfile(count=1, vehicles=[
            VehicleProfile(vin="1ABCDEFGHJKLMNPRS", year=2024, make="X", model="Y", is_trailer=False),
        ]),
        coverages_detail=CoveragesProfile(),
    )
    profile.commodity = "Dirt Sand & Gravel"
    fields = map_profile_to_fields(profile, effective_date="06/15/2026")
    assert fields.commodity == "Dirt Sand & Gravel"


def test_no_commodity_no_usdot_stays_none():
    """If neither commodity nor USDOT exist, do not invent a 'Trucker' default —
    something is wrong upstream and the bot should fail loudly later (USDOT is
    actually required to quote, so this case mostly never happens)."""
    profile = QuoteProfile(
        applicant=ApplicantProfile(business_name="X", owner_name="O"),
        units=UnitsProfile(count=1, vehicles=[
            VehicleProfile(vin="1ABCDEFGHJKLMNPRS", year=2024, make="X", model="Y", is_trailer=False),
        ]),
        coverages_detail=CoveragesProfile(),
    )
    profile.commodity = ""
    fields = map_profile_to_fields(profile, effective_date="06/15/2026")
    assert fields.commodity is None
