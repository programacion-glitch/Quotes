"""Tests for MostCommonVehiclesPage.resolve_tile — fail-loud tile resolution.

Uses __new__ + stub injection to avoid Playwright Page setup.
asyncio_mode=auto (pytest.ini) so @pytest.mark.asyncio is harmless.
"""

from __future__ import annotations

import pytest
from modules.progressive.pages.vehicles_page import MostCommonVehiclesPage
from modules.progressive.pages._exceptions import UnmappableValueError


def _mk(tiles):
    obj = MostCommonVehiclesPage.__new__(MostCommonVehiclesPage)

    async def _enum():
        return tiles
    obj._enumerate_tiles = _enum            # stub live enumeration

    async def _shot(name):
        return None
    obj.screenshot = _shot                  # stub BasePage.screenshot
    return obj


@pytest.mark.asyncio
async def test_resolve_tile_matches_flatbed():
    page = _mk(["Truck Tractor", "Flatbed Truck", "Pickup Truck"])
    res = await page.resolve_tile("FLATBED DRY VAN")
    assert res.value == "Flatbed Truck"


@pytest.mark.asyncio
async def test_resolve_tile_halts_when_absent():
    # sand & gravel: no matching tile on screen -> HALT, NOT 'Other / Not Listed'
    page = _mk(["Truck Tractor", "Pickup Truck", "Dump Truck"])
    with pytest.raises(UnmappableValueError) as exc:
        await page.resolve_tile("MONORAIL SLED")
    assert "Dump Truck" in exc.value.available_options


@pytest.mark.asyncio
async def test_resolve_tile_halts_when_mapped_tile_absent_from_screen():
    # trailer maps to "Box Truck" but the live picker doesn't show it -> HALT
    page = _mk(["Truck Tractor", "Pickup Truck", "Dump Truck"])
    with pytest.raises(UnmappableValueError):
        await page.resolve_tile("UTILITY DRY VAN")


@pytest.mark.asyncio
async def test_enumerate_tiles_filters_nav_tabs():
    from modules.progressive.pages.vehicles_page import MostCommonVehiclesPage
    obj = MostCommonVehiclesPage.__new__(MostCommonVehiclesPage)
    class _Pg:
        async def evaluate(self, js):
            return ["START", "VEHICLES", "RATES", "Dump Truck", "Truck Tractor",
                    "Pickup Truck", "Other / Not Listed", "Continue", "Edit"]
    obj.page = _Pg()
    tiles = await obj._enumerate_tiles()
    assert "Dump Truck" in tiles and "Truck Tractor" in tiles
    assert "START" not in tiles and "RATES" not in tiles and "Continue" not in tiles
