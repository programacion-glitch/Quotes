"""VehicleSummaryPage.list_existing_units reads pre-loaded rows from the DOM."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.progressive.pages.vehicles_page import VehicleSummaryPage


@pytest.mark.asyncio
async def test_returns_empty_when_on_most_common_vehicles(mock_page):
    """Fresh quote landing on tile picker → no rows → empty list, no raise."""
    # Header that signals MostCommonVehicles instead of VehicleSummary
    header = AsyncMock()
    header.count = AsyncMock(return_value=1)
    mock_page.get_by_text = MagicMock(return_value=header)
    summary = VehicleSummaryPage(mock_page)
    result = await summary.list_existing_units()
    assert result == []


@pytest.mark.asyncio
async def test_returns_empty_when_dom_read_fails(mock_page):
    """Best-effort: if locator query raises, return [] and do not propagate."""
    mock_page.get_by_text = MagicMock(side_effect=RuntimeError("DOM gone"))
    summary = VehicleSummaryPage(mock_page)
    result = await summary.list_existing_units()
    assert result == []


@pytest.mark.asyncio
async def test_parses_row_with_vin_visible(mock_page):
    """A single VehicleSummary row with visible '2021 UTILITY DRY VAN · VIN: 1UYVS253XM7301310'
    must parse into an ExistingUnit with normalized identifier."""
    row = AsyncMock()
    row.text_content = AsyncMock(return_value="2021 UTILITY DRY VAN  VIN: 1UYVS253XM7301310  Edit  Remove")
    row.is_visible = AsyncMock(return_value=True)

    rows = AsyncMock()
    rows.count = AsyncMock(return_value=1)
    rows.nth = MagicMock(return_value=row)
    # Header probe must return zero so the MostCommon early-return doesn't fire.
    header = AsyncMock()
    header.count = AsyncMock(return_value=0)

    def get_by_text(text, **kwargs):
        if "Most common vehicles" in str(text):
            return header
        return rows

    mock_page.get_by_text = MagicMock(side_effect=get_by_text)
    # Rows are looked up via a CSS selector → page.locator
    mock_page.locator = MagicMock(return_value=rows)

    summary = VehicleSummaryPage(mock_page)
    result = await summary.list_existing_units()
    assert len(result) == 1
    assert result[0].vin == "1UYVS253XM7301310"
    assert result[0].year == 2021
    assert result[0].make == "UTILITY"
    assert "DRY VAN" in (result[0].model or "")
    assert result[0].identifier == "1UYVS253XM7301310"
