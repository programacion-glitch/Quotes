"""CompCollSubPage._handle_business_class_mismatch — GEICO business-class override.

Live NUNEZ 2026-06-17: after the vehicle/operations data is entered, GEICO may
decide the selected business class is wrong and pop a "Something's not lining up"
interstitial suggesting its own class (e.g. 'Package Delivery' ->
'For-Hire Trucking/General Freight'), offering 'Update' (accept GEICO's class)
or 'Start New Quote' (discard). GEICO is the authority on its own rating class,
so the handler clicks 'Update'. Same pattern as the Verify-USDOT 'Skip' handler.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from modules.geico.pages.vehicles_page import CompCollSubPage


async def test_clicks_update_when_interstitial_present(mock_page):
    # mock_page.get_by_text returns a locator with count=1 / is_visible=True.
    sub = CompCollSubPage(mock_page)
    sub.remove_overlays = AsyncMock()
    sub.click_button = AsyncMock()

    handled = await sub._handle_business_class_mismatch()

    assert handled is True
    # 'Update' bounces to Step 1; accept GEICO's pre-selected class via
    # 'Save And Continue'.
    sub.click_button.assert_any_await("Update")
    sub.click_button.assert_any_await("Save And Continue")
    # A warning is recorded for the agent-facing report.
    assert any("business class" in w.lower() for w in sub.warnings)


async def test_noop_when_interstitial_absent(mock_page, mock_locator):
    mock_locator.count = AsyncMock(return_value=0)
    sub = CompCollSubPage(mock_page)
    sub.remove_overlays = AsyncMock()
    sub.click_button = AsyncMock()

    handled = await sub._handle_business_class_mismatch()

    assert handled is False
    sub.click_button.assert_not_awaited()


async def test_noop_when_banner_hidden(mock_page, mock_locator):
    mock_locator.is_visible = AsyncMock(return_value=False)
    sub = CompCollSubPage(mock_page)
    sub.remove_overlays = AsyncMock()
    sub.click_button = AsyncMock()

    handled = await sub._handle_business_class_mismatch()

    assert handled is False
    sub.click_button.assert_not_awaited()
