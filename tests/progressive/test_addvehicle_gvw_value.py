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


class _Combo:
    def __init__(self, count):
        self._count = count

    async def count(self):
        return self._count


def _set_gvw_page(combo_count):
    """AddVehiclePage with find_combo returning a combo of the given count."""
    obj = AddVehiclePage.__new__(AddVehiclePage)
    obj.warnings = []

    async def _find_combo(label):
        return _Combo(combo_count)
    obj.find_combo = _find_combo
    return obj


@pytest.mark.asyncio
async def test_set_gvw_skips_when_combo_absent():
    """VIN-decoded GVW shows as static read-only text (no combo). The step
    must SKIP — never resolve against the partial catalog, never HALT."""
    page = _set_gvw_page(combo_count=0)

    async def _boom(raw):
        raise AssertionError("resolve_gvw_label must not run when combo absent")
    page.resolve_gvw_label = _boom

    await page._set_gvw("9,000 lbs")  # must not raise
    assert any("gross vehicle weight" in w for w in page.warnings)


@pytest.mark.asyncio
async def test_set_gvw_selects_when_combo_present():
    """Editable GVW combo present → resolve raw value and select it."""
    page = _set_gvw_page(combo_count=1)
    selected = {}

    async def _resolve(raw):
        assert raw == "51,000 lbs"
        return "26,001 lbs or greater"
    page.resolve_gvw_label = _resolve

    async def _select(combo, label):
        selected["label"] = label
    page.safe_select_combo = _select

    await page._set_gvw("51,000 lbs")
    assert selected["label"] == "26,001 lbs or greater"
