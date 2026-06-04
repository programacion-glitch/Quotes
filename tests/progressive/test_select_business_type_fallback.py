"""Test that _select_business_type falls back to 'Trucker' when the
commodity-derived filter finds no matching options."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from modules.progressive.pages.business_info_page import BusinessInfoPage


@pytest.mark.asyncio
async def test_unmappable_commodity_falls_back_to_trucker():
    """When the filter for the commodity-derived search term yields 0 options,
    the bot retries with 'Trucker' instead of leaving the combobox empty."""
    page = MagicMock()
    page.wait_for_timeout = AsyncMock()
    page.keyboard = MagicMock()
    page.keyboard.type = AsyncMock()

    # Combo locator (clickable + fillable)
    combo = MagicMock()
    combo.wait_for = AsyncMock()
    combo.click = AsyncMock()
    combo.fill = AsyncMock()

    # Two `get_by_role("option")` calls: first returns 0, second returns >=1.
    first_options = MagicMock()
    first_options.count = AsyncMock(return_value=0)
    first_options.first = MagicMock()
    second_options = MagicMock()
    second_options.count = AsyncMock(return_value=3)
    chosen = MagicMock()
    chosen.click = AsyncMock()
    second_options.first = chosen

    page.get_by_role = MagicMock(side_effect=[first_options, second_options])

    bp = BusinessInfoPage(page)
    bp.find_combo = AsyncMock(return_value=combo)
    bp._map_commodity_to_option = lambda c: ("Processed", None)

    await bp._select_business_type("Processed wood 33%, pipes 33%")

    # Combo was fill()'d twice — first with "Processed", then with "Trucker"
    fill_calls = [c.args[0] for c in combo.fill.call_args_list]
    assert "Processed" in fill_calls or any("Processed" in s for s in fill_calls)
    assert "Trucker" in fill_calls

    # An option was eventually clicked (the Trucker-matched one)
    chosen.click.assert_awaited()
