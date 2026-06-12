"""Currency money fields (comp/coll value inputs) auto-format to '$1,234',
so verifying a fill by exact read-back falsely fails ('1234' != '$1,234').
_digits_only normalizes both sides to digits for the comparison.
"""

from __future__ import annotations

from modules.geico.pages.vehicles_page import _digits_only


def test_strips_dollar_and_commas():
    assert _digits_only("$50,000") == "50000"


def test_plain_number_unchanged():
    assert _digits_only("1234") == "1234"


def test_zero_dollar():
    assert _digits_only("$0") == "0"


def test_empty_and_none_safe():
    assert _digits_only("") == ""
    assert _digits_only(None) == ""


def test_formatted_equals_raw():
    # The real check the fill does: typed '50000', read back '$50,000'.
    assert _digits_only("$50,000") == _digits_only("50000")
