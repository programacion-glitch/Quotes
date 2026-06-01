"""
Driver pages for the GEICO wizard (Step 4: Drivers & Incidents).

Step 4 is internally three sub-pages that the wizard cycles through:

  DriverPlaceholderPage   -> "We need some more info about {OWNER_FIRST_NAME}"
                             GEICO auto-creates a placeholder driver tied to the
                             business owner (even when our field_mapper sets
                             `owner_is_driver=False`). We satisfy the minimum
                             requirements (license state + CDL) and proceed.
  AddDriverPage           -> "Add a Driver" form for each non-excluded driver.
  DriverSummaryPage       -> List of added drivers + "Add Driver" list item +
                             "Looks Good" button that advances to Step 5.

Selectors / quirks validated live (see docs/Proceso GEICO.md "Step 4: Drivers
& Incidents"):

  - Driver License State is a native `<select>` whose id is dynamic per page
    load. We use `select_by_options_signature(["Alabama","Wyoming"], ...)` —
    the option list is the 50 US states and is the stable signature.
  - Suffix combobox is also a native `<select>`. Options are
    `(empty) / JR / SR / I / II / III / IV / V / 2ND / 3RD / MD`.
  - CDL Yes/No and Relationship radios live inside shadow DOM. The clickable
    proxies have ids like `*-DriverCDLYes-shadow` / `*-DriverCDLNo-shadow`
    and `*-RelationshipOwner-shadow` / `*-RelationshipEmployee-shadow`.
  - For the owner placeholder, when the owner is excluded we default CDL to
    `No` — the placeholder is kept (GEICO requires it) but the owner is
    excluded from rating via the relationship/excluded flag on Step 2.
  - License NUMBER is NOT collected on this page; it is collected later on
    Step 7 (Final Quote Details). Do not attempt to fill it here.
  - Incidents (accidents/violations) are out of scope for Block 3 — if a
    driver has `has_incidents=True` we log a warning and continue without
    filling incidents.
  - The "Add Driver" entry on the summary page is a list item (not a
    button) — same pattern as VehicleSummaryPage.
  - "Looks Good" advances the wizard's document.title to
    "Additional Business Info" (Step 5).

This file mirrors the multi-class layout of
`modules/progressive/pages/drivers_page.py` so `quote_flow` can loop in the
same way: placeholder -> add driver -> summary -> (add another | looks good).
"""

from modules.geico.field_mapper import MappedDriver
from modules.geico.pages.base_page import BasePage


# Signature for the Driver's License State native <select>. The 50 US-state
# list is invariant across page loads, so first + last alphabetical state make
# a unique signature regardless of dynamic ids.
_LICENSE_STATE_OPTIONS_SIGNATURE = ["Alabama", "Wyoming"]

# Suffix combobox signature. Options observed live:
# (empty) / JR / SR / I / II / III / IV / V / 2ND / 3RD / MD
_SUFFIX_OPTIONS_SIGNATURE = ["JR", "MD"]


class DriverPlaceholderPage(BasePage):
    """Sub-page 1 of Step 4: owner placeholder driver form.

    GEICO auto-creates a driver placeholder tied to the business owner —
    even when our field_mapper says `owner_is_driver=False`. We satisfy
    the minimum required fields (license state + CDL Yes/No) so we can
    advance to "Add a Driver". The owner is still excluded from rating
    via the relationship flag set on Step 2.
    """

    async def fill_owner_placeholder(self, owner_driver: MappedDriver) -> None:
        """Fill the owner placeholder form and click Next.

        Pre-state: "We need some more info about {OWNER_FIRST_NAME}" title.
        Post-state: "Add a Driver" page (or DriverSummary if GEICO skips ahead).
        """
        print(
            f"    [GEICO] Step 4: owner placeholder for "
            f"{owner_driver.first_name or '(unknown)'}"
        )
        await self.page.wait_for_load_state("networkidle", timeout=30_000)
        await self._wait_for_placeholder_content()
        await self.remove_overlays()

        await self._select_license_state(owner_driver)
        await self._answer_has_cdl(owner_driver)
        await self._click_next()

    async def _wait_for_placeholder_content(self) -> None:
        """Wait until the owner-placeholder form has actually mounted.

        The Step 3 -> Step 4 transition is title-gated upstream, but the
        placeholder's own fields can paint a beat later. Wait for the
        Driver's License State <select> (50-state signature) to exist so we
        don't probe a half-rendered form. Soft-fails: if the marker never
        appears we fall through and let the field helpers report precisely.
        """
        try:
            await self.page.wait_for_function(
                """() => {
                    const sels = Array.from(document.querySelectorAll('select'))
                        .filter(s => !s.disabled);
                    return sels.some(s => {
                        const t = Array.from(s.options).map(o => (o.text||'').trim());
                        return t.some(x => x.includes('Alabama'))
                            && t.some(x => x.includes('Wyoming'));
                    });
                }""",
                timeout=20_000,
            )
        except Exception:
            print(
                "    [GEICO] WARN: owner-placeholder license-state select not "
                "detected within 20s; proceeding anyway"
            )

    async def _select_license_state(self, owner_driver: MappedDriver) -> None:
        """Driver's License State combobox — native <select>, dynamic id."""
        state = owner_driver.license_state or "Texas"
        print(f"    [GEICO] Step 4: owner placeholder license state -> {state}")
        try:
            await self.select_by_options_signature(
                _LICENSE_STATE_OPTIONS_SIGNATURE, state
            )
        except Exception as e:
            print(
                f"    [GEICO] WARN: owner placeholder license state "
                f"select failed: {e}"
            )
            await self.screenshot("step4_placeholder_license_state_error")

    async def _answer_has_cdl(self, owner_driver: MappedDriver) -> None:
        """CDL Yes/No radio. When owner is excluded, default to No (the
        placeholder is kept but the owner is excluded from rating via the
        relationship flag set on Step 2)."""
        if owner_driver.is_excluded:
            answer = False
            print(
                "    [GEICO] Step 4: owner placeholder CDL -> No "
                "(owner excluded; placeholder kept)"
            )
        else:
            answer = bool(owner_driver.has_cdl)
            print(
                f"    [GEICO] Step 4: owner placeholder CDL -> "
                f"{'Yes' if answer else 'No'}"
            )
        try:
            await self.click_question_radio(
                "does this driver have a CDL", "Yes" if answer else "No"
            )
        except Exception as e:
            print(f"    [GEICO] WARN: owner placeholder CDL radio failed: {e}")
            await self.screenshot("step4_placeholder_cdl_error")

    async def _click_next(self) -> None:
        """Click the Next button at the bottom of the placeholder form."""
        print("    [GEICO] Step 4: submitting owner placeholder...")
        await self.remove_overlays()
        try:
            btn = self.page.get_by_role("button", name="Next")
            await btn.first.click(timeout=10_000)
            await self.page.wait_for_load_state("networkidle", timeout=30_000)
        except Exception as e:
            await self.screenshot("step4_placeholder_next_error")
            raise RuntimeError(
                f"Failed to click Next on owner placeholder: {e}"
            ) from e


class AddDriverPage(BasePage):
    """Sub-page 2 of Step 4: 'Add a Driver' form for non-excluded drivers.

    Auto-appears after `DriverPlaceholderPage.fill_owner_placeholder()` and
    again after each `DriverSummaryPage.add_another()`. License number is
    NOT collected here — it is collected on Step 7 (Final Quote Details).
    """

    async def fill_and_submit(self, driver: MappedDriver) -> None:
        """Fill the Add Driver form and click Save and Continue.

        Steps follow docs/Proceso GEICO.md Step 4 sub-page 2.
        """
        print(
            f"    [GEICO] Step 4: adding driver "
            f"{driver.first_name} {driver.last_name}"
        )
        await self.page.wait_for_load_state("networkidle", timeout=30_000)
        await self.remove_overlays()

        await self._fill_first_name(driver)
        await self._fill_last_name(driver)
        await self._select_suffix(driver)
        await self._fill_date_of_birth(driver)
        await self._select_license_state(driver)
        await self._answer_relationship(driver)
        await self._answer_has_cdl(driver)
        await self._handle_incidents(driver)
        await self._click_save_and_continue()

    async def _fill_first_name(self, driver: MappedDriver) -> None:
        if not driver.first_name:
            print("    [GEICO] WARN: driver missing first_name, skipping field")
            return
        try:
            print(f"    [GEICO] Step 4: First Name -> {driver.first_name}")
            box = self.page.get_by_role("textbox", name="First Name")
            await box.first.wait_for(state="visible", timeout=10_000)
            await box.first.fill(driver.first_name, timeout=5_000)
        except Exception as e:
            print(f"    [GEICO] WARN: First Name fill failed: {e}")
            await self.screenshot("step4_add_driver_first_name_error")

    async def _fill_last_name(self, driver: MappedDriver) -> None:
        if not driver.last_name:
            print("    [GEICO] WARN: driver missing last_name, skipping field")
            return
        try:
            print(f"    [GEICO] Step 4: Last Name -> {driver.last_name}")
            box = self.page.get_by_role("textbox", name="Last Name")
            await box.first.wait_for(state="visible", timeout=10_000)
            await box.first.fill(driver.last_name, timeout=5_000)
        except Exception as e:
            print(f"    [GEICO] WARN: Last Name fill failed: {e}")
            await self.screenshot("step4_add_driver_last_name_error")

    async def _select_suffix(self, driver: MappedDriver) -> None:
        """Suffix is optional — only set when the driver record has one."""
        if not driver.suffix:
            return
        try:
            print(f"    [GEICO] Step 4: Suffix -> {driver.suffix}")
            await self.select_by_options_signature(
                _SUFFIX_OPTIONS_SIGNATURE, driver.suffix
            )
        except Exception as e:
            print(f"    [GEICO] WARN: Suffix select failed: {e}")
            await self.screenshot("step4_add_driver_suffix_error")

    async def _fill_date_of_birth(self, driver: MappedDriver) -> None:
        if not driver.date_of_birth:
            print("    [GEICO] WARN: driver missing date_of_birth")
            return
        try:
            print(f"    [GEICO] Step 4: DOB -> {driver.date_of_birth}")
            dob_box = self.page.get_by_label("Date of Birth")
            if await dob_box.count() == 0:
                dob_box = self.page.locator('[id*="DateOfBirth" i]').first
            await dob_box.first.wait_for(state="visible", timeout=10_000)
            await dob_box.first.fill(driver.date_of_birth, timeout=5_000)
            await self.page.keyboard.press("Tab")
            await self.page.wait_for_timeout(300)
        except Exception as e:
            print(f"    [GEICO] WARN: DOB fill failed: {e}")
            await self.screenshot("step4_add_driver_dob_error")

    async def _select_license_state(self, driver: MappedDriver) -> None:
        state = driver.license_state or "Texas"
        try:
            print(f"    [GEICO] Step 4: License State -> {state}")
            await self.select_by_options_signature(
                _LICENSE_STATE_OPTIONS_SIGNATURE, state
            )
        except Exception as e:
            print(f"    [GEICO] WARN: License State select failed: {e}")
            await self.screenshot("step4_add_driver_license_state_error")

    async def _answer_relationship(self, driver: MappedDriver) -> None:
        """Relationship to the business: Owner / Employee / Other.

        The owner already has a separate placeholder driver, so a driver
        added through this form is, by construction, not the owner.
        Default to Employee. If the driver record happens to be flagged
        as the owner (defensive), click Owner instead.
        """
        relationship = "Owner" if driver.is_owner else "Employee"
        print(f"    [GEICO] Step 4: Relationship -> {relationship}")
        try:
            await self.click_question_radio(
                "what is their relationship to the business", relationship
            )
        except Exception as e:
            print(f"    [GEICO] WARN: Relationship radio click failed: {e}")
            await self.screenshot("step4_add_driver_relationship_error")

    async def _answer_has_cdl(self, driver: MappedDriver) -> None:
        answer = bool(driver.has_cdl)
        print(
            f"    [GEICO] Step 4: CDL -> {'Yes' if answer else 'No'}"
        )
        try:
            await self.click_question_radio(
                "does this driver have a CDL", "Yes" if answer else "No"
            )
        except Exception as e:
            print(f"    [GEICO] WARN: CDL radio failed: {e}")
            await self.screenshot("step4_add_driver_cdl_error")

    async def _handle_incidents(self, driver: MappedDriver) -> None:
        """Block 3 scope: skip incidents.

        If the BlueQuote indicates accidents/violations, log a warning so
        the operator knows the driving history was not entered. The MVR
        check on Step 8 will surface real violations regardless.
        """
        if driver.has_incidents:
            print(
                f"    [GEICO] WARN: driver "
                f"{driver.first_name} {driver.last_name} has_incidents=True "
                f"but incident entry is OUT OF SCOPE for Block 3 — leaving "
                f"driving history blank (MVR on Step 8 will catch violations)"
            )

    async def _click_save_and_continue(self) -> None:
        """Click 'Save and Continue' to advance to the Driver Summary page."""
        print("    [GEICO] Step 4: submitting Add Driver form...")
        await self.remove_overlays()
        try:
            btn = self.page.get_by_role("button", name="Save and Continue")
            if await btn.count() == 0:
                # Some builds label it differently.
                btn = self.page.get_by_role("button", name="Save & Continue")
            if await btn.count() == 0:
                btn = self.page.get_by_role("button", name="Continue")
            await btn.first.click(timeout=10_000)
            await self.page.wait_for_load_state("networkidle", timeout=30_000)
        except Exception as e:
            await self.screenshot("step4_add_driver_submit_error")
            raise RuntimeError(
                f"Failed to submit Add Driver form: {e}"
            ) from e


class DriverSummaryPage(BasePage):
    """Sub-page 3 of Step 4: 'Driver Summary' page.

    Lists drivers added so far plus an "Add Driver" list item (NOT a
    button) and a "Looks Good" button.
    """

    async def add_another(self) -> None:
        """Click 'Add Driver' to start another driver entry."""
        print("    [GEICO] Step 4: adding another driver...")
        await self.page.wait_for_load_state("networkidle", timeout=30_000)
        await self.remove_overlays()

        # Live confirmed pattern: the "Add Driver" action lives in its own
        # listitem at the bottom of the drivers list. To avoid false matches
        # against driver-row text that may contain the phrase 'Add Driver'
        # (e.g. status messages), scope to listitems whose visible text is
        # EXACTLY 'Add Driver' (trimmed). Among multiple matches, the LAST
        # one is the add-control (it's appended at the bottom of the list).
        candidates = self.page.locator(
            '[role="listitem"]'
        ).filter(has_text="Add Driver")
        count = await candidates.count()
        target = None
        if count > 0:
            # Walk from last → first and pick the first listitem whose text
            # (collapsed) equals exactly "Add Driver".
            for i in range(count - 1, -1, -1):
                node = candidates.nth(i)
                try:
                    text = (await node.inner_text(timeout=2_000)).strip()
                except Exception:
                    text = ""
                if text == "Add Driver":
                    target = node
                    break
            if target is None:
                # No exact match; fall back to the last candidate (most likely
                # the add control, since GEICO appends it after driver rows).
                target = candidates.nth(count - 1)

        if target is None:
            await self.screenshot("step4_add_another_no_candidate")
            raise RuntimeError(
                "DriverSummaryPage.add_another: no 'Add Driver' listitem found"
            )

        try:
            await target.click(timeout=10_000)
            await self.page.wait_for_load_state("networkidle", timeout=30_000)
        except Exception as e:
            await self.screenshot("step4_add_another_driver_error")
            raise RuntimeError(
                f"Failed to click 'Add Driver' on summary: {e}"
            ) from e

    async def click_looks_good(self) -> None:
        """Click 'Looks Good' and wait for Step 5 ('Additional Business Info').
        """
        print(
            "    [GEICO] Step 4: clicking 'Looks Good' to advance to Step 5..."
        )
        await self.page.wait_for_load_state("networkidle", timeout=30_000)
        await self.remove_overlays()
        try:
            await self.click_button("Looks Good")
        except Exception as e:
            await self.screenshot("step4_looks_good_error")
            raise RuntimeError(
                f"Failed to click 'Looks Good' on driver summary: {e}"
            ) from e

        # Wait for the wizard's <title> to change to 'Additional Business Info'.
        # Use wait_for_function on document.title (consistent with other page
        # objects). Previous wait_for_text was strict-mode-prone when the
        # phrase also appears in a breadcrumb / sidebar / step indicator.
        try:
            await self.page.wait_for_function(
                "() => document.title.includes('Additional Business Info')",
                timeout=20_000,
            )
            print("    [GEICO] Step 4: reached Step 5 (Additional Business Info).")
        except Exception as e:
            await self.screenshot("step4_no_transition_to_step5")
            raise RuntimeError(
                f"Step 4 did not advance to 'Additional Business Info': {e}"
            ) from e
