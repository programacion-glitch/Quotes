"""_parse_us_address: split a Blue Quote address into (street, city, state, zip)."""

from __future__ import annotations

import pytest

from modules.document_ai_extractor import _parse_us_address


@pytest.mark.parametrize("addr,expected", [
    # Live (RDM TRUCKING): ZIP+4 with a trailing dash + double space — used to
    # return all-None, leaving the owner address blank so START page rejected it.
    ("1426 HARROP AVE  PASADENA, TX 77506-3628-",
     ("1426 HARROP AVE", "PASADENA", "TX", "77506")),
    # Plain 5-digit zip, comma before state.
    ("3294 N CLOSNER BLVD EDINBURG, TX 78541",
     ("3294 N CLOSNER BLVD", "EDINBURG", "TX", "78541")),
    # Comma immediately before state.
    ("585 NOLAN ST BEAUMONT, TX 77705",
     ("585 NOLAN ST", "BEAUMONT", "TX", "77705")),
    # ZIP+4 without the trailing dash still works.
    ("1426 HARROP AVE PASADENA, TX 77506-3628",
     ("1426 HARROP AVE", "PASADENA", "TX", "77506")),
])
def test_parse_us_address(addr, expected):
    assert _parse_us_address(addr) == expected


def test_parse_us_address_garbage_is_none():
    assert _parse_us_address("not an address") == (None, None, None, None)
    assert _parse_us_address("") == (None, None, None, None)
