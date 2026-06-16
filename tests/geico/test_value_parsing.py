"""Regression tests for GEICO vehicle-value parsing + the comp/coll guard.

Root cause (live JERO'S/DIBOLL 2026-06-16): the BlueQuote writes values in
latino format ("$10.000" = $10,000, dot = thousands separator). GEICO's
`_parse_value_amount` did `str(raw).split(".")[0]` -> "$10" -> "10", scaling the
value down 1000x. A value of $10 (<= the $1,000 comp/coll deductible) then trips
GEICO's "Stated amount cannot be the same or less than selected deductibles"
validation at Step 6, leaving the premium dirty (Recalculate never clears, Next
never advances). Progressive's `parse_amount` already disambiguates dot/comma.
"""

from modules.geico.field_mapper import _parse_value_amount, _map_vehicle
from modules.quote_profile import VehicleProfile, CoveragesProfile


# ---- _parse_value_amount: latino + US number formats ----

def test_latino_thousands_dot():
    # "$10.000" is $10,000 (dot = thousands separator), NOT $10.
    assert _parse_value_amount("$10.000") == "10000"
    assert _parse_value_amount("$40.000") == "40000"
    assert _parse_value_amount("$8.000") == "8000"


def test_us_format_comma_thousands():
    assert _parse_value_amount("$45,000.00") == "45000"
    assert _parse_value_amount("$45,000") == "45000"
    assert _parse_value_amount("45000") == "45000"


def test_none_and_garbage_are_none():
    assert _parse_value_amount(None) is None
    assert _parse_value_amount("") is None
    assert _parse_value_amount("$0") is None


def test_clamped_to_geico_max():
    assert _parse_value_amount("$5,000,000") == "999000"


# ---- comp/coll guard: value <= deductible cannot carry physical damage ----

def test_comp_coll_dropped_when_value_at_or_below_deductible():
    # $500 <= $1,000 default deductible -> liability-only (GEICO would reject).
    v = VehicleProfile(value="$500")
    mv = _map_vehicle(v, "77001", CoveragesProfile(), requested_coverages=["APD"])
    assert mv.has_comp_coll is False


def test_comp_coll_kept_when_value_above_deductible_latino():
    # "$10.000" = $10,000 > $1,000 deductible -> comp/coll stays, value correct.
    v = VehicleProfile(value="$10.000")
    mv = _map_vehicle(v, "77001", CoveragesProfile(), requested_coverages=["APD"])
    assert mv.has_comp_coll is True
    assert mv.value == "10000"


def test_no_value_is_liability_only():
    v = VehicleProfile(value=None)
    mv = _map_vehicle(v, "77001", CoveragesProfile(), requested_coverages=["APD"])
    assert mv.has_comp_coll is False
    assert mv.value is None
