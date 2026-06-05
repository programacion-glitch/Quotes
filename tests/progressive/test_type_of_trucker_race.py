"""Regression: the 'Type of Trucker' conditional must not be silently skipped.

When the business type resolves to the generic 'Trucker', the 'Type of Trucker'
subtype combobox is REQUIRED but rendered asynchronously by ExtJS. A too-short
probe used to return early under live latency, leaving the field unanswered and
tripping 'Type of Trucker: This field is required' at Continue. It must now wait
generously and HALT loud if the combo never renders — while a genuinely-absent
combo for a NON-Trucker business type still skips silently.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from modules.progressive.choice_resolver import Resolution
from modules.progressive.pages.business_info_page import BusinessInfoPage
from modules.progressive.pages._exceptions import FieldNotFoundError


def _page(*, business_type_value: str, combo_present: bool):
    page = BusinessInfoPage.__new__(BusinessInfoPage)
    page.resolve_business_type = lambda commodity: Resolution(
        "Business type", business_type_value, "MATCHED", commodity, "generic"
    )
    page.wait_for_extjs_idle = AsyncMock()
    page.find_combo = AsyncMock(return_value=AsyncMock())
    page.field_exists = AsyncMock(return_value=combo_present)
    page.screenshot = AsyncMock(return_value="logs/shot.png")

    inner = AsyncMock()
    inner.wait_for_timeout = AsyncMock()
    page.page = inner
    return page


@pytest.mark.asyncio
async def test_trucker_required_combo_missing_halts():
    """Trucker business type + combo never renders → FieldNotFoundError."""
    page = _page(business_type_value="Trucker", combo_present=False)
    with pytest.raises(FieldNotFoundError):
        await page._answer_type_of_trucker("Processed wood 33%, pipes 33%")
    # It must have polled generously (12s), not the old 1.5s probe.
    page.field_exists.assert_awaited()
    _, kwargs = page.field_exists.await_args
    assert kwargs.get("wait_ms") == 12_000


@pytest.mark.asyncio
async def test_non_trucker_absent_combo_skips_silently():
    """A non-Trucker business type whose combo is absent skips without raising."""
    page = _page(business_type_value="Beverage Distributor", combo_present=False)
    # Must not raise.
    await page._answer_type_of_trucker("Bottled water distribution")
    _, kwargs = page.field_exists.await_args
    assert kwargs.get("wait_ms") == 1_500
