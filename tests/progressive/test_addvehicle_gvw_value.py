import pytest
from modules.progressive.pages.vehicles_page import AddVehiclePage
from modules.progressive.pages._exceptions import UnmappableValueError


class _Combo:
    def __init__(self, count):
        self._count = count

    async def count(self):
        return self._count


def _set_gvw_page(*, combo_count, options):
    """AddVehiclePage with find_combo + _enumerate_gvw_options stubbed."""
    page = AddVehiclePage.__new__(AddVehiclePage)
    page.warnings = []

    async def _find_combo(label):
        return _Combo(combo_count)
    page.find_combo = _find_combo

    async def _enum():
        return options
    page._enumerate_gvw_options = _enum

    async def _shot(name):
        return None
    page.screenshot = _shot

    selected = {}

    async def _select(combo, label):
        selected["label"] = label
    page.safe_select_combo = _select
    return page, selected


@pytest.mark.asyncio
async def test_set_gvw_skips_when_combo_absent():
    """VIN-decoded GVW shows as static read-only text (no combo). Skip — never
    resolve against a partial catalog, never HALT."""
    page, selected = _set_gvw_page(combo_count=0, options=[])
    await page._set_gvw("9,000 lbs")  # must not raise
    assert "label" not in selected
    assert any("gross vehicle weight" in w for w in page.warnings)


@pytest.mark.asyncio
async def test_set_gvw_skips_when_combo_present_but_no_live_options():
    """Regression: a combo element present but exposing NO selectable options
    is the VIN-decoded static display in a transient state. It must SKIP — not
    fall back to the partial seeded catalog and FALSE-HALT a light pickup."""
    page, selected = _set_gvw_page(combo_count=1, options=[])
    await page._set_gvw("9,000 lbs")  # must not raise (this was the live bug)
    assert "label" not in selected
    assert any("no live options" in w for w in page.warnings)


@pytest.mark.asyncio
async def test_set_gvw_selects_when_combo_present_with_options():
    """Genuine interactive combo with real options → bucket + select."""
    page, selected = _set_gvw_page(
        combo_count=1,
        options=["10,000 lbs or less", "10,001 - 26,000 lbs", "26,001 lbs or greater"],
    )
    await page._set_gvw("51.000 LBS")
    assert selected["label"] == "26,001 lbs or greater"


@pytest.mark.asyncio
async def test_set_gvw_halts_when_real_options_dont_fit():
    """Fail-loud preserved: when live options are real but the value fits none
    of them (and no default matches), HALT instead of guessing."""
    page, _ = _set_gvw_page(combo_count=1, options=["33,001 to 45,000", "45,001 or more"])
    with pytest.raises(UnmappableValueError):
        await page._set_gvw("9,000 lbs")
