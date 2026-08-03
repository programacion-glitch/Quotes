"""
R-085 (Diana 2026-08-03, PANTHER): el zip de garaging de los vehículos debe
salir de la PHYSICAL address, no de la mailing. Cubre el parser de dirección
y el fallback_zip de ambos field mappers (Progressive y GEICO).
"""

from modules.document_ai_extractor import _parse_us_address
from modules.quote_profile import (
    QuoteProfile,
    ApplicantProfile,
    UnitsProfile,
    VehicleProfile,
)
from modules.progressive import field_mapper as prog_mapper
from modules.geico import field_mapper as geico_mapper


def _profile(physical_zip, mailing_zip="77095"):
    return QuoteProfile(
        applicant=ApplicantProfile(
            business_name="PANTHER EXPRESS TRUCKING LLC",
            owner_name="Juan Perez",
            usdot="4514637",
            zip_code=mailing_zip,
            physical_zip=physical_zip,
            state="TX",
        ),
        commodity="GENERAL FREIGHT",
        coverages=["AL"],
        units=UnitsProfile(
            count=1,
            trailer_types=["DRY VAN"],
            vehicles=[VehicleProfile(vin="1XKYD49X6LJ353747", year=2020,
                                     make="KENWORTH", trailer_type="TRACTOR")],
        ),
    )


class TestParsePhysicalAddress:
    def test_panther_physical_lowercase(self):
        """La physical de PANTHER viene en minúsculas y sin comas estándar."""
        _, _, state, zipc = _parse_us_address("7800 Wright rd, houston tx 77041")
        assert state == "TX"
        assert zipc == "77041"


class TestProgressiveGaragingZip:
    def test_prefers_physical_zip(self):
        fields = prog_mapper.map_profile_to_fields(_profile("77041"))
        assert fields.vehicles[0].garaging_zip == "77041"

    def test_falls_back_to_mailing_when_physical_missing(self):
        fields = prog_mapper.map_profile_to_fields(_profile(None))
        assert fields.vehicles[0].garaging_zip == "77095"


class TestGeicoGaragingZip:
    def test_prefers_physical_zip(self):
        fields = geico_mapper.map_profile_to_fields(_profile("77041"))
        assert fields.vehicles[0].garaging_zip == "77041"

    def test_falls_back_to_mailing_when_physical_missing(self):
        fields = geico_mapper.map_profile_to_fields(_profile(None))
        assert fields.vehicles[0].garaging_zip == "77095"
