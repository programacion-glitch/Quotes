"""Tests for MostCommonTrailersPage.resolve_tile — fail-loud tile resolution.

Mirrors tests/progressive/test_vehicle_tile_resolution.py for trailers.
Uses __new__ + stub injection to avoid Playwright Page setup.
asyncio_mode=auto (pytest.ini) so @pytest.mark.asyncio is harmless.
"""

from __future__ import annotations

import pytest
from modules.progressive.pages.trailers_page import MostCommonTrailersPage
from modules.progressive.pages._exceptions import UnmappableValueError


def _mk(tiles):
    obj = MostCommonTrailersPage.__new__(MostCommonTrailersPage)

    async def _enum():
        return tiles
    obj._enumerate_tiles = _enum            # stub live enumeration

    async def _shot(name):
        return None
    obj.screenshot = _shot                  # stub BasePage.screenshot
    return obj


@pytest.mark.asyncio
async def test_resolve_trailer_tile_matches_gooseneck():
    page = _mk(["Dry Freight Trailer", "Flatbed Trailer", "Gooseneck Trailer"])
    res = await page.resolve_tile("GOOSENECK TRAILER")
    assert res.value == "Gooseneck Trailer"


@pytest.mark.asyncio
async def test_resolve_trailer_tile_halts_when_absent():
    # No matching tile on screen -> HALT, NOT a silent catch-all.
    page = _mk(["Dry Freight Trailer", "Flatbed Trailer", "Gooseneck Trailer"])
    with pytest.raises(UnmappableValueError) as exc:
        await page.resolve_tile("MONORAIL")
    assert "Gooseneck Trailer" in exc.value.available_options


@pytest.mark.asyncio
async def test_enumerate_trailer_tiles_filters_nav_tabs():
    obj = MostCommonTrailersPage.__new__(MostCommonTrailersPage)

    class _Pg:
        async def evaluate(self, js):
            return ["START", "VEHICLES", "RATES", "Dry Freight Trailer",
                    "Flatbed Trailer", "Gooseneck Trailer", "Other / Not Listed",
                    "Continue", "Edit"]
    obj.page = _Pg()
    tiles = await obj._enumerate_tiles()
    assert "Dry Freight Trailer" in tiles and "Gooseneck Trailer" in tiles
    assert "START" not in tiles and "RATES" not in tiles and "Continue" not in tiles
