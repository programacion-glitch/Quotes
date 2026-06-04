import pytest
from modules.progressive.pages.vehicles_page import AddVehiclePage
from modules.progressive.pages._exceptions import UnmappableValueError


def _page(gvw_options):
    obj = AddVehiclePage.__new__(AddVehiclePage)

    async def _enum():
        return gvw_options
    obj._enumerate_gvw_options = _enum

    async def _shot(name):
        return None
    obj.screenshot = _shot
    return obj


@pytest.mark.asyncio
async def test_resolve_gvw_label_buckets_live():
    page = _page(["10,000 lbs or less", "10,001 - 26,000 lbs", "26,001 lbs or greater"])
    label = await page.resolve_gvw_label("51.000 LBS")
    assert label == "26,001 lbs or greater"


@pytest.mark.asyncio
async def test_resolve_gvw_label_absent_defaults():
    page = _page(["10,000 lbs or less", "26,001 lbs or greater"])
    label = await page.resolve_gvw_label(None)
    assert label == "26,001 lbs or greater"


@pytest.mark.asyncio
async def test_resolve_gvw_label_garbage_halts():
    page = _page(["26,001 lbs or greater"])
    with pytest.raises(UnmappableValueError):
        await page.resolve_gvw_label("banana")
