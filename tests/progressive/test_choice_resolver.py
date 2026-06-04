from modules.progressive.pages._exceptions import (
    UnmappableValueError,
    ExtJSInteractionError,
)


def test_unmappable_value_error_carries_context():
    err = UnmappableValueError(
        field="Business type",
        source_value="PACKED CHARCOAL",
        available_options=["Coal Hauling", "Garbage & Trash Hauling/Removal"],
    )
    assert isinstance(err, ExtJSInteractionError)   # integrates with existing except
    assert err.field == "Business type"
    assert err.source_value == "PACKED CHARCOAL"
    assert "Coal Hauling" in err.available_options
    assert err.screenshot_path is None              # offline use
    assert "PACKED CHARCOAL" in str(err)


import pytest
from modules.progressive.choice_resolver import resolve_choice, Resolution

OPTS = ["Coal Hauling", "Beverage Distributor", "General Freight / Other",
        "Dirt, Sand and Gravel"]


def test_exact_match_returns_matched():
    r = resolve_choice("Business type", "Coal Hauling", OPTS)
    assert r.kind == "MATCHED" and r.value == "Coal Hauling" and r.note == "exact"


def test_mapping_table_match():
    r = resolve_choice("Business type", "BEER", OPTS,
                       mapping={"BEER": "Beverage Distributor"})
    assert r.kind == "MATCHED" and r.value == "Beverage Distributor"
    assert r.note == "mapping"


def test_generic_alias_routes_to_catch_all():
    r = resolve_choice("Business type", "general freight", OPTS,
                       generic_aliases=frozenset({"general freight"}))
    assert r.kind == "MATCHED" and r.value == "General Freight / Other"
    assert r.note == "generic"


def test_unique_token_match():
    r = resolve_choice("Business type", "Beverage", OPTS)
    assert r.kind == "MATCHED" and r.value == "Beverage Distributor"
    assert r.note.startswith("token")


def test_present_but_no_match_raises():
    from modules.progressive.pages._exceptions import UnmappableValueError
    with pytest.raises(UnmappableValueError) as exc:
        resolve_choice("Business type", "PACKED CHARCOAL", OPTS)
    assert exc.value.source_value == "PACKED CHARCOAL"
    assert exc.value.available_options == OPTS


def test_ambiguous_token_raises_not_guesses():
    # "hauling" appears in 2 options -> not confident -> HALT, no guess
    from modules.progressive.pages._exceptions import UnmappableValueError
    with pytest.raises(UnmappableValueError):
        resolve_choice("Business type", "hauling stuff", OPTS)


def test_absent_field_with_default_returns_defaulted():
    r = resolve_choice("GVW", None, [], default="26,001 lbs or greater")
    assert r.kind == "DEFAULTED" and r.value == "26,001 lbs or greater"
    assert r.source_value is None and r.note == "default"


def test_absent_critical_field_raises():
    from modules.progressive.pages._exceptions import UnmappableValueError
    with pytest.raises(UnmappableValueError):
        resolve_choice("vehicle tile", None, ["Pickup Truck"])
