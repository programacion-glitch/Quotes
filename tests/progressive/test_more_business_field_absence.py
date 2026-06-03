"""Verify MoreBusinessPage soft-skips fields not rendered for this commodity.

Reproduces the RYD LLC bug: ELD radio doesn't render for Beverage Distributor.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.progressive.pages.more_business_page import MoreBusinessPage


@pytest.mark.asyncio
async def test_eld_skipped_when_radio_not_present(mock_page, mock_locator):
    """When the ELD radiogroup is absent, fill_and_submit must NOT raise."""
    eld_locator = AsyncMock()
    eld_locator.count = AsyncMock(return_value=0)
    eld_locator.wait_for = AsyncMock(side_effect=TimeoutError("not visible"))

    insured_group = AsyncMock()
    insured_radio = AsyncMock()
    insured_radio.click = AsyncMock()
    insured_radio.check = AsyncMock()
    insured_radio.is_checked = AsyncMock(return_value=True)
    insured_group.get_by_role = MagicMock(return_value=insured_radio)

    filings_group = AsyncMock()
    filings_group.count = AsyncMock(return_value=0)
    filings_group.wait_for = AsyncMock(side_effect=TimeoutError("not visible"))

    none_checkbox = AsyncMock()
    none_checkbox.is_checked = AsyncMock(return_value=True)
    none_checkbox.click = AsyncMock()

    def get_by_role(role, **kwargs):
        n = (kwargs.get("name") or "").lower()
        if "currently insured" in n:
            return insured_group
        if "filings required" in n:
            return filings_group
        if "electronic logging device" in n or "eld" in n:
            return eld_locator
        if role == "checkbox":
            return none_checkbox
        return AsyncMock()

    mock_page.get_by_role = MagicMock(side_effect=get_by_role)

    urls = iter([
        "https://x.com/?pageName=MoreAboutBusiness",
        "https://x.com/?pageName=Rates",
    ])
    type(mock_page).url = property(lambda self: next(urls, "https://x.com/?pageName=Rates"))

    page_obj = MoreBusinessPage(mock_page)
    page_obj.warnings = []

    await page_obj.fill_and_submit(
        currently_insured=False,
        other_coverages="None",
        eld_required=False,
    )

    assert any("eld" in w.lower() and "skip" in w.lower() for w in page_obj.warnings), \
        f"Expected ELD-skipped warning, got: {page_obj.warnings}"


@pytest.mark.asyncio
async def test_snapshot_proview_skipped_when_radio_not_present(mock_page, mock_locator):
    """When the Snapshot ProView radiogroup is absent, fill_and_submit must NOT raise."""
    proview_locator = AsyncMock()
    proview_locator.count = AsyncMock(return_value=0)
    proview_locator.wait_for = AsyncMock(side_effect=TimeoutError("not visible"))

    insured_group = AsyncMock()
    insured_radio = AsyncMock()
    insured_radio.click = AsyncMock()
    insured_radio.check = AsyncMock()
    insured_radio.is_checked = AsyncMock(return_value=True)
    insured_group.get_by_role = MagicMock(return_value=insured_radio)

    filings_group = AsyncMock()
    filings_group.count = AsyncMock(return_value=0)
    filings_group.wait_for = AsyncMock(side_effect=TimeoutError("not visible"))

    eld_group = AsyncMock()
    eld_group.count = AsyncMock(return_value=0)
    eld_group.wait_for = AsyncMock(side_effect=TimeoutError("not visible"))

    none_checkbox = AsyncMock()
    none_checkbox.is_checked = AsyncMock(return_value=True)
    none_checkbox.click = AsyncMock()

    def get_by_role(role, **kwargs):
        n = (kwargs.get("name") or "").lower()
        if "currently insured" in n:
            return insured_group
        if "filings required" in n:
            return filings_group
        if "electronic logging device" in n or "eld" in n:
            return eld_group
        if "eligible for additional savings" in n or "snapshot" in n or "proview" in n:
            return proview_locator
        if role == "checkbox":
            return none_checkbox
        return AsyncMock()

    mock_page.get_by_role = MagicMock(side_effect=get_by_role)

    urls = iter([
        "https://x.com/?pageName=MoreAboutBusiness",
        "https://x.com/?pageName=Rates",
    ])
    type(mock_page).url = property(lambda self: next(urls, "https://x.com/?pageName=Rates"))

    page_obj = MoreBusinessPage(mock_page)
    page_obj.warnings = []

    await page_obj.fill_and_submit(
        currently_insured=False,
        other_coverages="None",
        eld_required=False,
        snapshot_proview=False,
    )

    assert any("snapshot_proview" in w.lower() and "skip" in w.lower() for w in page_obj.warnings), \
        f"Expected snapshot_proview-skipped warning, got: {page_obj.warnings}"
