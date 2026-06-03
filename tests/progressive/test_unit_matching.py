"""Stable identifier composition for matching units PDF↔Progressive."""

from __future__ import annotations

from modules.progressive.unit_matching import normalize_identifier


def test_real_vin_dominates_ymm():
    """When a real VIN is present, it wins regardless of Y/M/M."""
    assert normalize_identifier("1UYVS253XM7301310", 2021, "UTILITY", "DRY VAN") == "1UYVS253XM7301310"


def test_lowercase_vin_normalizes_to_upper():
    assert normalize_identifier("  1uyvs253xm7301310  ", None, None, None) == "1UYVS253XM7301310"


def test_non_owned_vin_falls_back_to_ymm():
    """NON OWNED marker is not a real VIN; fall back to composite."""
    assert normalize_identifier("NON OWNED", 2018, "  utility  ", "end dump") == "2018|UTILITY|END DUMP"


def test_empty_vin_with_ymm_uses_ymm():
    assert normalize_identifier("", 2018, "UTILITY", "FLATBED") == "2018|UTILITY|FLATBED"


def test_no_vin_missing_year_returns_none():
    """Insufficient identity data → None; caller will treat as no-match."""
    assert normalize_identifier(None, None, "UTILITY", "FLATBED") is None


def test_short_vin_not_treated_as_real():
    """A 5-char string is not a VIN; fall back to YMM."""
    assert normalize_identifier("ABC12", 2020, "X", "Y") == "2020|X|Y"


def test_invalid_vin_chars_fall_back():
    """VINs use a restricted alphabet (no I, O, Q). 17 chars with O → not a VIN."""
    bad_vin = "1OOOOOOOOOOOOOOOO"   # 17 chars but contains O
    assert normalize_identifier(bad_vin, 2020, "X", "Y") == "2020|X|Y"


def test_whitespace_only_make_returns_none():
    """Whitespace-only make/model collapses to empty after strip → fallback fails."""
    assert normalize_identifier(None, 2021, "   ", "FLATBED") is None


def test_none_vin_with_valid_ymm_uses_ymm():
    """Most common no-VIN path: vin=None + complete YMM → composite identifier."""
    assert normalize_identifier(None, 2021, "UTILITY", "FLATBED") == "2021|UTILITY|FLATBED"


# ---------------------------------------------------------------------------
# diff_unit_vs_pdf tests
# ---------------------------------------------------------------------------
from dataclasses import dataclass
from typing import Optional as _Opt

from modules.progressive.unit_matching import diff_unit_vs_pdf


# Lightweight stand-ins for ExistingUnit/MappedVehicle, since diff_unit_vs_pdf
# is structural (reads attrs, not type-bound).
@dataclass
class _U:
    year: _Opt[int] = None
    make: _Opt[str] = None
    model: _Opt[str] = None
    gvw: _Opt[str] = None
    value: _Opt[str] = None
    has_loan: str = "No"
    radius_miles: _Opt[str] = None


def test_diff_identical_units_returns_empty():
    a = _U(year=2021, make="UTIL", model="DRY VAN", gvw="26,001 lbs or greater",
           value="50000", has_loan="No", radius_miles="Over 500 miles")
    b = _U(year=2021, make="UTIL", model="DRY VAN", gvw="26,001 lbs or greater",
           value="50000", has_loan="No", radius_miles="Over 500 miles")
    assert diff_unit_vs_pdf(a, b) == {}


def test_diff_single_field_diff():
    a = _U(year=2021, gvw="26,001 lbs or greater")
    b = _U(year=2021, gvw="10,001 - 16,000 lbs")
    assert diff_unit_vs_pdf(a, b) == {"gvw": ("26,001 lbs or greater", "10,001 - 16,000 lbs")}


def test_diff_multiple_fields():
    a = _U(year=2021, value="50000", has_loan="No")
    b = _U(year=2020, value="40000", has_loan="Loan")
    assert diff_unit_vs_pdf(a, b) == {
        "year": (2021, 2020),
        "value": ("50000", "40000"),
        "has_loan": ("No", "Loan"),
    }


def test_diff_none_vs_value_counts_as_diff():
    a = _U(value=None)
    b = _U(value="40000")
    assert diff_unit_vs_pdf(a, b) == {"value": (None, "40000")}


def test_diff_skips_unknown_attrs():
    """diff_unit_vs_pdf reads a fixed field list; foreign attrs don't break it."""
    a = _U(year=2021)
    b = _U(year=2021)
    # ad hoc attr that diff_unit_vs_pdf should ignore
    a.foo = "x"
    b.foo = "y"
    assert diff_unit_vs_pdf(a, b) == {}
