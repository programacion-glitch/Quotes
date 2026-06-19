"""VehicleEntryPage.answer_leading_hazmat_if_present — Hazmat opens Step 3.

Live RODRIGUEZ 2026-06-17 (BUILDING MATERIALS): GEICO skipped the Hazmat
placard question on Step 1 and instead OPENED the Vehicles step with it, so the
VIN form ('Do you have it handy?') wasn't first. The flow answers the leading
Hazmat question (No, since the field mapper never sets hazmat) and clicks Next to
reveal the VIN form. No-op when the question isn't present (the common case).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from modules.geico.pages.vehicles_page import VehicleEntryPage


def _wire(ent: VehicleEntryPage) -> None:
    ent.click_question_radio = AsyncMock()
    ent.remove_overlays = AsyncMock()
    ent.click_button = AsyncMock()


async def test_answers_no_and_advances_when_hazmat_opens_step3(mock_page):
    ent = VehicleEntryPage(mock_page)
    _wire(ent)

    await ent.answer_leading_hazmat_if_present(False)

    ent.click_question_radio.assert_awaited_once()
    assert ent.click_question_radio.await_args.args[1] == "No"
    ent.click_button.assert_awaited_once_with("Next")


async def test_answers_yes_when_has_hazmat(mock_page):
    ent = VehicleEntryPage(mock_page)
    _wire(ent)

    await ent.answer_leading_hazmat_if_present(True)

    assert ent.click_question_radio.await_args.args[1] == "Yes"
    ent.click_button.assert_awaited_once_with("Next")


async def test_noop_when_no_hazmat_question(mock_page, mock_locator):
    mock_locator.is_visible = AsyncMock(return_value=False)
    ent = VehicleEntryPage(mock_page)
    _wire(ent)

    await ent.answer_leading_hazmat_if_present(False)

    ent.click_question_radio.assert_not_awaited()
    ent.click_button.assert_not_awaited()
