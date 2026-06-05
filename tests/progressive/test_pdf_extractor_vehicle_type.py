"""Per-row vehicle/trailer Type reading in BlueQuotePDFExtractor.

The Blue Quote PDF form stores each row's Type in the field right after the VIN
(base+3). The FIRST row of each section (power units, trailers) is the
exception: its Type widget is unnamed and pdfplumber collects it under the
shared key '0' as a 2-item list = [first_power_type, first_trailer_type].

The old extractor read ALL types positionally from data_map['0'] (only 2
values), which mis-aligned multi-vehicle quotes: a 3-tractor + 1-flatbed quote
came out [Tractor, Flatbed(!), Unknown, Unknown, ...]. These tests pin the
correct per-row + first-row-from-'0' behaviour.
"""

from __future__ import annotations

from modules.pdf_extractor import BlueQuotePDFExtractor


def _extractor_with(data_map):
    ex = BlueQuotePDFExtractor.__new__(BlueQuotePDFExtractor)
    ex.data_map = data_map
    ex.type_vals = data_map.get("0", [])
    return ex


def test_multi_vehicle_types_resolve_per_row_and_from_zero():
    """TRANSMILANOS shape: 3 power units + 3 trailers; first row of each
    section comes from data_map['0'], the rest from base+3."""
    data_map = {
        "0": ["Tractor Truck", "Flatbed Trailer"],  # [first power, first trailer]
        # power rows (no '77' -> first row type comes from '0'[0])
        "74": "2018", "75": "KW T68", "76": "VIN0", "78": "80.000", "79": "10,000",
        "80": "2016", "81": "FREIGHTLINER", "82": "VIN1", "83": "Tractor Truck",
        "84": "33,000", "85": "0",
        "86": "2021", "87": "KENWORTH", "88": "VIN2", "89": "Tractor Truck",
        "90": "33,000", "91": "0",
        # trailer rows (no '107' -> first trailer type from '0'[1])
        "104": "2013", "105": "GDAN FLP", "106": "VIN3", "108": "11,100 lbs",
        "109": "10,000",
        "112": "NON OWNED", "113": "Dry Van Trailer",
        "118": "NON OWNED", "119": "Dry Van Trailer",
    }
    ex = _extractor_with(data_map)
    vehicles = ex._extract_vehicles(data_map["0"])
    trailers = ex._extract_trailers(data_map["0"], len(vehicles))

    assert [v["type"] for v in vehicles] == [
        "Tractor Truck", "Tractor Truck", "Tractor Truck",
    ]
    assert [t["type"] for t in trailers] == [
        "Flatbed Trailer", "Dry Van Trailer", "Dry Van Trailer",
    ]


def test_single_power_and_single_trailer_use_zero_slots():
    """JUAREZ shape: 1 power + 1 trailer, both first rows -> both from '0'."""
    data_map = {
        "0": ["Pickup Truck", "Gooseneck Trailer"],
        "74": "2024", "75": "RAM 250", "76": "VINP", "78": "9,000 lbs",
        "104": "2026", "105": "BIGT 16G", "106": "VINT", "108": "15,950 lbs",
    }
    ex = _extractor_with(data_map)
    vehicles = ex._extract_vehicles(data_map["0"])
    trailers = ex._extract_trailers(data_map["0"], len(vehicles))
    assert [v["type"] for v in vehicles] == ["Pickup Truck"]
    assert [t["type"] for t in trailers] == ["Gooseneck Trailer"]


def test_second_power_row_reads_per_row_not_blank_zero_slot():
    """REPUBLIC shape: 2 dump trucks, '0' = ['Dump Truck', ' '] (trailer slot is
    a blank space). Row 0 from '0'[0]; row 1 from its own base+3 — NOT the blank
    trailer slot. No trailers."""
    data_map = {
        "0": ["Dump Truck", " "],
        "74": "2012", "75": "KW", "76": "VIN0", "78": "51.000 LBS", "79": "$45.000",
        "80": "2012", "81": "KW", "82": "VIN1", "83": "Dump Truck",
        "84": "51.000 LBS", "85": "$45.000",
    }
    ex = _extractor_with(data_map)
    vehicles = ex._extract_vehicles(data_map["0"])
    assert [v["type"] for v in vehicles] == ["Dump Truck", "Dump Truck"]


def test_genuinely_blank_type_stays_unknown():
    """No per-row type and no '0' slot available -> Unknown (fail-loud catches it)."""
    data_map = {
        "0": [],
        "74": "2018", "75": "KW T68", "76": "VIN0", "78": "80.000",
        "80": "2016", "81": "FRHT", "82": "VIN1", "84": "33,000",
    }
    ex = _extractor_with(data_map)
    vehicles = ex._extract_vehicles(data_map["0"])
    assert [v["type"] for v in vehicles] == ["Unknown", "Unknown"]
