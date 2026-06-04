"""Multi-vehicle navigation: add_vehicle must VERIFY it reached the
MostCommonVehicles tile picker before returning (a click that lands on a text
span can register without firing the ExtJS handler, leaving us on
VehicleSummary). These tests cover the _wait_for_tile_picker verification used
to confirm navigation."""

import pytest

from modules.progressive.pages.vehicles_page import VehicleSummaryPage


def _summary():
    return VehicleSummaryPage.__new__(VehicleSummaryPage)


class _Loc:
    def __init__(self, count):
        self._count = count

    async def count(self):
        return self._count


class _Page:
    def __init__(self, text_count):
        self._text_count = text_count

    def get_by_text(self, *a, **k):
        return _Loc(self._text_count)

    async def wait_for_timeout(self, ms):
        return None


@pytest.mark.asyncio
async def test_wait_for_tile_picker_true_by_pagename():
    page = _summary()

    async def _tok():
        return "MostCommonVehicles"
    page.current_page_token = _tok
    page.page = _Page(text_count=0)
    assert await page._wait_for_tile_picker(timeout_ms=500) is True


@pytest.mark.asyncio
async def test_wait_for_tile_picker_true_by_text():
    page = _summary()

    async def _tok():
        return "VehicleSummary"   # token doesn't match, but picker text present
    page.current_page_token = _tok
    page.page = _Page(text_count=1)
    assert await page._wait_for_tile_picker(timeout_ms=500) is True


@pytest.mark.asyncio
async def test_wait_for_tile_picker_false_when_absent():
    page = _summary()

    async def _tok():
        return "VehicleSummary"
    page.current_page_token = _tok
    page.page = _Page(text_count=0)
    # No picker by token or text -> must time out to False (the bug signature:
    # a registered-but-non-navigating click).
    assert await page._wait_for_tile_picker(timeout_ms=300) is False
