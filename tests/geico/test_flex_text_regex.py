"""_flex_text_regex must match real GEICO question text.

Regression: the original code used an INVISIBLE private-use placeholder
character (U+E000) inline; a rewrite copied it as an empty string and the
empty-string replacement mangled every pattern into one with an apostrophe
class glued between every literal character — no locator matched, no radio
was ever clicked, and three live runs burned on
'RadioStuckError (last error: None)'. The placeholder must be an explicit
escape, and this test pins matching behavior on both apostrophe variants.
"""

from __future__ import annotations

from modules.geico.pages.base_page import _flex_text_regex

PUA_PLACEHOLDER = chr(0xE000)


def test_matches_ascii_apostrophe_text():
    re_ = _flex_text_regex("Is this the customer's business")
    assert re_.search(
        "HUMBERTO VILLARREAL 585 NOLAN STREET Is this the customer's business? Yes No"
    )


def test_matches_typographic_apostrophe_text():
    re_ = _flex_text_regex("Is this the customer's business")
    assert re_.search("Is this the customer’s business?")


def test_query_with_typographic_matches_ascii_dom():
    re_ = _flex_text_regex("Is this the customer’s business")
    assert re_.search("Is this the customer's business?")


def test_collapses_whitespace_runs():
    re_ = _flex_text_regex("Does the customer have an ELD")
    assert re_.search("Does the customer  have\nan ELD in their vehicle(s)?")


def test_no_apostrophe_question():
    re_ = _flex_text_regex("require a hazardous material placard")
    assert re_.search(
        "Do any of the customer's vehicles or loads require a hazardous "
        "material placard?"
    )


def test_does_not_match_unrelated_text():
    re_ = _flex_text_regex("Is this the customer's business")
    assert not re_.search("Does the customer have a USDOT Number?")


def test_pattern_is_clean_and_js_compatible():
    # The pattern ships into the page as `new RegExp(src, 'i')`; the
    # placeholder must never leak, and the mangling symptom (apostrophe
    # class between every literal char) must be absent.
    src = _flex_text_regex("Is this the customer's business").pattern
    assert PUA_PLACEHOLDER not in src
    assert "['’]" in src
    assert "['’]I['’]" not in src
