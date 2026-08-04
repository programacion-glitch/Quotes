"""R-078 (Diana 2026-08-04): filings de GEICO según radio y TXDOT# de la
Blue Quote. Interestatal/ilimitado → Yes solo MC; intraestatal con TXDOT#
→ Yes + TXDMV; sin TXDOT activo → No por el momento."""

from modules.geico import field_mapper as geico_mapper
from modules.quote_profile import (
    QuoteProfile,
    ApplicantProfile,
    UnitsProfile,
    VehicleProfile,
)


def _profile(txdot=None, radius="0-50 miles"):
    return QuoteProfile(
        applicant=ApplicantProfile(
            business_name="PANTHER EXPRESS TRUCKING LLC", owner_name="O",
            usdot="4514637", txdot=txdot, zip_code="77095", state="TX",
        ),
        commodity="GENERAL FREIGHT",
        coverages=["AL"],
        units=UnitsProfile(
            count=1, trailer_types=["DRY VAN"],
            vehicles=[VehicleProfile(vin="1XKYD49X6LJ353747", year=2020,
                                     trailer_type="TRACTOR",
                                     radius_miles=radius)],
        ),
    )


def test_interestatal_ilimitado_yes_solo_mc():
    fields = geico_mapper.map_profile_to_fields(_profile(radius="Unlimited"))
    assert fields.requires_filings is True
    assert fields.filing_mode == "MC"
    assert fields.txdmv_number is None


def test_mas_de_500_millas_yes_solo_mc():
    fields = geico_mapper.map_profile_to_fields(
        _profile(radius="More than 500 miles"))
    assert fields.filing_mode == "MC"


def test_intraestatal_con_txdot_yes_txdmv():
    fields = geico_mapper.map_profile_to_fields(
        _profile(txdot="9876543", radius="0-50 miles"))
    assert fields.requires_filings is True
    assert fields.filing_mode == "TXDMV"
    assert fields.txdmv_number == "9876543"


def test_intraestatal_txdot_na_queda_en_no():
    """PANTHER: TXDOT# = N/A → 'se deja como NO por el momento'."""
    fields = geico_mapper.map_profile_to_fields(
        _profile(txdot="N/A", radius="0-50 miles"))
    assert fields.requires_filings is False
    assert fields.filing_mode is None


def test_intraestatal_sin_txdot_queda_en_no():
    fields = geico_mapper.map_profile_to_fields(_profile(txdot=None))
    assert fields.requires_filings is False
