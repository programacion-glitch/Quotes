"""
Unit tests for commodity extraction hardening.

Background (RAFYURY TRANSPORT LLC, 2026-06-14): a BlueQuote with positionally
misaligned form fields put the operating radius '500 MILES' into the commodity
slot and the real commodity 'SAND & GRAVEL' into the destinations slot. GEICO
then tried to select a business class literally named '500 MILES' and HALTed.

A commodity is never a pure distance, so:
  * `_looks_like_radius` recognises radius/distance expressions, and
  * `_resolve_commodity` discards a radius that leaked into the commodity slot
    and recovers the real commodity from the destinations slot — but ONLY when
    the commodity was radius-like (a clear misalignment signal), never when the
    commodity is simply empty (which would risk guessing a destination as a
    commodity).
"""

import os

import pytest

from modules.document_ai_extractor import _looks_like_radius, _resolve_commodity


# --------------------------------------------------------------------------- #
# _looks_like_radius
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("value", [
    "500 MILES",
    "500 MILE",
    "150 MI",
    "301-500",
    "101 - 200",
    "500+",
    "500+ MILES",
    "500",
    "  500 Miles  ",
])
def test_looks_like_radius_true(value):
    assert _looks_like_radius(value) is True


@pytest.mark.parametrize("value", [
    "SAND & GRAVEL",
    "GENERAL FREIGHT",
    "100% PRODUCE",
    "PACKED CHARCOAL",
    "",
    None,
])
def test_looks_like_radius_false(value):
    assert _looks_like_radius(value) is False


# --------------------------------------------------------------------------- #
# _resolve_commodity
# --------------------------------------------------------------------------- #

def test_resolve_commodity_normal_keeps_value():
    assert _resolve_commodity("SAND & GRAVEL", "TX OK LA") == "SAND & GRAVEL"


def test_resolve_commodity_recovers_from_destinations_when_radius_leaked():
    # RAFYURY: radius in commodity slot, real commodity in destinations slot.
    assert _resolve_commodity("500 MILES", "SAND & GRAVEL") == "SAND & GRAVEL"


def test_resolve_commodity_empty_does_not_guess_destinations():
    # Genuinely empty commodity must NOT pull destinations (could be a real
    # destination like a state list, not a commodity).
    assert _resolve_commodity("", "48 STATES") == ""
    assert _resolve_commodity(None, "TX OK LA") == ""


def test_resolve_commodity_blank_when_both_radius_like():
    assert _resolve_commodity("500 MILES", "301-500") == ""
    assert _resolve_commodity("500 MILES", "") == ""


# --------------------------------------------------------------------------- #
# Integration on the real RAFYURY BlueQuote (skipped if the client PDF is
# absent — client PDFs are never committed to the repo).
# --------------------------------------------------------------------------- #

_RAFYURY_PDF = os.path.join(
    "data", "BlueQuotes GEICO",
    "20260514 BLUE QUOTE - RAFYURY TRANSPORT LLC - 4579781.pdf",
)


@pytest.mark.skipif(
    not os.path.exists(_RAFYURY_PDF),
    reason="RAFYURY client PDF not present (not committed to repo)",
)
def test_rafyury_blue_quote_maps_to_real_commodity():
    from modules.pdf_extractor import BlueQuotePDFExtractor
    from modules.document_ai_extractor import DocumentAIExtractor

    extracted = BlueQuotePDFExtractor(_RAFYURY_PDF).extract()
    ext = DocumentAIExtractor()
    applicant, commodity, coverages, units, drivers, coverages_detail = (
        ext._map_blue_quote_to_profile(extracted)
    )

    assert commodity == "SAND & GRAVEL"
    # The radius is still captured correctly at the coverage level and must NOT
    # have been overwritten by the misplaced commodity text.
    radii = {v.radius_miles for v in units.vehicles if v.radius_miles}
    assert radii == {"301-500"}
