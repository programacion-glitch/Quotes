import pytest
from unittest.mock import AsyncMock
from modules.progressive.pages.vehicles_page import AddVehiclePage
from modules.progressive.pages._exceptions import UnmappableValueError


class _Combo:
    def __init__(self, count, value="", visible=True):
        self._count = count
        self._value = value
        self._visible = visible

    @property
    def first(self):
        return self

    async def count(self):
        return self._count

    async def input_value(self):
        return self._value

    async def wait_for(self, state=None, timeout=None):
        if not self._visible:
            raise AssertionError("locator not visible")

    async def is_visible(self):
        return self._visible


def _set_gvw_page(*, combo_count, options, value="", visible=True):
    """AddVehiclePage with find_combo + _enumerate_gvw_options stubbed.

    `value` is the combo's current input value: non-empty means Progressive
    already VIN-decoded the GVW (skip); empty means a required selection.
    `visible=False` models the hidden-combo static-text case (pickups whose
    GVW row is VIN-decoded static text while the combo stays in the DOM).
    """
    page = AddVehiclePage.__new__(AddVehiclePage)
    page.warnings = []
    page.page = AsyncMock()  # for wait_for_timeout in the enumerate retry

    combo = _Combo(combo_count, value, visible)

    async def _find_combo(label):
        return combo
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
    """No combo element → VIN-decoded static text. Skip, never HALT."""
    page, selected = _set_gvw_page(combo_count=0, options=[])
    await page._set_gvw("9,000 lbs")
    assert "label" not in selected
    assert any("gross vehicle weight" in w for w in page.warnings)


@pytest.mark.asyncio
async def test_set_gvw_skips_when_combo_already_has_value():
    """A VIN-decoded pickup shows its GVW as the combo value ('6,001 to
    10,000') — leave it. The reliable discriminator is the value, not whether
    options enumerate (which races)."""
    page, selected = _set_gvw_page(combo_count=1, options=[], value="6,001 to 10,000")
    await page._set_gvw("9,000 lbs")  # must not raise, must not select
    assert "label" not in selected
    assert any("already set" in w for w in page.warnings)


@pytest.mark.asyncio
async def test_set_gvw_skips_when_combo_hidden():
    """Live pickups (F350/RAM 3500, 2026-06-10): GVW row shows VIN-decoded
    static text but ExtJS keeps a hidden EMPTY combobox in the DOM. Must skip
    — selecting on it fails / misreads a stray boundlist."""
    page, selected = _set_gvw_page(combo_count=1, value="", options=[], visible=False)
    await page._set_gvw("9.800 LBS")
    assert "label" not in selected
    assert any("hidden" in w for w in page.warnings)


@pytest.mark.asyncio
async def test_set_gvw_selects_when_empty_with_options():
    """Empty combo (e.g. dump truck) with real options → bucket + select."""
    page, selected = _set_gvw_page(
        combo_count=1, value="",
        options=["10,000 lbs or less", "10,001 - 26,000 lbs", "26,001 lbs or greater"],
    )
    await page._set_gvw("51.000 LBS")
    assert selected["label"] == "26,001 lbs or greater"


@pytest.mark.asyncio
async def test_set_gvw_empty_no_options_falls_back_to_catalog():
    """Regression (REPUBLIC dump truck): an EMPTY required combo whose dropdown
    won't enumerate must NOT be skipped — fall back to the seeded gvw catalog
    (heavy ranges) so 51,000 lbs still resolves to '45,001 or more' and the
    page can Continue."""
    page, selected = _set_gvw_page(combo_count=1, value="", options=[])
    await page._set_gvw("51.000 LBS")
    assert selected["label"] == "45,001 or more"


@pytest.mark.asyncio
async def test_set_gvw_halts_when_real_options_dont_fit():
    """Fail-loud preserved: empty combo, real options that fit neither the
    value nor the default → HALT instead of guessing."""
    page, _ = _set_gvw_page(combo_count=1, value="", options=["10,000 lbs or less"])
    with pytest.raises(UnmappableValueError):
        await page._set_gvw("51.000 LBS")
