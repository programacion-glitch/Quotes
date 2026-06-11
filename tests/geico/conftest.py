"""Shared fixtures for GEICO primitive tests.

Mocks playwright.async_api.Page and Locator so primitives can be tested
without launching a browser. Mirrors tests/progressive/conftest.py, extended
with the locator methods the GEICO BasePage uses (filter, evaluate,
get_attribute) and page.inner_text / page.title.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_locator() -> AsyncMock:
    """A minimal Playwright Locator double."""
    loc = AsyncMock()
    loc.count = AsyncMock(return_value=1)
    loc.is_visible = AsyncMock(return_value=True)
    loc.is_checked = AsyncMock(return_value=False)
    loc.input_value = AsyncMock(return_value="")
    loc.inner_text = AsyncMock(return_value="")
    loc.click = AsyncMock()
    loc.fill = AsyncMock()
    loc.press = AsyncMock()
    loc.type = AsyncMock()
    loc.check = AsyncMock()
    loc.select_option = AsyncMock()
    loc.scroll_into_view_if_needed = AsyncMock()
    loc.wait_for = AsyncMock()
    loc.evaluate = AsyncMock(return_value=None)
    loc.get_attribute = AsyncMock(return_value=None)
    loc.first = loc
    loc.last = loc
    loc.nth = MagicMock(return_value=loc)
    loc.locator = MagicMock(return_value=loc)
    loc.filter = MagicMock(return_value=loc)
    loc.get_by_role = MagicMock(return_value=loc)
    loc.get_by_text = MagicMock(return_value=loc)
    return loc


@pytest.fixture
def mock_page(mock_locator: AsyncMock) -> AsyncMock:
    """A minimal Playwright Page double that returns mock_locator everywhere."""
    page = AsyncMock()
    page.url = "https://sales.geico.com/quote"
    page.title = AsyncMock(return_value="")
    page.inner_text = AsyncMock(return_value="")
    page.locator = MagicMock(return_value=mock_locator)
    page.get_by_role = MagicMock(return_value=mock_locator)
    page.get_by_text = MagicMock(return_value=mock_locator)
    page.get_by_label = MagicMock(return_value=mock_locator)
    page.evaluate = AsyncMock(return_value=None)
    page.wait_for_function = AsyncMock(return_value=None)
    page.wait_for_load_state = AsyncMock(return_value=None)
    page.wait_for_timeout = AsyncMock(return_value=None)
    page.keyboard = MagicMock()
    page.keyboard.press = AsyncMock()
    page.screenshot = AsyncMock(return_value=None)
    return page
