"""Structured exceptions for ExtJS-safe primitives in BasePage.

Every primitive that fails after retries raises a subclass of
ExtJSInteractionError carrying the screenshot path and debug context
captured at the moment of failure.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


class ExtJSInteractionError(Exception):
    """Base for any failure inside a BasePage primitive after retries."""

    def __init__(
        self,
        message: str,
        *,
        primitive: str,
        field: Optional[str],
        attempts: int,
        screenshot_path: Optional[Path] = None,
        debug_context: Optional[dict] = None,
    ) -> None:
        super().__init__(message)
        self.primitive = primitive
        self.field = field
        self.attempts = attempts
        self.screenshot_path = screenshot_path
        self.debug_context = debug_context or {}


class FillVerifyError(ExtJSInteractionError):
    """safe_fill could not verify input_value() after retries."""


class RadioStuckError(ExtJSInteractionError):
    """safe_radio could not make a radio is_checked() after retries."""


class ContinueStuckError(ExtJSInteractionError):
    """safe_click_continue did not advance the URL after retries."""


class ComboSelectError(ExtJSInteractionError):
    """safe_select_combo could not commit the desired option."""


class FieldNotFoundError(ExtJSInteractionError):
    """find_* primitive could not locate a REQUIRED field within timeout."""


class UnmappableValueError(ExtJSInteractionError):
    """A Blue Quote value was present but matched no Progressive option with
    confidence, OR a critical field was absent with no default. Raised by
    resolve_choice; used both offline (preflight, screenshot_path=None) and
    in-flight (with screenshot)."""

    def __init__(
        self,
        *,
        field: str,
        source_value: Optional[str],
        available_options: list,
        screenshot_path: Optional[Path] = None,
        debug_context: Optional[dict] = None,
    ) -> None:
        super().__init__(
            f"Cannot map {field!r}: value {source_value!r} has no confident "
            f"match among {len(available_options)} options",
            primitive="resolve_choice",
            field=field,
            attempts=1,
            screenshot_path=screenshot_path,
            debug_context=debug_context,
        )
        self.source_value = source_value
        self.available_options = list(available_options)
