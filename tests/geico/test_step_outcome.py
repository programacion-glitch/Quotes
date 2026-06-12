"""wait_for_step_outcome: dynamic multi-outcome wait for step submits.

The budget (60s) is a worst-case CAP for GEICO's slow backend, never a
sleep: success returns the instant the title flips, and FAILURES (visible
validation banner = the form refused the submit; GEICO's server-error page)
surface within one poll instead of burning the whole budget.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from modules.geico.pages.base_page import BasePage


async def test_returns_matched_title_immediately(mock_page):
    mock_page.title = AsyncMock(return_value="GEICO Business & Owner Info")
    bp = BasePage(mock_page)
    matched = await bp.wait_for_step_outcome(
        ["Business & Owner Info"], budget_ms=5_000
    )
    assert matched == "Business & Owner Info"
    # No polling delay on the happy path.
    mock_page.wait_for_timeout.assert_not_awaited()


async def test_accepts_any_of_multiple_titles(mock_page):
    mock_page.title = AsyncMock(return_value="GEICO Quote & Coverages")
    bp = BasePage(mock_page)
    matched = await bp.wait_for_step_outcome(
        ["DriveEasy Pro", "Quote & Coverages"], budget_ms=5_000
    )
    assert matched == "Quote & Coverages"


async def test_fails_fast_on_visible_validation(mock_page):
    mock_page.title = AsyncMock(return_value="GEICO Vehicles")
    mock_page.evaluate = AsyncMock(
        return_value={"kind": "validation",
                      "detail": "Please make a selection."}
    )
    bp = BasePage(mock_page)
    with pytest.raises(RuntimeError) as exc_info:
        await bp.wait_for_step_outcome(["Drivers & Incidents"], budget_ms=60_000)
    assert "refused" in str(exc_info.value).lower()
    assert "Please make a selection" in str(exc_info.value)


async def test_fails_fast_on_server_error_page(mock_page):
    mock_page.title = AsyncMock(return_value="GEICO")
    mock_page.evaluate = AsyncMock(return_value={"kind": "server-error"})
    bp = BasePage(mock_page)
    with pytest.raises(RuntimeError) as exc_info:
        await bp.wait_for_step_outcome(["Vehicles"], budget_ms=60_000)
    assert "transient" in str(exc_info.value).lower()


async def test_times_out_when_nothing_happens(mock_page):
    mock_page.title = AsyncMock(return_value="GEICO Vehicles")
    mock_page.evaluate = AsyncMock(return_value=None)
    bp = BasePage(mock_page)
    with pytest.raises(TimeoutError):
        await bp.wait_for_step_outcome(["Drivers & Incidents"], budget_ms=300)
