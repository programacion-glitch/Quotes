"""Whitespace hygiene: extractor values arrive with trailing spaces
('2033673 ') — Progressive hit this live (USDOT lookup, commit fa4005a).
Critical identifiers must reach the pages stripped."""

from __future__ import annotations

from modules.geico.field_mapper import map_profile_to_fields
from modules.quote_profile import ApplicantProfile, QuoteProfile


def test_critical_fields_are_stripped():
    profile = QuoteProfile(
        applicant=ApplicantProfile(
            business_name="  HUMBERTO VILLARREAL  ",
            owner_name="HUMBERTO VILLARREAL",
            usdot="2033673 ",
            zip_code=" 77705 ",
        )
    )
    fields = map_profile_to_fields(profile)
    assert fields.usdot == "2033673"
    assert fields.zip_code == "77705"
    assert fields.business_name == "HUMBERTO VILLARREAL"
