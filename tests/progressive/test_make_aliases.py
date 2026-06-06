"""Make-abbreviation expansion for the trailer Make combobox."""

from __future__ import annotations

import pytest

from modules.progressive.mappings import expand_make


@pytest.mark.parametrize("raw,expected", [
    ("GD", "Great Dane"),        # live (3R TRUCKING): initials, not a prefix
    ("GDAN", "Great Dane"),
    ("GD 48FT", "Great Dane"),   # alias keyed on the first token
    ("UTIL", "Utility"),
    ("BIGT 16G", "Big Tex"),
    ("PTRB", "Peterbilt"),
    ("KW", "Kenworth"),
])
def test_expand_known_abbreviations(raw, expected):
    assert expand_make(raw) == expected


def test_unknown_make_is_unchanged():
    assert expand_make("WILSON") == "WILSON"
    assert expand_make("Some Trailer Co") == "Some Trailer Co"


def test_empty_make():
    assert expand_make("") == ""
    assert expand_make(None) is None
