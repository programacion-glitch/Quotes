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
