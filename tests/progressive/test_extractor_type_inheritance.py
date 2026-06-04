"""Sibling type inheritance for whitespace/empty vehicle Type cells.

Blue Quote fillers often leave a repeated row's Type cell blank ("same as
above"); the PDF form field then holds ' ' and extraction yields None even
though the row renders the type visually. Confirmed live: REPUBLIC AGGREGATE,
two identical 2012 KW dump trucks where the 2nd Type form field is a space
(type_vals = ['Dump Truck', ' ']). A vehicle with a missing type inherits from
an earlier identical sibling (same year+make) in the SAME group.
"""

from __future__ import annotations

from modules.document_ai_extractor import DocumentAIExtractor


def test_whitespace_type_inherits_from_identical_sibling():
    extracted = {
        "vehicles": {
            "tractors_trucks_pickup": [
                {"year": "2012", "make": "KW", "vin": "1XKDDP9XXCJ329791",
                 "type": "Dump Truck", "gvw": "51.000 LBS", "value": "$45.000"},
                {"year": "2012", "make": "KW", "vin": "1XKDDP9X3CJ329793",
                 "type": " ", "gvw": "51.000 LBS", "value": "$45.000"},
            ],
            "trailers": [],
        },
    }
    recs = DocumentAIExtractor._build_vehicle_records_from_dict(extracted)
    assert recs[0].trailer_type == "DUMP TRUCK"
    assert recs[1].trailer_type == "DUMP TRUCK"   # inherited from identical sibling


def test_no_inheritance_across_different_year_make():
    extracted = {
        "vehicles": {
            "tractors_trucks_pickup": [
                {"year": "2012", "make": "KW", "vin": "A", "type": "Dump Truck"},
                {"year": "2020", "make": "FORD", "vin": "B", "type": " "},
            ],
            "trailers": [],
        },
    }
    recs = DocumentAIExtractor._build_vehicle_records_from_dict(extracted)
    assert recs[0].trailer_type == "DUMP TRUCK"
    assert recs[1].trailer_type is None   # different vehicle -> no guess


def test_trailer_does_not_inherit_truck_type():
    extracted = {
        "vehicles": {
            "tractors_trucks_pickup": [
                {"year": "2012", "make": "KW", "vin": "A", "type": "Dump Truck"},
            ],
            "trailers": [
                {"year": "2012", "make": "KW", "vin": "B", "type": " "},
            ],
        },
    }
    recs = DocumentAIExtractor._build_vehicle_records_from_dict(extracted)
    assert recs[0].trailer_type == "DUMP TRUCK"
    assert recs[1].is_trailer is True
    assert recs[1].trailer_type is None   # scoped within group, not across
