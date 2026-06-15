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


def test_from_dict_ignores_unknown_keys():
    # A blob from a newer schema carries a field this dataclass doesn't know.
    data = QuoteProfile().to_dict()
    data["applicant"]["some_future_field"] = "ignored"
    data["units"]["vehicles"] = [{"vin": "X", "some_future_field": 1}]
    # Must NOT raise TypeError on unknown keys.
    restored = QuoteProfile.from_dict(data)
    assert restored.applicant.business_name == ""
    assert restored.units.vehicles[0].vin == "X"


def test_from_dict_preserves_none_optionals():
    p = QuoteProfile()
    p.coverages_detail.comp_deductible = None
    p.coverages_detail.coll_deductible = None
    restored = QuoteProfile.from_dict(json.loads(json.dumps(p.to_dict())))
    assert restored.coverages_detail.comp_deductible is None
    assert restored.coverages_detail.coll_deductible is None
