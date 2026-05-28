"""
AdditionalDetails page (FINAL DETAILS step in wizard).

URL: pageName=AdditionalDetails
Validated live 2026-05-25.

This is the LAST page before PAYMENT. For quote-only flows, we capture
the screenshot/PDF here and STOP. We do NOT click the Continue button
because that advances to the PAYMENT step which actually binds the policy.

Fields shown:
  - Agent of Record (combobox - usually pre-filled)
  - Employer Identification Number (EIN) (optional textbox)
  - Per-vehicle: VIN displayed, lender info if applicable
  - "Do you want to order MVR/CLUE reports for all drivers?" radio
"""

from typing import Optional

from modules.progressive.pages.base_page import BasePage


class FinalDetailsPage(BasePage):
    """Progressive wizard - AdditionalDetails page (FINAL DETAILS step).

    For quote-only flow, we land here, optionally fill EIN/MVR preference,
    take a screenshot, then STOP. Do not call .submit() unless you intend
    to actually purchase the policy.
    """

    async def land_and_review(
        self,
        ein: Optional[str] = None,
        order_mvr_reports: bool = False,
    ) -> None:
        """Land on the FINAL DETAILS page and fill optional fields.

        Does NOT click Continue. The caller should then capture price/screenshot.
        """
        await self.page.wait_for_load_state("networkidle", timeout=30_000)
        await self.remove_overlays()

        if ein:
            await self._fill_ein(ein)

        await self._set_mvr_order(order_mvr_reports)

        # IMPORTANT: We do NOT click Continue here.
        # The next step is PAYMENT which actually binds the policy.
        print("    [Progressive] Reached FINAL DETAILS - stopping before PAYMENT")

    async def _fill_ein(self, ein: str) -> None:
        print(f"    [Progressive] EIN: {ein}")
        box = self.page.get_by_role(
            "textbox",
            name="Employer Identification Number",
            exact=False,
        )
        if await box.count() > 0:
            await box.first.fill(ein)

    async def _set_mvr_order(self, order: bool) -> None:
        label = "Yes, order reports" if order else "No, do not order"
        print(f"    [Progressive] MVR/CLUE reports: {label}")
        group = self.page.get_by_role(
            "radiogroup",
            name="Do you want to order MVR/CLUE reports for all drivers?",
        )
        if await group.count() > 0:
            await group.get_by_role("radio", name=label).click()
            await self.page.wait_for_timeout(300)
