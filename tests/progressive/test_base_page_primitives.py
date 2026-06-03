"""Unit tests for BasePage primitives.

Uses AsyncMock fixtures from conftest.py — no real browser.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.progressive.pages.base_page import BasePage


@pytest.mark.asyncio
async def test_current_page_token_extracts_pagename(mock_page):
    mock_page.url = "https://x.progressive.com/agent/?pageName=MoreAboutBusiness&wGuid=abc"
    bp = BasePage(mock_page)
    assert await bp.current_page_token() == "MoreAboutBusiness"


@pytest.mark.asyncio
async def test_current_page_token_returns_empty_when_no_pagename(mock_page):
    mock_page.url = "https://x.progressive.com/agent/"
    bp = BasePage(mock_page)
    assert await bp.current_page_token() == ""


@pytest.mark.asyncio
async def test_remove_overlays_calls_evaluate(mock_page):
    bp = BasePage(mock_page)
    await bp.remove_overlays()
    mock_page.evaluate.assert_awaited()


@pytest.mark.asyncio
async def test_blur_active_element_calls_evaluate(mock_page):
    bp = BasePage(mock_page)
    await bp.blur_active_element()
    mock_page.evaluate.assert_awaited()


@pytest.mark.asyncio
async def test_wait_for_extjs_idle_calls_wait_for_function(mock_page):
    bp = BasePage(mock_page)
    await bp.wait_for_extjs_idle()
    mock_page.wait_for_function.assert_awaited_once()
    args, kwargs = mock_page.wait_for_function.call_args
    js = args[0] if args else kwargs.get("expression", "")
    assert "Ext" in js
    assert "x-mask" in js
    assert "readyState" in js


@pytest.mark.asyncio
async def test_wait_for_extjs_idle_respects_timeout_ms(mock_page):
    bp = BasePage(mock_page)
    await bp.wait_for_extjs_idle(timeout_ms=5000)
    args, kwargs = mock_page.wait_for_function.call_args
    assert kwargs.get("timeout") == 5000


@pytest.mark.asyncio
async def test_find_by_label_text_uses_xpath_following_input(mock_page, mock_locator):
    bp = BasePage(mock_page)
    result = await bp.find_by_label_text("Driver's License Number")
    mock_page.get_by_text.assert_called_once()
    args, kwargs = mock_page.get_by_text.call_args
    assert args[0] == "Driver's License Number"
    assert kwargs.get("exact") is True
    mock_locator.locator.assert_called_with(
        "xpath=following::input[@type='text'][1]"
    )
    assert result is mock_locator


@pytest.mark.asyncio
async def test_find_by_placeholder_uses_get_by_placeholder(mock_page, mock_locator):
    bp = BasePage(mock_page)
    result = await bp.find_by_placeholder("Business Name")
    mock_page.get_by_placeholder.assert_called_once_with("Business Name")
    assert result is mock_locator


@pytest.mark.asyncio
async def test_find_radiogroup_uses_get_by_role(mock_page, mock_locator):
    bp = BasePage(mock_page)
    result = await bp.find_radiogroup("Is the customer currently insured?")
    mock_page.get_by_role.assert_called_with(
        "radiogroup",
        name="Is the customer currently insured?",
        exact=False,
    )
    assert result is mock_locator


@pytest.mark.asyncio
async def test_find_combo_uses_get_by_role_combobox(mock_page, mock_locator):
    bp = BasePage(mock_page)
    result = await bp.find_combo("Year")
    mock_page.get_by_role.assert_called_with(
        "combobox",
        name="Year",
        exact=False,
    )
    assert result is mock_locator


@pytest.mark.asyncio
async def test_field_exists_true_when_visible(mock_page, mock_locator):
    mock_locator.count = AsyncMock(return_value=1)
    mock_locator.is_visible = AsyncMock(return_value=True)
    bp = BasePage(mock_page)
    assert await bp.field_exists(mock_locator, wait_ms=100) is True


@pytest.mark.asyncio
async def test_field_exists_false_when_count_zero(mock_page, mock_locator):
    mock_locator.count = AsyncMock(return_value=0)
    bp = BasePage(mock_page)
    assert await bp.field_exists(mock_locator, wait_ms=100) is False


@pytest.mark.asyncio
async def test_field_exists_false_when_not_visible(mock_page, mock_locator):
    mock_locator.count = AsyncMock(return_value=1)
    mock_locator.is_visible = AsyncMock(return_value=False)
    bp = BasePage(mock_page)
    assert await bp.field_exists(mock_locator, wait_ms=100) is False
