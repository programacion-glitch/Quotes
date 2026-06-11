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
async def test_select_expands_other_not_listed_for_refrigerated():
    """Live (A&H): the common 'Most common trailers' tiles lack a refrigerated
    option, but 'Other / Not Listed' expands to the full taxonomy where
    'Refrigerated Dry Freight' lives. select_trailer_type must click the
    expander, re-enumerate, then select the real tile."""
    common = ["Bottom Dump", "Flatbed Trailer", "Bulk Commodity",
              "Dump Body Trailer", "Dry Freight Trailer", "Other / Not Listed"]
    full = common[:-1] + ["Gooseneck Trailer", "Refrigerated Dry Freight",
                          "Tank Trailer", "Horse Trailer", "Other / Not Listed"]

    page = MostCommonTrailersPage.__new__(MostCommonTrailersPage)
    calls = {"enum": 0}

    async def _enum():
        calls["enum"] += 1
        return common if calls["enum"] == 1 else full
    page._enumerate_tiles = _enum

    clicked = []

    async def _click(label):
        clicked.append(label)
    page._click_tile = _click

    async def _idle(*a, **k):
        return None
    page.wait_for_extjs_idle = _idle

    class _Pg:
        async def wait_for_timeout(self, ms):
            return None
    page.page = _Pg()

    async def _shot(name):
        return None
    page.screenshot = _shot

    # Post-click verification stubs: the AddTrailer form (Year combo)
    # "opens" on the first tile click.
    async def _find_combo(name, **kw):
        return object()
    page.find_combo = _find_combo

    async def _field_exists(loc, **kw):
        return True
    page.field_exists = _field_exists

    await page.select_trailer_type("REFRIGERATED TRAILER")

    assert clicked == ["Other / Not Listed", "Refrigerated Dry Freight"], clicked


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
