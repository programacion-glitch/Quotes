"""
More About Business page (BUSINESS step in wizard breadcrumb).

URL: pageName=MoreAboutBusiness
Validated live 2026-05-25 with USDOT 2998569 (M&D CUSTOM FREIGHT LLC).

Required fields:
  - "Is the customer currently insured?" Yes/No
  - "Does the customer have other coverages for the business?" GL/BOP/None
  - "Is an Electronic Logging Device (ELD) required to record hours of service?" Yes/No

Optional fields (have defaults):
  - Customer Email Address
  - Number of Named Additional Insureds (default 0)
  - Number of Named Waiver of Subrogation Holders (default 0)
  - Blanket Additional Insured endorsement (default No)
  - Blanket Waiver of Subrogation endorsement (default No)
  - Federal/state filings required (default No)
"""

from typing import Optional

from modules.progressive.pages.base_page import BasePage


class MoreBusinessPage(BasePage):
    """Progressive wizard - MoreAboutBusiness page (BUSINESS step)."""

    async def fill_and_submit(
        self,
        currently_insured: bool = False,
        other_coverages: str = "None",  # "General Liability" | "Business Owner's Policy" | "None"
        eld_required: bool = False,
        customer_email: Optional[str] = None,
        federal_filings_required: bool = False,
    ) -> None:
        """Fill the BUSINESS page and click Continue."""
        await self.page.wait_for_load_state("networkidle", timeout=30_000)
        await self.remove_overlays()

        if customer_email:
            await self._fill_email(customer_email)

        await self._answer_currently_insured(currently_insured)
        await self._answer_other_coverages(other_coverages)
        await self._answer_federal_filings(federal_filings_required)
        await self._answer_eld_required(eld_required)
        await self._click_continue()

    async def _fill_email(self, email: str) -> None:
        print(f"    [Progressive] Customer email: {email}")
        box = self.page.get_by_role("textbox", name="Customer Email Address")
        if await box.count() > 0:
            await box.first.fill(email)

    async def _answer_currently_insured(self, is_insured: bool) -> None:
        answer = "Yes" if is_insured else "No"
        print(f"    [Progressive] Currently insured (any carrier): {answer}")
        group = self.page.get_by_role(
            "radiogroup",
            name="Is the customer currently insured?",
            exact=False,
        )
        await group.get_by_role("radio", name=answer, exact=True).click()
        await self.page.wait_for_timeout(300)

    async def _answer_other_coverages(self, choice: str) -> None:
        valid = {"General Liability", "Business Owner's Policy", "None"}
        if choice not in valid:
            choice = "None"
        print(f"    [Progressive] Other coverages: {choice}")
        group = self.page.get_by_role(
            "radiogroup",
            name="Does the customer have other coverages for the business?",
        )
        await group.get_by_role("radio", name=choice, exact=True).click()
        await self.page.wait_for_timeout(300)

    async def _answer_federal_filings(self, required: bool) -> None:
        answer = "Yes" if required else "No"
        print(f"    [Progressive] Federal/state filings required: {answer}")
        group = self.page.get_by_role(
            "radiogroup",
            name="Are state or federal filings required?",
        )
        if await group.count() > 0:
            await group.get_by_role("radio", name=answer, exact=True).click()
            await self.page.wait_for_timeout(300)

    async def _answer_eld_required(self, required: bool) -> None:
        answer = "Yes" if required else "No"
        print(f"    [Progressive] ELD required: {answer}")
        group = self.page.get_by_role(
            "radiogroup",
            name="Is an Electronic Logging Device (ELD) required to record hours of service?",
        )
        await group.get_by_role("radio", name=answer, exact=True).click()
        await self.page.wait_for_timeout(300)

    async def _click_continue(self) -> None:
        print("    [Progressive] Continuing to RATES...")
        # Two Continue buttons (top + bottom); bottom is the safe one
        btn = self.page.get_by_role("button", name="Continue").last
        await btn.click(timeout=10_000)
        await self.page.wait_for_load_state("networkidle", timeout=60_000)
