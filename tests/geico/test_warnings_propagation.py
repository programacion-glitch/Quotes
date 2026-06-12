"""G11: fail-soft WARN paths must accumulate in page.warnings (not just
print) so quote_flow can harvest them into QuoteResult.warnings and the
batch report shows what was skipped/defaulted on each quote."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

from modules.geico.pages.additional_business_page import AdditionalBusinessPage
from modules.geico.pages.vehicles_page import VehicleEntryPage
from modules.geico.field_mapper import MappedVehicle

NO_MATCH = json.dumps({"error": "no-match"})


async def test_select_failure_lands_in_page_warnings(mock_page):
    # Every select finder JS call reports no matching <select>: the years-
    # operating block must fail SOFT and record the warning.
    mock_page.evaluate = AsyncMock(return_value=NO_MATCH)
    page_obj = AdditionalBusinessPage(mock_page)

    class F:
        years_operating = "7+"
        employee_count = "1"

    await page_obj._fill_business_metrics(F())
    assert len(page_obj.warnings) >= 1
    assert any("years operating" in w.lower() for w in page_obj.warnings)


async def test_vehicle_distance_select_failure_warns(mock_page, mock_locator):
    # Select-finder JS reports no matching <select>; every OTHER evaluate
    # (radio probes, validation-blocker check, mileage reader) returns None.
    def _evaluate(js, *args):
        return NO_MATCH if "findSelect" in js else None

    mock_page.evaluate = AsyncMock(side_effect=_evaluate)
    # Radios verify as checked so the flow reaches the distance select.
    mock_locator.is_checked = AsyncMock(return_value=True)
    page_obj = VehicleEntryPage(mock_page)
    vehicle = MappedVehicle(vin=None, vehicle_type="Tractor",
                            one_way_distance="51-100")
    await page_obj.fill_and_submit(vehicle)
    assert any("distance" in w.lower() for w in page_obj.warnings)
