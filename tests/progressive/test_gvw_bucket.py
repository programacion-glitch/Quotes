import pytest
from modules.progressive.vehicle_amounts import bucket_gvw, resolve_gvw
from modules.progressive.pages._exceptions import UnmappableValueError

OPTS = ["10,000 lbs or less", "10,001 - 26,000 lbs", "26,001 lbs or greater"]


def test_bucket_high_weight():
    assert bucket_gvw(51000, OPTS) == "26,001 lbs or greater"


def test_bucket_low_weight():
    assert bucket_gvw(8000, OPTS) == "10,000 lbs or less"


def test_bucket_mid_weight():
    assert bucket_gvw(15000, OPTS) == "10,001 - 26,000 lbs"


def test_bucket_boundary_inclusive():
    assert bucket_gvw(26000, OPTS) == "10,001 - 26,000 lbs"
    assert bucket_gvw(26001, OPTS) == "26,001 lbs or greater"


def test_resolve_gvw_present_weight_buckets():
    assert resolve_gvw("51.000 LBS", OPTS) == "26,001 lbs or greater"


def test_resolve_gvw_absent_uses_default():
    assert resolve_gvw(None, OPTS) == "26,001 lbs or greater"
    assert resolve_gvw("", OPTS) == "26,001 lbs or greater"


def test_resolve_gvw_present_but_garbage_halts():
    with pytest.raises(UnmappableValueError) as exc:
        resolve_gvw("banana", OPTS)
    assert exc.value.source_value == "banana"


def test_label_with_no_number_does_not_crash():
    from modules.progressive.vehicle_amounts import bucket_gvw
    result = bucket_gvw(5000, ["10,000 lbs or less", "Unknown"])
    assert result == "10,000 lbs or less"   # real range matches first; no crash
