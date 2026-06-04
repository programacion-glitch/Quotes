"""Test that _select_business_type routes directly to 'Trucker' via
safe_select_combo when the commodity is unmappable (preferred is None).

History: an earlier implementation tried `combo.fill(search_term)` to filter
the dropdown and then click the first remaining option. ExtJS comboboxes
don't reliably react to programmatic .fill() — the filter never narrowed,
options.count() > 0 was vacuously true against the full alphabetical list,
the bot clicked "Accountant" (the first option), and ExtJS dropped the
click, leaving the combobox empty. The current implementation skips the
broken filter entirely and calls safe_select_combo("Trucker") directly.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from modules.progressive.pages.business_info_page import BusinessInfoPage


@pytest.mark.asyncio
async def test_unmappable_commodity_routes_to_trucker_via_safe_select_combo():
    """When preferred is None (the commodity has no entry in the mapping
    table), the bot calls safe_select_combo(combo, 'Trucker') directly
    instead of attempting an unreliable filter+click fallback."""
    page = MagicMock()
    page.wait_for_timeout = AsyncMock()

    combo = MagicMock()
    combo.wait_for = AsyncMock()

    bp = BusinessInfoPage(page)
    bp.find_combo = AsyncMock(return_value=combo)
    bp.safe_select_combo = AsyncMock()
    bp._map_commodity_to_option = lambda c: ("Processed", None)

    await bp._select_business_type("Processed wood 33%, pipes 33%")

    # safe_select_combo should be called exactly once, with "Trucker"
    bp.safe_select_combo.assert_awaited_once()
    args = bp.safe_select_combo.call_args.args
    assert args[0] is combo
    assert args[1] == "Trucker"


@pytest.mark.asyncio
async def test_preferred_mapping_skips_trucker_fallback():
    """When the mapping table returns an explicit preferred option, the
    bot uses safe_select_combo(combo, preferred) and does NOT fall back to
    Trucker — preserving accurate underwriting for known commodities."""
    page = MagicMock()
    page.wait_for_timeout = AsyncMock()

    combo = MagicMock()
    combo.wait_for = AsyncMock()

    bp = BusinessInfoPage(page)
    bp.find_combo = AsyncMock(return_value=combo)
    bp.safe_select_combo = AsyncMock()
    bp._map_commodity_to_option = lambda c: ("Dirt Sand", "Dirt Sand & Gravel (For A Fee)")

    await bp._select_business_type("SAND & GRAVEL 100%")

    # safe_select_combo called once with the preferred label, NOT "Trucker"
    bp.safe_select_combo.assert_awaited_once()
    args = bp.safe_select_combo.call_args.args
    assert args[1] == "Dirt Sand & Gravel (For A Fee)"


@pytest.mark.asyncio
async def test_preferred_mapping_failure_falls_back_to_trucker():
    """When the mapping returns a preferred label but safe_select_combo
    raises (label not in the live dropdown), the bot falls back to
    Trucker rather than leaving the combobox empty."""
    page = MagicMock()
    page.wait_for_timeout = AsyncMock()

    combo = MagicMock()
    combo.wait_for = AsyncMock()

    bp = BusinessInfoPage(page)
    bp.find_combo = AsyncMock(return_value=combo)
    # First call raises (preferred label missing), second succeeds (Trucker)
    bp.safe_select_combo = AsyncMock(side_effect=[Exception("not found"), None])
    bp._map_commodity_to_option = lambda c: ("Foo", "Foo (For A Fee)")

    await bp._select_business_type("FOO 100%")

    assert bp.safe_select_combo.await_count == 2
    second_args = bp.safe_select_combo.await_args_list[1].args
    assert second_args[1] == "Trucker"
