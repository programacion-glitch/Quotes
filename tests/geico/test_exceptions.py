"""Structured exceptions for GEICO BasePage primitives carry diagnostics."""

from __future__ import annotations

from pathlib import Path

from modules.geico.pages._exceptions import (
    FillVerifyError,
    GeicoInteractionError,
    RadioStuckError,
    SelectNotFoundError,
    SelectVerifyError,
)


def test_base_exception_carries_diagnostics():
    err = GeicoInteractionError(
        "boom",
        primitive="safe_fill",
        field="owner_phone",
        attempts=3,
        screenshot_path=Path("logs/geico_x.png"),
        debug_context={"url": "https://sales.geico.com/quote"},
    )
    assert str(err) == "boom"
    assert err.primitive == "safe_fill"
    assert err.field == "owner_phone"
    assert err.attempts == 3
    assert err.screenshot_path == Path("logs/geico_x.png")
    assert err.debug_context["url"] == "https://sales.geico.com/quote"


def test_debug_context_defaults_to_empty_dict():
    err = GeicoInteractionError(
        "boom", primitive="p", field=None, attempts=1
    )
    assert err.debug_context == {}


def test_subclasses_inherit_base():
    for cls in (FillVerifyError, RadioStuckError, SelectVerifyError, SelectNotFoundError):
        err = cls("x", primitive="p", field="f", attempts=1)
        assert isinstance(err, GeicoInteractionError)
        assert isinstance(err, Exception)


def test_select_verify_error_carries_available_options():
    err = SelectVerifyError(
        "no option",
        primitive="select_by_options_signature",
        field="Years operating",
        attempts=3,
        available_options=["Less than 1", "1", "2", "3-6", "7+"],
    )
    assert err.available_options == ["Less than 1", "1", "2", "3-6", "7+"]
