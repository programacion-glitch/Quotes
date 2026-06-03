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
