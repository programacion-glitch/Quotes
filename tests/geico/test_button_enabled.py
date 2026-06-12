"""wait_for_button_enabled polls a gds-button's disabled state.

Live SOLANO 2026-06-11: the owner-driver placeholder's Next is disabled
ASYNCHRONOUSLY while GEICO processes CDL=Yes + the driving-history reveal;
clicking during that window is a no-op and the form never advances. The
primitive polls the enabled state (a condition wait, not a sleep) before
the click.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from modules.geico.pages.base_page import BasePage


async def test_returns_true_when_enabled_immediately(mock_page):
    mock_page.evaluate = AsyncMock(return_value=True)
    bp = BasePage(mock_page)
    assert await bp.wait_for_button_enabled("Next", timeout_ms=1000) is True
    mock_page.wait_for_timeout.assert_not_awaited()  # no polling delay needed


async def test_polls_until_enabled(mock_page):
    mock_page.evaluate = AsyncMock(side_effect=[False, False, True])
    bp = BasePage(mock_page)
    assert await bp.wait_for_button_enabled("Next", timeout_ms=5000) is True
    assert mock_page.evaluate.await_count == 3


async def test_returns_false_on_timeout(mock_page):
    mock_page.evaluate = AsyncMock(return_value=False)
    bp = BasePage(mock_page)
    assert await bp.wait_for_button_enabled("Next", timeout_ms=300) is False
