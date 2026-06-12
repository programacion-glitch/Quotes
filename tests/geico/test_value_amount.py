"""_parse_value_amount: BlueQuote 'Value' -> GEICO 'Total value' (1..999,000)."""

from __future__ import annotations

from modules.geico.field_mapper import _parse_value_amount


def test_dollar_formatted():
    assert _parse_value_amount("$45,000") == "45000"

def test_with_cents():
    assert _parse_value_amount("45000.00") == "45000"

def test_plain():
    assert _parse_value_amount("30000") == "30000"

def test_clamped_to_max():
    assert _parse_value_amount("1,500,000") == "999000"

def test_none_and_empty():
    assert _parse_value_amount(None) is None
    assert _parse_value_amount("") is None
    assert _parse_value_amount("$0") is None
    assert _parse_value_amount("n/a") is None


def test_value_presence_forces_comp_coll():
    from modules.geico.field_mapper import _map_vehicle
    from modules.quote_profile import CoveragesProfile, VehicleProfile
    v = VehicleProfile(vin="1X", value="$60,000")
    mapped = _map_vehicle(v, "77001", CoveragesProfile(), requested_coverages=[])
    assert mapped.has_comp_coll is True   # value present -> APD
    assert mapped.value == "60000"
