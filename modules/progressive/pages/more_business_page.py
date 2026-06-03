"""
More About Business page (BUSINESS step in wizard breadcrumb).

URL: pageName=MoreAboutBusiness
Validated live 2026-06-01 with USDOT 2998569 (M&D CUSTOM FREIGHT LLC).

Required fields (current Progressive UI - 2026-06):
  - "Is the customer currently insured?" Yes/No radio
  - "Does the customer currently have any of the following insurance policies
     for their business?" — CHECKBOX GROUP: Business Owners Policy /
     General Liability / Workers' Compensation / None of the above
  - "Does the customer currently have, or will they purchase, any of the
     following insurance policies with Progressive within 45 days?" — second
     CHECKBOX GROUP with the same options.
  - "Is an Electronic Logging Device (ELD) required to record hours of
     service?" Yes/No radio

NOTE 2026-06-01: "Other coverages" used to be a radio group with options
"GL / BOP / None". Progressive split it into TWO checkbox groups (existing
policies + bundle-with-Progressive). To indicate "no extras" we tick
"None of the above" in BOTH groups.

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
        """Tick the appropriate checkbox(es) in BOTH 'other coverages' groups.

        Progressive replaced the old single radio (GL/BOP/None) with TWO
        checkbox groups: existing-policies + bundle-with-Progressive.

        For now we support only choice="None" (default) — tick
        "None of the above" in both groups. To support multi-select in the
        future, accept a list and tick each matching checkbox by label.
        """
        print(f"    [Progressive] Other coverages: {choice}")
        # Map the legacy choice string to checkbox labels.
        if choice in ("None", None, ""):
            target_labels = ["None of the above"]
        else:
            # legacy single value -> single checkbox (in the existing-policies group)
            target_labels = [choice]

        # Click ALL matching checkboxes (one per "Other coverages" question).
        for label in target_labels:
            checkboxes = self.page.get_by_role("checkbox", name=label, exact=True)
            n = await checkboxes.count()
            print(f"    [Progressive] Found {n} '{label}' checkbox(es); ticking each")
            for i in range(n):
                cb = checkboxes.nth(i)
                try:
                    if not await cb.is_checked():
                        await cb.click(timeout=5_000)
                        await self.page.wait_for_timeout(200)
                except Exception as e:
                    # If the checkbox is in a hidden container (e.g. when the
                    # form variant is the old radiogroup), fall through.
                    print(f"    [Progressive] WARN: checkbox '{label}'[{i}] click failed: {e}")

        # Legacy fallback: if the radiogroup variant still exists in some
        # Progressive flows, tick the matching radio. Safe no-op when the
        # checkboxes above already satisfied the requirement.
        legacy_group = self.page.get_by_role(
            "radiogroup",
            name="Does the customer have other coverages for the business?",
        )
        if await legacy_group.count() > 0:
            try:
                radio_label = choice if choice and choice != "None" else "None"
                await legacy_group.get_by_role("radio", name=radio_label, exact=True).click(timeout=3_000)
            except Exception:
                pass
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
        """Click Continue → RATES with retry + force=True + URL verify.

        Same flake pattern as VehicleSummary/AddDriver Continue: clicks are
        sometimes silently absorbed by Progressive's frontend.
        """
        print("    [Progressive] Continuing to RATES...")
        # Blur active field so ExtJS commits all radio/checkbox state.
        try:
            await self.page.evaluate(
                "() => { if (document.activeElement && document.activeElement.blur) document.activeElement.blur(); }"
            )
            await self.page.wait_for_timeout(400)
        except Exception:
            pass

        for attempt in range(3):
            try:
                # Two Continue buttons (top + bottom); bottom is the safe one
                btn = self.page.get_by_role("button", name="Continue").last
                await btn.scroll_into_view_if_needed(timeout=2_000)
                await btn.click(timeout=10_000, force=True)
            except Exception as e:
                print(f"    [Progressive] more_business Continue click failed: {e}")
            await self.page.wait_for_load_state("networkidle", timeout=60_000)
            await self.page.wait_for_timeout(1_500)
            if "MoreAboutBusiness" not in self.page.url:
                return  # advanced
            if attempt < 2:
                print(f"    [Progressive] more_business Continue did not advance; retry {attempt + 1}/2")
                await self.page.wait_for_timeout(2_500)
