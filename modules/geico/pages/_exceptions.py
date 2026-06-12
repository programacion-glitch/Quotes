"""Structured exceptions for GEICO BasePage primitives.

Every primitive that fails after retries raises a subclass of
GeicoInteractionError carrying the screenshot path and debug context
captured at the moment of failure — the log must teach the real DOM so
the next fix is surgical, not guessed.

Mirrors modules/progressive/pages/_exceptions.py; GEICO's front end is
shadow-DOM custom elements + native <select>s instead of ExtJS, so the
select errors additionally carry the visible option list.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


class GeicoInteractionError(Exception):
    """Base for any failure inside a GEICO BasePage primitive after retries."""

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


class FillVerifyError(GeicoInteractionError):
    """safe_fill could not verify input_value() after retries."""


class RadioStuckError(GeicoInteractionError):
    """click_question_radio verified the radio as NOT checked after retries."""


class SelectNotFoundError(GeicoInteractionError):
    """No <select> matched the id-pattern / options-signature finder."""


class SelectVerifyError(GeicoInteractionError):
    """The desired option was missing, or the framework reset the value
    after we committed it. Carries the select's visible options so the
    failure log teaches the real catalog."""

    def __init__(
        self,
        message: str,
        *,
        primitive: str,
        field: Optional[str],
        attempts: int,
        available_options: Optional[list] = None,
        screenshot_path: Optional[Path] = None,
        debug_context: Optional[dict] = None,
    ) -> None:
        super().__init__(
            message,
            primitive=primitive,
            field=field,
            attempts=attempts,
            screenshot_path=screenshot_path,
            debug_context=debug_context,
        )
        self.available_options = list(available_options or [])


class FieldNotFoundError(GeicoInteractionError):
    """A find_* primitive could not locate a REQUIRED field within timeout."""


class UnderwritingRejectError(RuntimeError):
    """GEICO rejected the quote INSIDE the wizard with 'We're unable to
    complete this quote through GEICO' (live YNJ 2026-06-12: the dashboard
    eligibility passed but the deeper FMCSA underwriting check refused the
    USDOT at Step 5 -> 6). Definitive HALT, not a bug and not retryable."""
