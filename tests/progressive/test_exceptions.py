"""Verify exception classes carry required diagnostic attributes."""

from pathlib import Path

import pytest

from modules.progressive.pages._exceptions import (
    ContinueStuckError,
    ExtJSInteractionError,
    FieldNotFoundError,
    FillVerifyError,
    RadioStuckError,
    ComboSelectError,
)


def test_extjs_interaction_error_carries_all_attrs():
    exc = ExtJSInteractionError(
        message="primitive failed",
        primitive="safe_fill",
        field="business_name",
        attempts=3,
        screenshot_path=Path("logs/x.png"),
        debug_context={"url": "u", "pageName": "P"},
    )
    assert exc.primitive == "safe_fill"
    assert exc.field == "business_name"
    assert exc.attempts == 3
    assert exc.screenshot_path == Path("logs/x.png")
    assert exc.debug_context["pageName"] == "P"
    assert "primitive failed" in str(exc)


def test_fill_verify_error_is_extjs_interaction_error():
    exc = FillVerifyError(message="m", primitive="safe_fill", field="x", attempts=2)
    assert isinstance(exc, ExtJSInteractionError)


def test_radio_stuck_error_is_extjs_interaction_error():
    exc = RadioStuckError(message="m", primitive="safe_radio", field="x", attempts=3)
    assert isinstance(exc, ExtJSInteractionError)


def test_continue_stuck_error_is_extjs_interaction_error():
    exc = ContinueStuckError(message="m", primitive="safe_click_continue", field=None, attempts=3)
    assert isinstance(exc, ExtJSInteractionError)


def test_combo_select_error_is_extjs_interaction_error():
    exc = ComboSelectError(message="m", primitive="safe_select_combo", field="x", attempts=2)
    assert isinstance(exc, ExtJSInteractionError)


def test_field_not_found_error_is_extjs_interaction_error():
    exc = FieldNotFoundError(message="m", primitive="find_radiogroup", field="ELD", attempts=1)
    assert isinstance(exc, ExtJSInteractionError)


def test_optional_attrs_default_to_none():
    exc = ExtJSInteractionError(message="m", primitive="p", field=None, attempts=1)
    assert exc.screenshot_path is None
    assert exc.debug_context == {}
