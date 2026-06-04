import pytest
from modules.progressive.vehicle_amounts import resolve_vehicle_value
from modules.progressive.pages._exceptions import UnmappableValueError


def test_value_present_processes():
    assert resolve_vehicle_value("$45.000") == 45000   # latino -> 45000


def test_value_us_format_processes():
    assert resolve_vehicle_value("$45,000.00") == 45000.0


def test_value_absent_is_none_no_apd():
    assert resolve_vehicle_value(None) is None
    assert resolve_vehicle_value("") is None


def test_value_zero_is_none_no_apd():
    assert resolve_vehicle_value("$0") is None
    assert resolve_vehicle_value("0") is None


def test_value_below_floor_halts():
    # the mis-parsed "$45" case: present, parses, but < $100 -> HALT
    with pytest.raises(UnmappableValueError) as exc:
        resolve_vehicle_value("$45")
    assert exc.value.source_value == "$45"


def test_value_exactly_floor_halts():
    # exactly $100 is NOT greater than $100 -> HALT
    with pytest.raises(UnmappableValueError):
        resolve_vehicle_value("$100")


def test_value_just_above_floor_processes():
    assert resolve_vehicle_value("$101") == 101


def test_value_garbage_halts():
    with pytest.raises(UnmappableValueError):
        resolve_vehicle_value("banana")
