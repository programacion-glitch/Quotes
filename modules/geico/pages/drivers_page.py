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

import re

from modules.geico.field_mapper import MappedDriver
from modules.geico.pages.base_page import BasePage, _flex_text_regex


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

        # EXCLUDED-owner variant (live 4JR 2026-06-12): GEICO creates NO
        # owner placeholder — Step 4 opens straight into an Add Driver
        # accordion (its telltale 'relationship to the business' question,
        # which the owner placeholder NEVER shows, plus Save And Continue
        # instead of Next). Skip the placeholder entirely; the driver loop
        # detects the open form and fills it for the first real driver.
        rel_q = self.page.locator("gds-radio-button-group").filter(
            has_text=_flex_text_regex("relationship to the business")
        ).filter(visible=True)
        if await self.field_exists(rel_q, wait_ms=2_000):
            print(
                "    [GEICO] Step 4: no owner placeholder — Add Driver form "
                "is already open (excluded owner) — skipping placeholder"
            )
            return

        await self._select_license_state(owner_driver)
        # An ACTIVE owner-driver's placeholder is a fully-rated driver entry:
        # it needs the DOB or its Next stays DISABLED (live SOLANO 2026-06-11
        # — Next greyed out with everything else filled). An EXCLUDED owner's
        # placeholder doesn't ask for it.
        if not owner_driver.is_excluded:
            await self._fill_owner_dob(owner_driver)
        await self._answer_certificate_of_responsibility()
        await self._answer_has_cdl(owner_driver)
        await self._click_next()

    async def _fill_owner_dob(self, owner_driver: MappedDriver) -> None:
        """Fill the owner-driver's DOB on the placeholder if the field is
        present and empty (active owner-driver only)."""
        if not owner_driver.date_of_birth:
            return
        try:
            box = self.page.get_by_label("Date of Birth")
            if await box.count() == 0:
                box = self.page.locator('[id*="DateOfBirth" i]')
            if await self.field_exists(box, wait_ms=2_000):
                current = ""
                try:
                    current = (await box.first.input_value()) or ""
                except Exception:
                    current = ""
                if not current.strip():
                    print(f"    [GEICO] Step 4: owner DOB -> "
                          f"{owner_driver.date_of_birth}")
                    await box.first.fill(owner_driver.date_of_birth)
                    await self.page.keyboard.press("Tab")
                    await self.page.wait_for_timeout(300)
        except Exception as e:
            self.note_warning(f"owner placeholder DOB fill failed: {e}")

    async def _answer_certificate_of_responsibility(self) -> None:
        """Conditional (live SOLANO 2026-06-11): 'Do they need a Certificate
        of Responsibility...?' (SR-22-style filing). BlueQuotes don't carry
        it; default No."""
        from modules.geico.pages.base_page import _flex_text_regex
        try:
            grp = self.page.locator("gds-radio-button-group").filter(
                has_text=_flex_text_regex("Certificate of Responsib")
            )
            if await self.field_exists(grp, wait_ms=1_500):
                print("    [GEICO] Step 4: Certificate of Responsibility -> No")
                await self.click_question_radio(
                    "Certificate of Responsib", "No"
                )
        except Exception as e:
            self.note_warning(f"certificate-of-responsibility radio failed: {e}")

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
            self.note_warning(
                "owner-placeholder license-state select not "
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
            self.note_warning(
                f"owner placeholder license state "
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
            self.note_warning(f"owner placeholder CDL radio failed: {e}")
            await self.screenshot("step4_placeholder_cdl_error")

    async def _click_next(self) -> None:
        """Click the placeholder Next and VERIFY it advanced.

        click_button waits for Next to be ENABLED (GEICO greys it while it
        processes CDL=Yes + the driving-history reveal — live SOLANO
        2026-06-11). After the click, confirm we left the placeholder (its
        CDL question is gone); retry once if a stale render kept us."""
        print("    [GEICO] Step 4: submitting owner placeholder...")
        cdl_q = self.page.locator("gds-radio-button-group").filter(
            has_text=_flex_text_regex("does this driver have a CDL")
        ).filter(visible=True)

        # Excluded-owner variant, late-mounting (live 4JR 2026-06-12): the
        # 'placeholder' is really the FIRST driver's Add Driver accordion —
        # it grows the relationship/name fields on a round-trip and its
        # buttons are Save And Continue / Discard Changes; a 'Next' NEVER
        # exists. Detect by buttons (robust to the mount timing) and bail:
        # the driver loop fills this open form for the first real driver.
        next_btn = self.page.locator("gds-button, button").filter(
            has_text=re.compile(r"^\s*Next\s*$")
        ).filter(visible=True)
        save_btn = self.page.locator("gds-button, button").filter(
            has_text=re.compile(r"^\s*Save\s+and\s+Continue\s*$", re.IGNORECASE)
        ).filter(visible=True)
        if (await next_btn.count()) == 0 and await self.field_exists(
            save_btn, wait_ms=3_000
        ):
            print(
                "    [GEICO] Step 4: no placeholder Next — this is the Add "
                "Driver accordion (excluded owner). Leaving it to the "
                "driver loop."
            )
            return
        for attempt in (1, 2):
            # Already advanced? The placeholder AUTO-ADVANCES on a server
            # round-trip (live YKZ 2026-06-12) — don't fight a missing Next.
            if await self._placeholder_advanced(cdl_q, wait_ms=1_000):
                return
            await self.remove_overlays()
            try:
                await self.click_button("Next")
                await self.page.wait_for_load_state("networkidle", timeout=30_000)
            except Exception as e:
                # The click can fail precisely BECAUSE we already advanced
                # (the Next vanished). Treat that as success.
                if await self._placeholder_advanced(cdl_q, wait_ms=2_000):
                    return
                await self.screenshot("step4_placeholder_next_error")
                raise RuntimeError(
                    f"Failed to click Next on owner placeholder: {e}"
                ) from e
            if await self._placeholder_advanced(cdl_q, wait_ms=4_000):
                return
            if attempt == 1:
                self.note_warning(
                    "owner placeholder Next did not advance — retrying "
                    "(waiting for it to enable)"
                )
                await self.page.wait_for_timeout(1_000)
        # Still on the placeholder — surface the real DOM for the next fix.
        debug = await self.dump_debug_context("placeholder_stuck")
        await self.screenshot("step4_placeholder_stuck")
        raise RuntimeError(
            f"Owner placeholder did not advance after Next (still showing the "
            f"CDL question). Visible buttons: {debug.get('visible_buttons')}"
        )

    async def _placeholder_advanced(self, cdl_q, *, wait_ms: int) -> bool:
        """Did the wizard leave the owner placeholder?

        'CDL question gone' alone is AMBIGUOUS: the Add Driver accordion that
        follows an excluded-owner placeholder has its OWN CDL question, so
        the old check read a successful advance as 'stuck' and then died
        hunting a Next that no longer exists (live 4JR/ABIGAIL 2026-06-12).
        Advanced == the relationship question (Add Driver form) is visible,
        OR the summary's Add Driver li is on screen, OR the CDL question is
        gone."""
        rel_q = self.page.locator("gds-radio-button-group").filter(
            has_text=_flex_text_regex("relationship to the business")
        ).filter(visible=True)
        try:
            if (await rel_q.count()) > 0 and await rel_q.first.is_visible():
                return True
        except Exception:
            pass
        try:
            add_li = self.page.locator("li.add-state", has_text="Add Driver")
            if (await add_li.count()) > 0 and await add_li.first.is_visible():
                return True
        except Exception:
            pass
        return not await self.field_exists(cdl_q, wait_ms=wait_ms)


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
        await self._answer_certificate_of_responsibility()
        await self._answer_has_cdl(driver)
        await self._handle_incidents(driver)
        await self._click_save_and_continue()

    async def _answer_certificate_of_responsibility(self) -> None:
        """Same SR-22-style conditional as the owner placeholder; default No."""
        from modules.geico.pages.base_page import _flex_text_regex
        try:
            grp = self.page.locator("gds-radio-button-group").filter(
                has_text=_flex_text_regex("Certificate of Responsib")
            )
            if await self.field_exists(grp, wait_ms=1_500):
                print("    [GEICO] Step 4: Certificate of Responsibility -> No")
                await self.click_question_radio(
                    "Certificate of Responsib", "No"
                )
        except Exception as e:
            self.note_warning(f"certificate-of-responsibility radio failed: {e}")

    async def _fill_first_name(self, driver: MappedDriver) -> None:
        if not driver.first_name:
            self.note_warning("driver missing first_name, skipping field")
            return
        try:
            print(f"    [GEICO] Step 4: First Name -> {driver.first_name}")
            box = self.page.get_by_role("textbox", name="First Name")
            await box.first.wait_for(state="visible", timeout=10_000)
            await box.first.fill(driver.first_name, timeout=5_000)
        except Exception as e:
            self.note_warning(f"First Name fill failed: {e}")
            await self.screenshot("step4_add_driver_first_name_error")

    async def _fill_last_name(self, driver: MappedDriver) -> None:
        if not driver.last_name:
            self.note_warning("driver missing last_name, skipping field")
            return
        try:
            print(f"    [GEICO] Step 4: Last Name -> {driver.last_name}")
            box = self.page.get_by_role("textbox", name="Last Name")
            await box.first.wait_for(state="visible", timeout=10_000)
            await box.first.fill(driver.last_name, timeout=5_000)
        except Exception as e:
            self.note_warning(f"Last Name fill failed: {e}")
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
            self.note_warning(f"Suffix select failed: {e}")
            await self.screenshot("step4_add_driver_suffix_error")

    async def _fill_date_of_birth(self, driver: MappedDriver) -> None:
        if not driver.date_of_birth:
            self.note_warning("driver missing date_of_birth")
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
            self.note_warning(f"DOB fill failed: {e}")
            await self.screenshot("step4_add_driver_dob_error")

    async def _select_license_state(self, driver: MappedDriver) -> None:
        state = driver.license_state or "Texas"
        try:
            print(f"    [GEICO] Step 4: License State -> {state}")
            await self.select_by_options_signature(
                _LICENSE_STATE_OPTIONS_SIGNATURE, state
            )
        except Exception as e:
            self.note_warning(f"License State select failed: {e}")
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
            self.note_warning(f"Relationship radio click failed: {e}")
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
            self.note_warning(f"CDL radio failed: {e}")
            await self.screenshot("step4_add_driver_cdl_error")

    async def _handle_incidents(self, driver: MappedDriver) -> None:
        """Block 3 scope: skip incidents.

        If the BlueQuote indicates accidents/violations, log a warning so
        the operator knows the driving history was not entered. The MVR
        check on Step 8 will surface real violations regardless.
        """
        if driver.has_incidents:
            self.note_warning(
                f"driver "
                f"{driver.first_name} {driver.last_name} has_incidents=True "
                f"but incident entry is OUT OF SCOPE for Block 3 — leaving "
                f"driving history blank (MVR on Step 8 will catch violations)"
            )

    async def _click_save_and_continue(self) -> None:
        """Click 'Save and Continue' to advance to the Driver Summary page.

        The accordion renders a Save and Continue / Discard Changes PAIR and
        the page can hold TWO copies (MCP-mapped live 2026-06-12) — the
        first is the inert top fragment, the LAST visible one is the real
        CTA (same lesson as the duplicated Next buttons). Clicking .first
        timed out 10s on every multi-driver profile."""
        print("    [GEICO] Step 4: submitting Add Driver form...")
        await self.remove_overlays()
        try:
            btn = self.page.get_by_role(
                "button", name="Save and Continue"
            ).filter(visible=True)
            if await btn.count() == 0:
                # Some builds label it differently.
                btn = self.page.get_by_role(
                    "button", name="Save & Continue"
                ).filter(visible=True)
            if await btn.count() == 0:
                btn = self.page.get_by_role(
                    "button", name="Continue"
                ).filter(visible=True)
            await btn.last.click(timeout=10_000)
            await self.page.wait_for_load_state("networkidle", timeout=30_000)
        except Exception as e:
            await self.screenshot("step4_add_driver_submit_error")
            raise RuntimeError(
                f"Failed to submit Add Driver form: {e}"
            ) from e

        # Confirm the accordion actually CLOSED (save committed): its First
        # Name box must leave the screen. During the close animation the old
        # form stays visible, so the driver-loop's open-form detector read it
        # as 'form still open' and skipped Add Driver for the NEXT driver —
        # whose fills then landed on the closing form (live DDH 2026-06-12:
        # ERIK overwrote OMAR's just-saved accordion and was lost).
        first_name = self.page.get_by_role("textbox", name="First Name")
        for _ in range(20):  # ~10s cap, no blind sleep
            try:
                if (await first_name.count() == 0
                        or not await first_name.first.is_visible()):
                    return
            except Exception:
                return
            await self.page.wait_for_timeout(500)
        self.note_warning(
            "Add Driver form still visible 10s after Save and Continue — "
            "the save may not have committed"
        )


class DriverSummaryPage(BasePage):
    """Sub-page 3 of Step 4: 'Driver Summary' page.

    Lists drivers added so far plus an "Add Driver" list item (NOT a
    button) and a "Looks Good" button.
    """

    async def add_another(self) -> None:
        """Open the Add Driver entry form from the summary.

        Same inline ACCORDION as Add Vehicle (MCP-mapped live 2026-06-12):
        the reliable opener is the '+' icon `span[data-testid="addIcon"]`
        inside the <li class="add-state"> — a click on the li itself is
        swallowed on current builds. Unlike Add Vehicle there is NO chooser:
        the driver form expands directly."""
        print("    [GEICO] Step 4: adding another driver...")
        await self.page.wait_for_load_state("networkidle", timeout=30_000)
        await self.remove_overlays()

        # Preferred: the accordion's + icon (the ONLY interactive element).
        icon = self.page.locator(
            'li.add-state [data-testid="addIcon"], '
            'li.add-state .expandable-form-add-icon'
        )
        if await self.field_exists(icon, wait_ms=5_000):
            try:
                await icon.first.click(timeout=10_000)
                await self.page.wait_for_load_state(
                    "networkidle", timeout=30_000
                )
                return
            except Exception as e:
                self.note_warning(f"Add Driver + icon click failed: {e}")

        # Live SOLANO 2026-06-11: the add control is a plain
        # <li class="add-state"> WITHOUT role=listitem — try it next.
        direct = self.page.locator("li.add-state", has_text="Add Driver")
        if await direct.count() > 0:
            try:
                await direct.first.click(timeout=10_000)
                await self.page.wait_for_load_state(
                    "networkidle", timeout=30_000
                )
                return
            except Exception:
                pass

        # Fallback (older builds): listitem whose visible text is EXACTLY
        # 'Add Driver' (trimmed); among multiple matches the LAST one is the
        # add-control (appended at the bottom of the list).
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
            # Dynamic outcome wait: success title instant; validation or
            # server-error fail fast; 60s only as worst-case cap.
            await self.wait_for_step_outcome(
                ["Additional Business Info"], budget_ms=60_000
            )
            print("    [GEICO] Step 4: reached Step 5 (Additional Business Info).")
        except (RuntimeError, TimeoutError) as e:
            await self.screenshot("step4_no_transition_to_step5")
            raise RuntimeError(
                f"Step 4 did not advance to 'Additional Business Info': {e}"
            ) from e
