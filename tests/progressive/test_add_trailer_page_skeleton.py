"""Structural + unit tests for AddTrailerPage.

The flow tests verify `fill_from_mapped`'s shape against mocked Playwright
calls. The form was confirmed live (JUAREZ 2026-06-05) to be simpler than
AddVehicle:

    VIN → Year → Make → ZIP → distance → loan → (optional Comp/Coll + value) → Continue

There is NO trailer-type combobox (set on the tile picker), NO GVW, NO
tonnage/hitch/business-use on this form. The unit tests below pin the
behaviour of the new Year/Make/VIN helpers.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from modules.progressive.field_mapper import MappedVehicle
from modules.progressive.pages.trailers_page import AddTrailerPage


def _make_trailer(**overrides) -> MappedVehicle:
    """A MappedVehicle representing a real-VIN trailer with sensible defaults."""
    defaults = dict(
        vin="16V3F4823T6450627",
        year=2026,
        make="BIGT 16G",
        model="GOOSENECK",
        trailer_type="Gooseneck Trailer",
        gvw="15,950 lbs",
        radius_miles="Over 500 miles",
        has_loan="No",
        garaging_zip="77053",
        value=None,
        is_trailer=True,
    )
    defaults.update(overrides)
    return MappedVehicle(**defaults)


def _wire_common(page, mock_page):
    """Stub the BasePage primitives a flow test doesn't care about."""
    page.safe_fill = AsyncMock()
    page.safe_radio = AsyncMock()
    page.safe_checkbox = AsyncMock()
    page.safe_select_combo = AsyncMock()
    page.safe_click_continue = AsyncMock()
    # Stub _click_continue to skip the validation-banner DOM check (which trips
    # on the conftest mock_locator defaults of count=1, is_visible=True).
    page._click_continue = AsyncMock()
    page.find_combo = AsyncMock(return_value=mock_page.get_by_role("combobox"))
    page.find_radiogroup = AsyncMock(return_value=mock_page.get_by_role("radiogroup"))
    page.field_exists = AsyncMock(return_value=True)
    page.wait_for_extjs_idle = AsyncMock()
    page.wait_for_currency_formatted = AsyncMock()
    page.screenshot = AsyncMock()
    page.dump_debug_context = AsyncMock(return_value={})
    page.blur_active_element = AsyncMock()


@pytest.mark.asyncio
async def test_fill_from_mapped_liability_only_completes_without_error(mock_page):
    """A trailer with no value should drive Comp/Coll=No and skip the value path."""
    page = AddTrailerPage(mock_page)
    _wire_common(page, mock_page)

    await page.fill_from_mapped(_make_trailer(value=None))

    page._click_continue.assert_awaited()
    # Value fill must NOT be triggered when value is None
    page.wait_for_currency_formatted.assert_not_awaited()


@pytest.mark.asyncio
async def test_fill_from_mapped_apd_yes_triggers_value_path(mock_page):
    """A trailer with value set should drive Comp/Coll=Yes, tick no-equipment, fill value."""
    page = AddTrailerPage(mock_page)
    _wire_common(page, mock_page)
    fill_value_mock = AsyncMock()
    page._fill_vehicle_value = fill_value_mock

    await page.fill_from_mapped(_make_trailer(value="25000"))

    fill_value_mock.assert_awaited()
    page._click_continue.assert_awaited()


@pytest.mark.asyncio
async def test_fill_from_mapped_loan_path_skips_apd_question(mock_page):
    """When has_loan='Loan', Progressive auto-requires Comp/Coll;
    the bot must NOT click the Comp/Coll radio."""
    page = AddTrailerPage(mock_page)
    _wire_common(page, mock_page)
    fill_value_mock = AsyncMock()
    page._fill_vehicle_value = fill_value_mock

    await page.fill_from_mapped(_make_trailer(has_loan="Loan", value="25000"))

    # Comp/Coll branch should be skipped entirely; value-fill not called
    fill_value_mock.assert_not_awaited()
    page._click_continue.assert_awaited()


# ---- Year / Make helpers ----


def _combo_page(*, count: int, current_value: str):
    """AddTrailerPage whose find_combo returns a combo with the given state."""
    page = AddTrailerPage.__new__(AddTrailerPage)
    page.warnings = []

    combo = AsyncMock()
    combo.count = AsyncMock(return_value=count)
    combo.first = combo
    combo.input_value = AsyncMock(return_value=current_value)

    async def _find_combo(label):
        return combo
    page.find_combo = _find_combo
    return page, combo


@pytest.mark.asyncio
async def test_set_year_selects_when_empty():
    page, combo = _combo_page(count=1, current_value="")
    selected = {}

    async def _select(c, val):
        selected["val"] = val
    page.safe_select_combo = _select

    await page._set_year(2026)
    assert selected["val"] == "2026"


@pytest.mark.asyncio
async def test_set_year_skips_when_vin_already_decoded():
    """If the VIN auto-populated Year, don't overwrite it."""
    page, combo = _combo_page(count=1, current_value="2026")

    async def _boom(c, val):
        raise AssertionError("must not select Year when combo already has a value")
    page.safe_select_combo = _boom

    await page._set_year(2026)  # must not raise


@pytest.mark.asyncio
async def test_set_make_warns_and_continues_on_no_match():
    """An unmatched Make must NOT HALT — it logs a warning and lets the
    Continue-step validation surface the real required-field state."""
    page, combo = _combo_page(count=1, current_value="")

    async def _select(c, val):
        raise RuntimeError("no option matched")
    page.safe_select_combo = _select

    await page._set_make("BIGT 16G")  # must not raise
    assert any("make" in w.lower() for w in page.warnings)


@pytest.mark.asyncio
async def test_set_make_skips_when_combo_absent():
    page, combo = _combo_page(count=0, current_value="")

    async def _boom(c, val):
        raise AssertionError("must not select Make when combo is absent")
    page.safe_select_combo = _boom

    await page._set_make("BIGT 16G")  # must not raise
    assert any("make" in w.lower() for w in page.warnings)
