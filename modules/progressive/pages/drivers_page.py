"""
Driver pages for Progressive wizard.

Validated live 2026-04-09 with USDOT 2998569 (M&D CUSTOM FREIGHT LLC).

Flow:
  DriverSummary (auto-populated with Owner as policyholder)
  -> [Edit] opens AddDriver for existing driver, OR
  -> [Add] opens AddDriver for new driver
  -> AddDriver form (License State, License Number, Exclude?, Driving History?)
  -> Continue
  -> (optional) NoHit page if MVR lookup failed: prompts for SSN
  -> Continue
  -> BusinessInfo page
"""

from typing import Optional

from modules.progressive.pages.base_page import BasePage


class DriverSummaryPage(BasePage):
    """
    Driver Summary page - lists all drivers on the quote.
    URL: pageName=DriverSummary (title shows "Here are the drivers on the quote:")

    Each driver row has Edit + Remove buttons.
    Bottom: "Add another driver?" with Add button.
    """

    async def edit_driver(self, index: int = 0) -> None:
        """Click Edit on the Nth driver row to modify their details."""
        print(f"    [Progressive] Editing driver {index}...")
        edit_btns = self.page.get_by_role("button", name="Edit")
        await edit_btns.nth(index).click(timeout=10_000)
        await self.page.wait_for_load_state("networkidle", timeout=30_000)

    async def remove_driver(self, index: int = 0) -> None:
        """Click Remove on the Nth driver row."""
        remove_btns = self.page.get_by_role("button", name="Remove")
        await remove_btns.nth(index).click(timeout=10_000)
        await self.page.wait_for_load_state("networkidle", timeout=15_000)

    async def add_driver(self) -> None:
        """Click 'Add' under 'Add another driver?' to open AddDriver page."""
        print("    [Progressive] Adding new driver...")
        # There's an "Add" button in the "Add another driver?" section
        add_btn = self.page.get_by_role("button", name="Add", exact=True).last
        await add_btn.click(timeout=10_000)
        await self.page.wait_for_load_state("networkidle", timeout=30_000)

    async def click_continue(self) -> None:
        """Click Continue to proceed to BUSINESS step."""
        print("    [Progressive] Continuing to BUSINESS step...")
        btn = self.page.get_by_role("button", name="Continue").first
        await btn.click(timeout=10_000)
        await self.page.wait_for_load_state("networkidle", timeout=60_000)


class AddDriverPage(BasePage):
    """
    Add/Edit Driver form.
    URL: pageName=AddDriver

    Page title: "A few more questions about {FIRST_NAME}:"
    Link "{FIRST_NAME} isn't a driver" to decline this person as a driver.

    Fields validated:
      - Driver's License State (combobox) — default Texas
      - Driver's License Number (textbox)
      - "Exclude this driver from the policy? (No Coverage)" — radio Yes/No
      - "Has this driver had any accidents, claims or violations in the past 5 years?"
        — radio Yes/No (Driving History section)
      - Link "Need an SR22?"
      - Continue button

    Note: MVR/CLUE reports are NOT ordered here - "You'll be prompted to order those
    reports after the Rates page." So license number validation is lightweight.
    """

    async def fill_and_submit(
        self,
        license_state: str = "Texas",
        license_number: str = "",
        exclude_from_policy: bool = False,
        has_driving_history: bool = False,
    ) -> None:
        """Fill the AddDriver form and click Continue."""
        await self.page.wait_for_load_state("networkidle", timeout=30_000)

        if license_state:
            await self._select_license_state(license_state)
        if license_number:
            await self._fill_license_number(license_number)

        await self._set_exclude_driver(exclude_from_policy)
        await self._set_has_driving_history(has_driving_history)

        await self._click_continue()

    async def _select_license_state(self, state: str) -> None:
        """Select Driver's License State (default Texas)."""
        print(f"    [Progressive] Driver's license state: {state}")
        combo = self.page.get_by_role("combobox", name="Driver's License State")
        await combo.click()
        # Clear and retype
        await combo.fill(state)
        # Choose matching option
        opt = self.page.get_by_role("option", name=state).first
        if await opt.count() > 0:
            await opt.click(timeout=5_000)

    async def _fill_license_number(self, number: str) -> None:
        """Fill Driver's License Number."""
        print(f"    [Progressive] License number: {number[:4]}****")
        # Label is long; match partial
        box = self.page.get_by_role(
            "textbox", name="Driver's License Number", exact=False
        )
        await box.fill(number, timeout=5_000)

    async def _set_exclude_driver(self, exclude: bool) -> None:
        """Set 'Exclude this driver from the policy? (No Coverage)' radio."""
        answer = "Yes" if exclude else "No"
        print(f"    [Progressive] Exclude driver: {answer}")
        group = self.page.get_by_role(
            "radiogroup",
            name="Exclude this driver from the policy? (No Coverage)",
        )
        await group.get_by_role("radio", name=answer, exact=True).click()

    async def _set_has_driving_history(self, has_history: bool) -> None:
        """Set driving history Yes/No (accidents/claims/violations)."""
        answer = "Yes" if has_history else "No"
        print(f"    [Progressive] Has accidents/claims/violations: {answer}")
        # Match by start of the long question text
        group = self.page.get_by_role(
            "radiogroup",
            name="Has this driver had any accidents",
            exact=False,
        )
        await group.get_by_role("radio", name=answer, exact=True).click()

    async def _click_continue(self) -> None:
        """Click Continue to save driver."""
        print("    [Progressive] Saving driver...")
        btn = self.page.get_by_role("button", name="Continue").first
        await btn.click(timeout=10_000)
        await self.page.wait_for_load_state("networkidle", timeout=30_000)

    async def click_isnt_a_driver(self, first_name: str) -> None:
        """Click the '{first_name} isn't a driver' link to remove them."""
        link = self.page.get_by_role(
            "link", name=f"{first_name} isn't a driver"
        )
        if await link.count() == 0:
            link = self.page.locator(f"a:has-text(\"{first_name} isn't a driver\")")
        await link.click(timeout=10_000)
        await self.page.wait_for_load_state("networkidle", timeout=15_000)


class NoHitPage(BasePage):
    """
    'Order Results No Hit' page.
    URL: pageName=NoHit

    Appears when Progressive cannot validate the driver's license number against
    the DMV. Asks the user to verify info + provide Social Security Number so the
    MVR lookup can be retried.

    Fields shown (mostly prefilled):
      - Business Owner's Name (First + Last + Suffix)
      - Home Address (pre-filled)
      - City / State / Zip Code (pre-filled)
      - Date of Birth (pre-filled)
      - Social Security Number (REQUIRED, yellow highlight) <-- new field

    For the automation, this is a HALT condition — SSN is sensitive and we don't
    collect it. Report the issue and stop.
    """

    async def detect(self) -> bool:
        """Return True if this is the NoHit page (used after clicking Continue from DriverSummary)."""
        return "NoHit" in self.page.url or "Order Results" in await self.page.title()

    async def back(self) -> None:
        """Click Back to return to DriverSummary."""
        btn = self.page.get_by_role("button", name="Back")
        await btn.click(timeout=10_000)
        await self.page.wait_for_load_state("networkidle", timeout=15_000)
