"""More About Business page (BUSINESS step).

URL: pageName=MoreAboutBusiness

REQUIRED fields:
  - currently_insured (Yes/No radio)
  - other_coverages (checkbox group: None of the above by default)

CONDITIONAL fields (may not render for some commodities — soft-skipped):
  - eld_required          (NOT rendered for Beverage Distributor)
  - federal_filings_required

OPTIONAL fields:
  - customer_email
"""

from __future__ import annotations

from typing import List, Optional

from modules.progressive.pages.base_page import BasePage


class MoreBusinessPage(BasePage):
    """Progressive wizard - MoreAboutBusiness page (BUSINESS step)."""

    REQUIRED_FIELDS = ("currently_insured", "other_coverages")
    CONDITIONAL_FIELDS = ("eld_required", "federal_filings_required")
    OPTIONAL_FIELDS = ("customer_email",)

    def __init__(self, page):
        super().__init__(page)
        self.warnings: List[str] = []

    async def fill_and_submit(
        self,
        currently_insured: bool = False,
        other_coverages: str = "None",
        eld_required: bool = False,
        customer_email: Optional[str] = None,
        federal_filings_required: bool = False,
    ) -> None:
        await self.wait_for_extjs_idle()
        await self.remove_overlays()

        if customer_email:
            await self._fill_email(customer_email)

        await self._answer_currently_insured(currently_insured)
        await self._answer_other_coverages(other_coverages)
        await self._answer_federal_filings_conditional(federal_filings_required)
        await self._answer_eld_required_conditional(eld_required)
        await self.safe_click_continue(expect_url_changes_from="MoreAboutBusiness")

    async def _fill_email(self, email: str) -> None:
        print(f"    [Progressive] Customer email: {email}")
        box = self.page.get_by_role("textbox", name="Customer Email Address")
        if await box.count() > 0:
            await self.safe_fill(box.first, email)

    async def _answer_currently_insured(self, is_insured: bool) -> None:
        answer = "Yes" if is_insured else "No"
        print(f"    [Progressive] Currently insured: {answer}")
        group = await self.find_radiogroup("Is the customer currently insured?")
        await self.safe_radio(group, answer)

    async def _answer_other_coverages(self, choice: str) -> None:
        print(f"    [Progressive] Other coverages: {choice}")
        target_labels = ["None of the above"] if choice in ("None", None, "") else [choice]
        for label in target_labels:
            checkboxes = self.page.get_by_role("checkbox", name=label, exact=True)
            n = await checkboxes.count()
            print(f"    [Progressive] Found {n} '{label}' checkbox(es); ticking each")
            for i in range(n):
                cb = checkboxes.nth(i)
                try:
                    await self.safe_checkbox(cb, check=True)
                except Exception as e:
                    print(f"    [Progressive] WARN: checkbox '{label}'[{i}]: {e}")

    async def _answer_federal_filings_conditional(self, required: bool) -> None:
        answer = "Yes" if required else "No"
        group = await self.find_radiogroup("Are state or federal filings required?", timeout_ms=2000)
        if not await self.field_exists(group, wait_ms=1000):
            self._log_skipped("federal_filings_required", "field_not_rendered")
            return
        print(f"    [Progressive] Federal/state filings required: {answer}")
        await self.safe_radio(group, answer)

    async def _answer_eld_required_conditional(self, required: bool) -> None:
        answer = "Yes" if required else "No"
        group = await self.find_radiogroup(
            "Is an Electronic Logging Device (ELD) required",
            timeout_ms=2000,
        )
        if not await self.field_exists(group, wait_ms=1000):
            self._log_skipped("eld_required", "field_not_rendered_for_this_commodity")
            return
        print(f"    [Progressive] ELD required: {answer}")
        await self.safe_radio(group, answer)

    def _log_skipped(self, field: str, reason: str) -> None:
        msg = f"more_business: skipped '{field}' — {reason}"
        print(f"    [Progressive] {msg}")
        self.warnings.append(msg)
