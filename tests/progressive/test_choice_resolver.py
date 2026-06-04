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
