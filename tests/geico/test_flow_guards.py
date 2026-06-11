"""Flow guards: G4 (DriveEasy may be server-skipped) and G5 (no premium = fail).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from modules.geico.pages.additional_business_page import AdditionalBusinessPage
from modules.geico.pages.coverages_page import CoveragesPage


# ---------- G4: Step 5 Next must accept either next title ----------

async def test_step5_next_waits_for_either_driveeasy_or_coverages(mock_page):
    page_obj = AdditionalBusinessPage(mock_page)
    page_obj.wait_for_any_title = AsyncMock(return_value="Quote & Coverages")
    await page_obj._click_next()
    page_obj.wait_for_any_title.assert_awaited_once()
    candidates = page_obj.wait_for_any_title.await_args.args[0]
    assert "DriveEasy Pro" in candidates
    assert "Quote & Coverages" in candidates


async def test_step5_next_raises_when_neither_title_appears(mock_page):
    page_obj = AdditionalBusinessPage(mock_page)
    page_obj.wait_for_any_title = AsyncMock(side_effect=TimeoutError("none"))
    with pytest.raises(RuntimeError):
        await page_obj._click_next()


# ---------- G5: success without premium is not allowed ----------

async def test_capture_and_advance_fails_loud_when_no_premium(mock_page, mock_locator):
    # No qualifying premium on the page; Recalculate / term buttons absent.
    mock_locator.count = AsyncMock(return_value=0)
    mock_page.inner_text = AsyncMock(return_value="UM/UIM $582.00 PIP $183.00")
    page_obj = CoveragesPage(mock_page)
    with pytest.raises(RuntimeError) as exc_info:
        await page_obj.capture_and_advance()
    assert "premium" in str(exc_info.value).lower()
    # The guard must fire BEFORE any Next click.
    mock_locator.click.assert_not_awaited()
