import pytest
from unittest.mock import AsyncMock, MagicMock
from modules.progressive.pages.business_info_page import BusinessInfoPage
from modules.progressive.pages._exceptions import UnmappableValueError


def _biz():
    return BusinessInfoPage.__new__(BusinessInfoPage)


def test_unmappable_commodity_raises_instead_of_trucker():
    biz = _biz()
    with pytest.raises(UnmappableValueError) as exc:
        biz.resolve_business_type("PACKED CHARCOAL")
    assert exc.value.source_value == "PACKED CHARCOAL"


def test_specific_commodity_resolves():
    biz = _biz()
    res = biz.resolve_business_type("BEVERAGE DISTRIBUTION")
    assert res.value == "Beverage Distributor"


def test_general_freight_resolves_generic():
    biz = _biz()
    res = biz.resolve_business_type("DRY VAN FREIGHT")
    assert res.value == "General Freight Hauler"


def test_trucker_sentinel_resolves():
    biz = _biz()
    res = biz.resolve_business_type("Trucker")
    assert res.value == "Trucker"


@pytest.mark.asyncio
async def test_select_business_type_uses_resolved_specific_value():
    # specific commodity -> safe_select_combo called with the SPECIFIC option, not Trucker
    page = MagicMock()
    combo = MagicMock()
    combo.wait_for = AsyncMock()
    bp = BusinessInfoPage.__new__(BusinessInfoPage)
    bp.page = page
    bp.find_combo = AsyncMock(return_value=combo)
    bp.safe_select_combo = AsyncMock()
    await bp._select_business_type("SAND & GRAVEL 100%")
    bp.safe_select_combo.assert_awaited_once()
    assert bp.safe_select_combo.call_args.args[1] == "Dirt Sand & Gravel (For A Fee)"


@pytest.mark.asyncio
async def test_select_business_type_halts_on_unmappable():
    # unmappable commodity -> UnmappableValueError propagates, safe_select_combo NEVER called
    bp = BusinessInfoPage.__new__(BusinessInfoPage)
    bp.find_combo = AsyncMock()
    bp.safe_select_combo = AsyncMock()
    with pytest.raises(UnmappableValueError):
        await bp._select_business_type("PACKED CHARCOAL")
    bp.safe_select_combo.assert_not_awaited()
