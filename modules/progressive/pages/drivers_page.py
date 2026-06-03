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
        """Click 'Add' under 'Add another driver?' to open AddDriver page.

        This is NOT the wizard Continue — it's a non-wizard action button
        that opens a sub-form. Use direct click with force=True.
        """
        print("    [Progressive] Adding new driver...")
        # Not a wizard Continue; use force=True for ExtJS button reliability.
        btn = self.page.get_by_role("button", name="Add", exact=True).last
        await btn.click(timeout=10_000, force=True)
        await self.page.wait_for_load_state("networkidle", timeout=30_000)

    async def click_continue(self) -> None:
        """Click Continue to proceed to BUSINESS step (wizard Continue)."""
        print("    [Progressive] Continuing to BUSINESS step...")
        await self.safe_click_continue(expect_url_changes_from="DriverSummary")


class AddDriverPage(BasePage):
    """
    Add/Edit Driver form.
    URL: pageName=AddDriver

    Page title: "A few more questions about {FIRST_NAME}:"
    Link "{FIRST_NAME} isn’t a driver" to decline this person as a driver.

    Fields validated:
      - Driver’s License State (combobox) — default Texas
      - Driver’s License Number (textbox)
      - "Exclude this driver from the policy? (No Coverage)" — radio Yes/No
      - "Has this driver had any accidents, claims or violations in the past 5 years?"
        — radio Yes/No (Driving History section)
      - Link "Need an SR22?"
      - Continue button

    Note: MVR/CLUE reports are NOT ordered here - "You’ll be prompted to order those
    reports after the Rates page." So license number validation is lightweight.
    """

    REQUIRED_FIELDS = ("license_state", "license_number")
    CONDITIONAL_FIELDS = ("exclude_from_policy", "has_driving_history")
    OPTIONAL_FIELDS = ()

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

        print("    [Progressive] Saving driver...")
        await self.safe_click_continue(expect_url_changes_from="AddDriver")

    async def _select_license_state(self, state: str) -> None:
        """Select Driver’s License State (default Texas).

        ExtJS combobox — uses safe_select_combo (click + option click).
        Progressive pre-fills the state from the policyholder’s address,
        so re-selecting Texas is usually a no-op; we still ensure the value.

        Tries multiple candidate accessible-name labels because Progressive’s
        aria-label for this combobox differs across page variants.
        """
        print(f"    [Progressive] Driver’s license state: {state}")
        candidates = [
            "Driver’s License State",
            "License State",
            "Driver License State",
        ]
        combo = None
        for label in candidates:
            c = await self.find_combo(label)
            if await self.field_exists(c, wait_ms=800):
                combo = c
                print(f"    [Progressive] License State combo matched on label=’{label}’")
                break
        if combo is None:
            print(f"    [Progressive] WARN: License State combobox not present (tried: {candidates}), skipping")
            return
        try:
            await self.safe_select_combo(combo.first, state)
        except Exception as e:
            print(f"    [Progressive] WARN: license state ‘{state}’ select failed: {e}")

    async def _fill_license_number(self, number: str) -> None:
        """Fill Driver’s License Number.

        The input has no placeholder/aria-label; its visible label is in a
        separate column. We use find_by_label_text as primary strategy, then
        fall back through XPath candidates. verify=False because license
        number inputs on Progressive are often masked after entry.
        """
        print(f"    [Progressive] License number: {number[:4]}****")
        # Primary: label-text XPath traversal via BasePage primitive
        primary = await self.find_by_label_text("License Number")
        # Fallback candidates in priority order (kept for resilience)
        candidates = [
            primary,
            self.page.locator(
                "xpath=//*[contains(normalize-space(text()), ‘License Number’)]"
                "/ancestor-or-self::*[1]/following::input[@type=’text’][1]"
            ),
            self.page.get_by_text("License Number", exact=False).first
                .locator("xpath=following::input[@type=’text’][1]"),
            self.page.get_by_role("textbox", name="Driver’s License Number", exact=False),
            self.page.get_by_placeholder("License Number", exact=False),
            self.page.get_by_label("License Number", exact=False),
        ]
        for idx, loc in enumerate(candidates):
            try:
                await loc.first.wait_for(state="visible", timeout=3_000)
                await loc.first.scroll_into_view_if_needed(timeout=2_000)
                # verify=False: license number inputs are often masked after entry
                await self.safe_fill(loc.first, number, verify=False)
                print(f"    [Progressive] License number filled OK (selector #{idx})")
                return
            except Exception:
                continue
        print("    [Progressive] WARN: License number textbox not found/filled")

    async def _set_exclude_driver(self, exclude: bool) -> None:
        """Set ‘Exclude this driver from the policy? (No Coverage)’ radio."""
        answer = "Yes" if exclude else "No"
        print(f"    [Progressive] Exclude driver: {answer}")
        group = await self.find_radiogroup(
            "Exclude this driver from the policy? (No Coverage)", exact=True
        )
        await self.safe_radio(group, answer)

    async def _set_has_driving_history(self, has_history: bool) -> None:
        """Set driving history Yes/No (accidents/claims/violations)."""
        answer = "Yes" if has_history else "No"
        print(f"    [Progressive] Has accidents/claims/violations: {answer}")
        # Partial match on start of the long question text
        group = await self.find_radiogroup("Has this driver had any accidents", exact=False)
        await self.safe_radio(group, answer)

    async def click_isnt_a_driver(self, first_name: str) -> None:
        """Click the ‘{first_name} isn’t a driver’ link to remove them."""
        link = self.page.get_by_role(
            "link", name=f"{first_name} isn’t a driver"
        )
        if await link.count() == 0:
            link = self.page.locator(f"a:has-text(\"{first_name} isn’t a driver\")")
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

    async def report_and_halt(self) -> None:
        """Screenshot the page for the operator and raise a clear HALT error.

        POLICY: Do NOT fill SSN — it is sensitive data not collected by this
        automation. The operator must handle this manually.
        """
        await self.screenshot("nohit_mvr_clue_failed")
        raise RuntimeError(
            "Progressive NoHit: MVR/CLUE lookup failed and SSN is required. "
            "This is a HALT condition — SSN must not be auto-filled. "
            "Operator intervention required."
        )

    async def back(self) -> None:
        """Click Back to return to DriverSummary (non-wizard navigation button)."""
        # Not a wizard Continue; direct click with force=True for ExtJS reliability.
        btn = self.page.get_by_role("button", name="Back")
        await btn.click(timeout=10_000, force=True)
        await self.page.wait_for_load_state("networkidle", timeout=15_000)
