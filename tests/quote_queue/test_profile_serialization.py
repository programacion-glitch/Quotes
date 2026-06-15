import json

from modules.quote_profile import (
    QuoteProfile, ApplicantProfile, VehicleProfile, UnitsProfile,
    DriverProfile, ConfidenceFlag, ExtractionConfidence,
)


def _sample_profile() -> QuoteProfile:
    return QuoteProfile(
        applicant=ApplicantProfile(
            business_name="RYD LLC", owner_name="Jane Doe", usdot="1234567",
            state="TX", zip_code="77001", is_new_venture=False,
        ),
        commodity="Food & Beverage",
        coverages=["AL", "MTC"],
        units=UnitsProfile(
            count=2,
            trailer_types=["DRY VAN"],
            vehicles=[
                VehicleProfile(vin="1FUJGLDR4CLBP8834", year=2012, make="FREIGHTLINER"),
                VehicleProfile(is_trailer=True, trailer_type="DRY VAN"),
            ],
        ),
        drivers=[DriverProfile(name="Jane Doe", cdl_years=5, cdl_present=True)],
        documents_present=["BLUE QUOTE", "CDL"],
        extraction_confidence=ExtractionConfidence(
            overall="high",
            flags=[ConfidenceFlag(field="commodity", reason="inferred")],
        ),
    )


def test_roundtrip_through_json_preserves_data():
    original = _sample_profile()
    blob = json.dumps(original.to_dict())
    restored = QuoteProfile.from_dict(json.loads(blob))

    assert restored == original
    assert restored.applicant.business_name == "RYD LLC"
    assert restored.units.count == 2
    assert len(restored.units.vehicles) == 2
    assert restored.units.vehicles[0].vin == "1FUJGLDR4CLBP8834"
    assert restored.units.vehicles[1].is_trailer is True
    assert restored.drivers[0].cdl_years == 5
    assert restored.extraction_confidence.flags[0].field == "commodity"


def test_from_dict_on_empty_defaults():
    restored = QuoteProfile.from_dict({})
    assert restored.applicant.business_name == ""
    assert restored.units.count == 0
    assert restored.drivers == []
    assert restored.extraction_confidence.overall == "high"
