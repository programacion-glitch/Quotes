"""Verify the document_ai_extractor flags trailer entries with is_trailer=True."""

from __future__ import annotations

from modules.document_ai_extractor import DocumentAIExtractor


def test_is_trailer_flag_propagates_from_structured_dict():
    """Trucks should land with is_trailer=False, trailers with is_trailer=True."""
    extracted = {
        "vehicles": {
            "tractors_trucks_pickup": [
                {"year": "2020", "make": "FREIGHTLINER", "vin": "1FUJGLDR8LSLT1234", "type": "TRACTOR"},
            ],
            "trailers": [
                {"year": "2021", "make": "UTILITY", "vin": "1UYVS253XM7301310", "type": "DRY VAN"},
            ],
        },
    }
    records = DocumentAIExtractor._build_vehicle_records_from_dict(extracted)
    assert len(records) == 2
    assert records[0].is_trailer is False
    assert records[1].is_trailer is True


def test_is_trailer_defaults_false_when_field_absent():
    """Profiles built without the extractor (older fixtures) default is_trailer=False."""
    from modules.quote_profile import VehicleProfile
    v = VehicleProfile(vin="ABC", year=2020, make="X", model="Y")
    assert v.is_trailer is False
