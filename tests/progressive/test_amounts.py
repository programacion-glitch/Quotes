import pytest
from modules.progressive.amounts import parse_amount


@pytest.mark.parametrize("raw,expected", [
    ("51.000 LBS", 51000),       # latino thousands + unit
    ("$45.000", 45000),          # latino thousands + currency
    ("$45,000.00", 45000.0),     # US thousands + decimal cents
    ("$45.000,50", 45000.5),     # latino thousands + decimal cents
    ("1.500.000", 1500000),      # latino, multiple separators
    ("1,500,000", 1500000),      # US, multiple separators
    ("1,500", 1500),             # single comma, 3 digits -> thousands
    ("45.5", 45.5),              # single dot, 1 digit -> decimal
    ("45.00", 45.0),             # single dot, 2 digits -> decimal (cents)
    ("45.000", 45000),           # single dot, 3 digits -> thousands
    ("26001", 26001),            # plain integer
    ("$0", 0),                   # zero
    ("0.001", 0.001),            # zero integer part + 3 digits -> decimal, not thousands
    ("10.000", 10000),           # real thousands still work (integer part not zero)
])
def test_parse_amount_formats(raw, expected):
    assert parse_amount(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", None, "banana", "$", "LBS", "N/A"])
def test_parse_amount_unparseable_returns_none(raw):
    assert parse_amount(raw) is None
