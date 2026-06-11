"""Unit tests for the hardened GEICO BasePage primitives.

Uses AsyncMock fixtures from conftest.py — no real browser. Mirrors the
Progressive primitive suite: every interaction primitive must VERIFY the
committed value, RETRY on mismatch, and raise a structured exception with
diagnostics after exhausting retries.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.geico.pages.base_page import BasePage


# ---------- JSON payloads the select JS is expected to return ----------

SET_OK = json.dumps({
    "id": "sel1", "value": "7", "text": "7+",
    "options": ["Less than 1", "1", "2", "3-6", "7+"],
})
READBACK_OK = json.dumps({"found": True, "value": "7", "text": "7+"})
READBACK_RESET = json.dumps({"found": True, "value": "", "text": ""})
OPTION_NOT_FOUND = json.dumps({
    "error": "option-not-found", "id": "sel1",
    "options": ["Less than 1", "1", "2", "3-6", "7+"],
})
NO_MATCH = json.dumps({"error": "no-match"})


# ============================================================
# safe_fill
# ============================================================

async def test_safe_fill_clicks_fills_tabs_and_verifies(mock_page, mock_locator):
    mock_locator.input_value = AsyncMock(return_value="hello")
    bp = BasePage(mock_page)
    await bp.safe_fill(mock_locator, "hello")
    mock_locator.click.assert_awaited()
    mock_locator.fill.assert_awaited_with("hello")
    mock_page.keyboard.press.assert_awaited_with("Tab")
    mock_locator.input_value.assert_awaited()


async def test_safe_fill_retries_when_value_mismatch(mock_page, mock_locator):
    mock_locator.input_value = AsyncMock(side_effect=["wrong", "wrong", "hello"])
    bp = BasePage(mock_page)
    await bp.safe_fill(mock_locator, "hello", retries=2)
    assert mock_locator.fill.await_count == 3


async def test_safe_fill_raises_after_retries(mock_page, mock_locator):
    from modules.geico.pages._exceptions import FillVerifyError
    mock_locator.input_value = AsyncMock(return_value="wrong")
    bp = BasePage(mock_page)
    with pytest.raises(FillVerifyError) as exc_info:
        await bp.safe_fill(mock_locator, "hello", retries=2)
    assert exc_info.value.primitive == "safe_fill"
    assert exc_info.value.attempts == 3


async def test_safe_fill_skips_verify_when_verify_false(mock_page, mock_locator):
    mock_locator.input_value = AsyncMock(return_value="wrong")
    bp = BasePage(mock_page)
    await bp.safe_fill(mock_locator, "hello", verify=False)
    mock_locator.input_value.assert_not_awaited()


# ============================================================
# select_by_options_signature / select_by_js (verified natives)
# ============================================================

async def test_select_by_signature_sets_and_verifies(mock_page):
    mock_page.evaluate = AsyncMock(side_effect=[SET_OK, READBACK_OK])
    bp = BasePage(mock_page)
    result = await bp.select_by_options_signature(["Less than 1", "7+"], "7+")
    assert result == "sel1"
    assert mock_page.evaluate.await_count == 2


async def test_select_by_signature_retries_when_framework_resets_value(mock_page):
    mock_page.evaluate = AsyncMock(
        side_effect=[SET_OK, READBACK_RESET, SET_OK, READBACK_OK]
    )
    bp = BasePage(mock_page)
    result = await bp.select_by_options_signature(
        ["Less than 1", "7+"], "7+", retries=2
    )
    assert result == "sel1"
    assert mock_page.evaluate.await_count == 4


async def test_select_by_signature_raises_with_options_dump(mock_page):
    from modules.geico.pages._exceptions import SelectVerifyError
    mock_page.evaluate = AsyncMock(return_value=OPTION_NOT_FOUND)
    bp = BasePage(mock_page)
    with pytest.raises(SelectVerifyError) as exc_info:
        await bp.select_by_options_signature(
            ["Less than 1", "7+"], "BOGUS", retries=1
        )
    err = exc_info.value
    assert err.attempts == 2
    assert "7+" in err.available_options


async def test_select_by_signature_raises_not_found_when_no_select(mock_page):
    from modules.geico.pages._exceptions import SelectNotFoundError
    mock_page.evaluate = AsyncMock(return_value=NO_MATCH)
    bp = BasePage(mock_page)
    with pytest.raises(SelectNotFoundError):
        await bp.select_by_options_signature(["X", "Y"], "X", retries=1)


async def test_select_by_js_sets_and_verifies(mock_page):
    mock_page.evaluate = AsyncMock(side_effect=[SET_OK, READBACK_OK])
    bp = BasePage(mock_page)
    result = await bp.select_by_js("yearsOperating", "7+")
    assert result == "sel1"


# ============================================================
# click_question_radio (shadow-DOM verified)
# ============================================================

async def test_radio_skips_click_when_already_checked(mock_page, mock_locator):
    # Pre-check: the JS probe reads checked=True before any click (the
    # customer's-business Yes arrives pre-checked on some quotes). Radio
    # clicks are idempotent but skipping avoids hydration races entirely.
    mock_locator.evaluate = AsyncMock(return_value=True)
    bp = BasePage(mock_page)
    await bp.click_question_radio("Does the customer have an ELD", "No")
    mock_locator.click.assert_not_awaited()


async def test_radio_clicks_then_verifies_checked(mock_page, mock_locator):
    # Pre-check False -> click -> post-check True.
    mock_locator.evaluate = AsyncMock(side_effect=[False, True])
    bp = BasePage(mock_page)
    await bp.click_question_radio("Does the customer have an ELD", "No")
    mock_locator.click.assert_awaited()


async def test_radio_waits_for_gds_hydration_before_clicking(mock_page, mock_locator):
    # The group mounts AFTER a server round-trip (FMCSA preview) and a click
    # on a not-yet-hydrated custom element is a silent no-op (live HUMBERTO
    # 2026-06-11). The primitive must wait for every gds-radio-button in the
    # group to have its shadow input before interacting.
    mock_locator.evaluate = AsyncMock(side_effect=[False, True])
    bp = BasePage(mock_page)
    await bp.click_question_radio("Is this the customer's business", "Yes")
    js_calls = [
        args.args[0] for args in mock_page.wait_for_function.await_args_list
    ]
    assert any("shadowRoot" in js for js in js_calls)


async def test_radio_raises_when_persistently_unchecked(mock_page, mock_locator):
    from modules.geico.pages._exceptions import RadioStuckError
    mock_locator.is_checked = AsyncMock(return_value=False)
    mock_locator.evaluate = AsyncMock(return_value=False)  # JS state: unchecked
    bp = BasePage(mock_page)
    with pytest.raises(RadioStuckError):
        await bp.click_question_radio(
            "Does the customer have an ELD", "No", retries=1
        )


async def test_radio_warns_and_continues_when_state_unreadable(mock_page, mock_locator):
    mock_locator.is_checked = AsyncMock(side_effect=Exception("shadow DOM"))
    mock_locator.evaluate = AsyncMock(side_effect=Exception("no shadowRoot"))
    bp = BasePage(mock_page)
    await bp.click_question_radio("Does the customer have an ELD", "No")
    assert any("unverified" in w.lower() for w in bp.warnings)


# ============================================================
# wait_for_any_title
# ============================================================

async def test_wait_for_any_title_returns_matched_substring(mock_page):
    mock_page.title = AsyncMock(return_value="GEICO Quote & Coverages")
    bp = BasePage(mock_page)
    matched = await bp.wait_for_any_title(
        ["DriveEasy Pro", "Quote & Coverages"], timeout_ms=1000
    )
    assert matched == "Quote & Coverages"


async def test_wait_for_any_title_raises_on_timeout(mock_page):
    mock_page.wait_for_function = AsyncMock(side_effect=Exception("timeout"))
    mock_page.title = AsyncMock(return_value="GEICO Vehicles")
    bp = BasePage(mock_page)
    with pytest.raises(TimeoutError):
        await bp.wait_for_any_title(["DriveEasy Pro"], timeout_ms=100)


# ============================================================
# field_exists
# ============================================================

async def test_field_exists_true_when_visible(mock_page, mock_locator):
    mock_locator.count = AsyncMock(return_value=1)
    mock_locator.is_visible = AsyncMock(return_value=True)
    bp = BasePage(mock_page)
    assert await bp.field_exists(mock_locator, wait_ms=100) is True


async def test_field_exists_false_when_count_zero(mock_page, mock_locator):
    mock_locator.count = AsyncMock(return_value=0)
    mock_locator.wait_for = AsyncMock(side_effect=Exception("timeout"))
    mock_locator.is_visible = AsyncMock(return_value=False)
    bp = BasePage(mock_page)
    assert await bp.field_exists(mock_locator, wait_ms=100) is False


async def test_field_exists_false_when_not_visible(mock_page, mock_locator):
    mock_locator.count = AsyncMock(return_value=1)
    mock_locator.wait_for = AsyncMock(side_effect=Exception("timeout"))
    mock_locator.is_visible = AsyncMock(return_value=False)
    bp = BasePage(mock_page)
    assert await bp.field_exists(mock_locator, wait_ms=100) is False


# ============================================================
# warnings infrastructure + debug context
# ============================================================

def test_note_warning_accumulates(mock_page):
    bp = BasePage(mock_page)
    bp.note_warning("first")
    bp.note_warning("second")
    assert bp.warnings == ["first", "second"]


async def test_dump_debug_context_returns_url_and_label(mock_page):
    mock_page.url = "https://sales.geico.com/quote?x=1"
    mock_page.title = AsyncMock(return_value="GEICO Vehicles")
    bp = BasePage(mock_page)
    ctx = await bp.dump_debug_context("vin_decode")
    assert ctx["label"] == "vin_decode"
    assert ctx["url"] == "https://sales.geico.com/quote?x=1"
    assert ctx["title"] == "GEICO Vehicles"
