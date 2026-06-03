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
        that opens a sub-form. Verified live 2026-06-03 (Prueba1) that the
        'Add' control is NOT a <button role="button" name="Add"> match:
        Progressive renders it as an <a> with role="button" or as a styled
        div. Multi-strategy locator + force=True for ExtJS reliability.
        """
        print("    [Progressive] Adding new driver...")
        await self.page.wait_for_load_state("networkidle", timeout=15_000)
        # Scroll to bottom so the 'Add another driver?' footer is in view.
        try:
            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await self.page.wait_for_timeout(400)
        except Exception:
            pass

        candidates = [
            # Most likely: link with 'Add' text near 'Add another driver?'
            self.page.get_by_role("link", name="Add", exact=True),
            self.page.get_by_role("button", name="Add", exact=True),
            # Sometimes the accessible name includes the full prompt
            self.page.get_by_role("button", name="Add another driver", exact=False),
            self.page.get_by_role("link", name="Add another driver", exact=False),
            # Final fallback: any visible element with exact text 'Add'
            self.page.get_by_text("Add", exact=True),
        ]
        for loc in candidates:
            n = await loc.count()
            for i in range(n):
                el = loc.nth(i)
                try:
                    if not await el.is_visible():
                        continue
                    await el.scroll_into_view_if_needed(timeout=2_000)
                    await el.click(timeout=5_000, force=True)
                    await self.page.wait_for_load_state("networkidle", timeout=30_000)
                    return
                except Exception:
                    continue

        await self.screenshot("driver_summary_no_add_button")
        raise RuntimeError(
            "DriverSummaryPage.add_driver: no clickable 'Add' control found"
        )

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
        name: Optional[str] = None,
        date_of_birth: Optional[str] = None,
    ) -> None:
        """Fill the AddDriver form and click Continue.

        Progressive AUTO-POPULATES First/Last/DOB for the policyholder from
        BusinessOwnerInfo, but ADDITIONAL drivers arrive with empty fields.
        We fill name + DOB only if the fields are currently empty (idempotent).
        """
        await self.page.wait_for_load_state("networkidle", timeout=30_000)

        if name:
            await self._fill_name_if_empty(name)
        if date_of_birth:
            await self._fill_dob_if_empty(date_of_birth)

        if license_state:
            await self._select_license_state(license_state)
        if license_number:
            await self._fill_license_number(license_number)

        await self._set_exclude_driver(exclude_from_policy)
        await self._set_has_driving_history(has_driving_history)

        print("    [Progressive] Saving driver...")
        await self.safe_click_continue(expect_url_changes_from="AddDriver")

    async def _locate_input_by_placeholder_or_label(
        self, *, placeholder_keywords: list, label_text: str
    ):
        """Multi-strategy locator for textboxes in the AddDriver form.

        Verified live 2026-06-03 (Prueba1): exact `get_by_placeholder("...")`
        with hardcoded curly/straight apostrophe didn't match the rendered
        placeholders, so no log was emitted and the fields stayed empty.
        Strategies (return first match):
          1. CSS attribute selector with case-insensitive substring match
             on placeholder (covers curly/straight apostrophes + variants)
          2. XPath traversal from the visible label text (works regardless
             of placeholder attribute presence)
        """
        # Strategy 1: case-insensitive partial placeholder
        for kw in placeholder_keywords:
            loc = self.page.locator(f'input[placeholder*="{kw}" i]').first
            if await self.field_exists(loc, wait_ms=600):
                return loc
        # Strategy 2: XPath from visible label
        label_loc = self.page.get_by_text(label_text, exact=False).first
        if await self.field_exists(label_loc, wait_ms=600):
            traversed = label_loc.locator("xpath=following::input[@type='text'][1]").first
            if await self.field_exists(traversed, wait_ms=600):
                return traversed
        return None

    async def _dump_addriver_inputs(self) -> None:
        """Emit the actual placeholders / aria-labels / labels of all visible
        textboxes on the AddDriver form. Called when fill_name/fill_dob can't
        find a target — reveals the real DOM shape in a single iteration.
        """
        try:
            info = await self.page.evaluate(
                """() => {
                    const out = [];
                    document.querySelectorAll('input[type="text"], input:not([type])').forEach(el => {
                        if (el.offsetParent === null) return;
                        out.push({
                            placeholder: el.getAttribute('placeholder') || '',
                            ariaLabel: el.getAttribute('aria-label') || '',
                            name: el.getAttribute('name') || '',
                            id: el.id || '',
                            value: (el.value || '').slice(0, 30),
                        });
                    });
                    return out;
                }"""
            )
            print(f"    [Progressive] AddDriver textbox DIAGNOSTIC (visible inputs):")
            for inp in info[:15]:
                print(f"    [Progressive]   {inp}")
        except Exception as e:
            print(f"    [Progressive] AddDriver diagnostic failed: {e}")

    async def _fill_name_if_empty(self, full_name: str) -> None:
        """Fill First / Last name textboxes if empty (additional drivers).

        Silent no-op for the POLICYHOLDER (whose Name + DOB are pre-filled
        by Progressive from BusinessOwnerInfo — these inputs don't render on
        the form). We detect that context by 'no First Name input visible'
        and just return; only emit WARN+diagnostic if it's an ADDITIONAL
        driver form (Name label is visible but inputs can't be located).
        """
        parts = full_name.strip().split()
        if not parts:
            return
        first = parts[0]
        last = " ".join(parts[1:]) if len(parts) > 1 else ""

        # First name
        first_input = await self._locate_input_by_placeholder_or_label(
            placeholder_keywords=["First Name", "First"],
            label_text="Name",
        )
        if first_input is None:
            # Policyholder context: name fields aren't rendered. Silent skip.
            return
        current = ""
        try:
            current = (await first_input.input_value()).strip()
        except Exception:
            pass
        if not current:
            print(f"    [Progressive] First Name = {first!r}")
            await self.safe_fill(first_input, first, verify=False)

        # Last name. The "Name" label is SHARED by First Name + MI + Last Name
        # (single label, 3 inputs). XPath from "Name" with [1] gives First
        # Name; Last Name is the 3rd input. Try placeholder strategy first,
        # then positional fallback.
        if last:
            last_input = None
            # Strategy 1: case-insensitive partial placeholder
            cand = self.page.locator('input[placeholder*="Last Name" i]').first
            if await self.field_exists(cand, wait_ms=600):
                last_input = cand
            # Strategy 2: ARIA label
            if last_input is None:
                cand = self.page.locator('input[aria-label*="Last" i]').first
                if await self.field_exists(cand, wait_ms=600):
                    last_input = cand
            # Strategy 3: positional — 3rd text input after the "Name" label
            #   layout: <label>Name</label> → [First Name] [MI] [Last Name]
            if last_input is None:
                name_label = self.page.get_by_text("Name", exact=True).first
                if await self.field_exists(name_label, wait_ms=600):
                    cand = name_label.locator(
                        "xpath=following::input[@type='text'][3]"
                    ).first
                    if await self.field_exists(cand, wait_ms=600):
                        last_input = cand

            if last_input is not None:
                current = ""
                try:
                    current = (await last_input.input_value()).strip()
                except Exception:
                    pass
                if not current:
                    print(f"    [Progressive] Last Name = {last!r}")
                    await self.safe_fill(last_input, last, verify=False)
            # If last_input is None: silent (policyholder context — pre-filled)

    async def _fill_dob_if_empty(self, dob: str) -> None:
        """Fill Date of Birth textbox if empty.

        Silent no-op for the policyholder (DOB pre-filled by Progressive
        and the input isn't rendered on the form).
        """
        dob_input = await self._locate_input_by_placeholder_or_label(
            placeholder_keywords=["MM/DD/YYYY", "MM/DD", "Birth"],
            label_text="Date of Birth",
        )
        if dob_input is None:
            return  # policyholder context — DOB pre-filled, no input on form
        current = ""
        try:
            current = (await dob_input.input_value()).strip()
        except Exception:
            pass
        if current and current != "MM/DD/YYYY":
            return  # already filled (likely policyholder auto-populated)
        print(f"    [Progressive] DOB = {dob}")
        await self.safe_fill(dob_input, dob, verify=False)

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

    async def try_continue_without_ssn(self) -> bool:
        """Try clicking the page's Continue button WITHOUT filling SSN.

        Verified live 2026-06-03 (Prueba1 NOBLE LOGISTICS): when SAFER can't
        match the USDOT and MVR/CLUE returns no credit history, Progressive
        shows a 'Please verify the following information' page with the
        SSN field marked 'Recommended for most accurate quote' — not
        required. Clicking Continue should proceed (Progressive prices with
        reduced underwriting accuracy).

        POLICY preserved: never AUTO-FILL the SSN. We just click Continue
        with the field empty.

        Returns True if the URL advances past NoHit / Order Results, False
        otherwise. Logs URL transitions + visible error text for debugging.
        """
        initial_token = await self.current_page_token()
        print(
            "    [Progressive] MVR/CLUE 'verify info' page; "
            "trying Continue without SSN"
        )

        try:
            await self.blur_active_element()
            await self.page.wait_for_timeout(300)
            btn = self.page.get_by_text("Continue", exact=True).last
            await btn.scroll_into_view_if_needed(timeout=2_000)
            await btn.click(timeout=10_000, force=True)
            await self.page.wait_for_load_state("networkidle", timeout=30_000)
            try:
                await self.wait_for_extjs_idle(timeout_ms=10_000)
            except Exception:
                pass
        except Exception as e:
            print(f"    [Progressive] WARN: MVR/CLUE Continue click failed: {e}")
            return False

        final_token = await self.current_page_token()
        final_url = self.page.url
        final_title = await self.page.title()
        advanced = (
            final_token != initial_token
            or ("NoHit" not in final_url and "Order Results" not in final_title)
        )
        if advanced:
            print("    [Progressive] MVR/CLUE page advanced without SSN")
            return True

        # Failure path only — emit diagnostic so the operator can see why
        print(
            "    [Progressive] MVR/CLUE page DID NOT advance — "
            "SSN may be required in this variant"
        )
        print(f"    [Progressive]   post-click URL  : {final_url}")
        print(f"    [Progressive]   post-click token: {final_token!r}")
        try:
            banners = await self.page.evaluate(
                """() => {
                    const errors = [];
                    document.querySelectorAll(
                        '.x-form-invalid-icon-default, [class*="error"], [class*="invalid"], '
                        + '[role="alert"], .x-mb-error, .x-mb-warning, .error-message-placeholder'
                    ).forEach(el => {
                        if (el.offsetParent === null) return;
                        const t = (el.innerText || el.textContent || '').trim();
                        if (t && t.length < 200) errors.push(t);
                    });
                    return [...new Set(errors)].slice(0, 10);
                }"""
            )
            if banners:
                print(f"    [Progressive]   visible error/warning banners: {banners}")
        except Exception:
            pass
        return False

    async def back(self) -> None:
        """Click Back to return to DriverSummary (non-wizard navigation button)."""
        # Not a wizard Continue; direct click with force=True for ExtJS reliability.
        btn = self.page.get_by_role("button", name="Back")
        await btn.click(timeout=10_000, force=True)
        await self.page.wait_for_load_state("networkidle", timeout=15_000)
