"""
Business & Owner Info Page Object for GEICO wizard (Step 2).

Title: `GEICO Business & Owner Info`. This is the page that loads after the
dashboard hands off the new wizard tab. GEICO auto-pops many fields from the
FMCSA registry (address, ZIP/City combobox, email, owner phone, business
phone). Our job is to OVERWRITE only the fields where the BlueQuote source
prevails (per Rule 3 in docs/Proceso GEICO.md: BlueQuote phone wins over
GEICO's auto-pop).

Field coverage (live-mapped):
  - Coverage Start Date (optional override; defaults to GEICO's tomorrow)
  - Business Owner First/Last Name
  - Date of Birth
  - Marital Status (ALWAYS "Single" per policy Rule 1)
  - Owner phone (BlueQuote prevails)
  - Customer email
  - Business Street Address (Google Places autocomplete — fill + escape)
  - Unit Number (left blank)
  - 5-Digit ZIP Code (overwrite if differs)
  - City combobox (auto-pop trusted unless explicit override)
  - Business ownership type combobox
  - Customer business name
  - Business phone (same number as owner phone)
  - Radio "Is the owner a driver on the policy?" (Yes is default)
  - Next button -> waits for Step 3 'Vehicles' title

Selectors avoid dynamic ids — using role+name and partial id patterns. Native
`<select>` elements use the `select_by_options_signature` helper because the
id changes on every page load. Failures are caught per logical group so one
missing field doesn't abort the entire form.
"""

import re
import time

from playwright.async_api import Page

from modules.geico.pages.base_page import BasePage, _flex_text_regex
from modules.geico.field_mapper import MappedFields


class OwnerVerificationError(RuntimeError):
    """GEICO could not verify the business owner's identity at Step 2 submit
    and is requesting the owner's SSN.

    Raised instead of marching forward into a phantom Step 3. The flow never
    auto-fills the SSN (sensitive data); per policy this is retried (the check
    is intermittent — the same owner often verifies on a later attempt) and,
    once retries are exhausted, promoted to a HALT for manual intervention.
    """


class BusinessOwnerPage(BasePage):
    """GEICO wizard Step 2 — Business & Owner Info."""

    async def fill_and_submit(self, fields: MappedFields) -> None:
        """
        Fill the Business & Owner Info form. Many fields are auto-populated by
        GEICO from FMCSA — we OVERWRITE only those where the BlueQuote source
        differs (per Rule 3 in docs/Proceso GEICO.md: phone source = BlueQuote
        prevails).

        Pre-state: 'Business & Owner Info' title.
        Post-state: 'Vehicles' title (Step 3) loaded.
        """
        await self.page.wait_for_load_state("networkidle", timeout=30_000)
        await self.remove_overlays()
        print("    [GEICO] Step 2: Business & Owner Info")

        await self._set_coverage_start_date(fields.effective_date)
        await self._fill_owner_personal(fields)
        await self._fill_owner_contact(fields)
        await self._fill_business_address(fields)
        await self._fill_business_info(fields)
        await self._answer_owner_is_driver(fields.owner_is_driver)
        await self._click_next()

    # ------------------------------------------------------------------
    # Coverage Start Date
    # ------------------------------------------------------------------

    async def _set_coverage_start_date(self, effective_date) -> None:
        """Set Coverage Start Date (mm/dd/yyyy). If None, accept GEICO's
        default (tomorrow) — do nothing."""
        if not effective_date:
            print("    [GEICO] Step 2: Coverage Start Date -> default (tomorrow)")
            return
        print(f"    [GEICO] Step 2: Coverage Start Date -> {effective_date}")
        try:
            box = self.page.get_by_label("Coverage Start Date")
            if await box.count() == 0:
                box = self.page.locator('input[id*="StartDate" i]').first
            await box.wait_for(state="visible", timeout=10_000)
            await box.fill(effective_date, timeout=5_000)
            await self.page.keyboard.press("Tab")
            await self.page.wait_for_timeout(300)
        except Exception as e:
            print(f"    [GEICO] WARN: failed to set Coverage Start Date: {e}")
            await self.screenshot("step2_coverage_start_date_error")

    # ------------------------------------------------------------------
    # Owner: name, DOB, marital status
    # ------------------------------------------------------------------

    async def _fill_owner_personal(self, fields: MappedFields) -> None:
        """First name, Last name, DOB, Marital Status (always Single)."""
        try:
            if fields.owner_first_name is not None:
                print(f"    [GEICO] Step 2: First Name -> {fields.owner_first_name}")
                box = self.page.get_by_role(
                    "textbox", name="Business Owner First Name"
                )
                await box.wait_for(state="visible", timeout=10_000)
                await box.fill(fields.owner_first_name, timeout=5_000)

            if fields.owner_last_name is not None:
                print(f"    [GEICO] Step 2: Last Name -> {fields.owner_last_name}")
                box = self.page.get_by_role(
                    "textbox", name="Business Owner Last Name"
                )
                await box.wait_for(state="visible", timeout=10_000)
                await box.fill(fields.owner_last_name, timeout=5_000)

            if fields.owner_dob is not None:
                print(f"    [GEICO] Step 2: DOB -> {fields.owner_dob}")
                dob_box = self.page.get_by_label("Date of Birth")
                if await dob_box.count() == 0:
                    dob_box = self.page.locator('[id*="DateOfBirth" i]').first
                await dob_box.wait_for(state="visible", timeout=10_000)
                await dob_box.fill(fields.owner_dob, timeout=5_000)
                await self.page.keyboard.press("Tab")
                await self.page.wait_for_timeout(300)

            # Marital Status — ALWAYS Single (Rule 1)
            marital = fields.marital_status or "Single"
            print(f"    [GEICO] Step 2: Marital Status -> {marital}")
            try:
                await self.select_by_options_signature(
                    ["Single", "Widowed"], marital
                )
            except Exception as e:
                print(f"    [GEICO] WARN: marital status select failed: {e}")
        except Exception as e:
            print(f"    [GEICO] WARN: owner personal block failed: {e}")
            await self.screenshot("step2_owner_personal_error")

    # ------------------------------------------------------------------
    # Owner contact (phone + email) — BlueQuote prevails over auto-pop
    # ------------------------------------------------------------------

    async def _fill_owner_contact(self, fields: MappedFields) -> None:
        """Owner phone and customer email. Skip if None (keep GEICO auto-pop)."""
        try:
            if fields.owner_phone is not None:
                print(f"    [GEICO] Step 2: Owner phone -> {fields.owner_phone}")
                box = self.page.get_by_role(
                    "textbox", name=re.compile(r"owner'?s phone", re.I)
                )
                if await box.count() == 0:
                    box = self.page.get_by_role(
                        "textbox", name=re.compile(r"confirm the owner", re.I)
                    )
                if await box.count() > 0:
                    await box.first.fill(fields.owner_phone, timeout=5_000)
                else:
                    print("    [GEICO] WARN: owner phone textbox not found")

            if fields.owner_email is not None:
                print(f"    [GEICO] Step 2: Email -> {fields.owner_email}")
                box = self.page.get_by_role(
                    "textbox", name=re.compile(r"customer'?s email", re.I)
                )
                if await box.count() == 0:
                    box = self.page.get_by_role(
                        "textbox", name=re.compile(r"email", re.I)
                    )
                if await box.count() > 0:
                    await box.first.fill(fields.owner_email, timeout=5_000)
                else:
                    print("    [GEICO] WARN: email textbox not found")
        except Exception as e:
            print(f"    [GEICO] WARN: owner contact block failed: {e}")
            await self.screenshot("step2_owner_contact_error")

    # ------------------------------------------------------------------
    # Business address (street, unit, ZIP, city)
    # ------------------------------------------------------------------

    async def _fill_business_address(self, fields: MappedFields) -> None:
        """
        Business Street Address (Google Places autocomplete + fallback).
        Unit Number is left blank. ZIP is overwritten only if our value
        differs from the auto-pop. City combobox is auto-pop unless we have
        a matching option.
        """
        try:
            if fields.owner_street is not None:
                # Google Places autocomplete: typing alone leaves the field
                # invalid ("Street Address is required") — Places requires
                # SELECTING a suggestion to commit a structured address.
                # Type street (+ city to disambiguate), wait for the dropdown,
                # then select the first suggestion (.pac-item / role=option /
                # ArrowDown+Enter fallback).
                query = fields.owner_street
                if fields.owner_city:
                    query = f"{fields.owner_street} {fields.owner_city}"
                print(f"    [GEICO] Step 2: Street Address (Places) -> {query}")
                box = self.page.get_by_role("searchbox", name="Enter a location")
                if await box.count() == 0:
                    box = self.page.get_by_role(
                        "textbox", name=re.compile(r"(street|location)", re.I)
                    ).first
                if await box.count() > 0:
                    await box.first.click(timeout=5_000)
                    await box.first.fill("", timeout=3_000)
                    await box.first.type(query, delay=60)
                    await self.page.wait_for_timeout(1_800)  # wait for suggestions

                    selected = False
                    for sel in (
                        ".pac-item",                  # raw Google Places
                        '[role="listbox"] [role="option"]',
                        '[role="option"]',
                        "gds-typeahead li",
                    ):
                        sug = self.page.locator(sel)
                        try:
                            if await sug.count() > 0:
                                await sug.first.click(timeout=3_000)
                                selected = True
                                break
                        except Exception:
                            continue
                    if not selected:
                        # Universal keyboard fallback: highlight first + commit.
                        try:
                            await box.first.press("ArrowDown")
                            await box.first.press("Enter")
                            selected = True
                        except Exception:
                            pass
                    if not selected:
                        print("    [GEICO] WARN: no Places suggestion selected; "
                              "address may remain invalid")
                    await self.page.wait_for_timeout(600)

            # Unit Number — explicitly left blank (not in BlueQuote).

            if fields.zip_code is not None:
                try:
                    zip_box = self.page.get_by_role(
                        "textbox", name="5-Digit ZIP Code"
                    )
                    if await zip_box.count() > 0:
                        current = ""
                        try:
                            current = await zip_box.first.input_value()
                        except Exception:
                            current = ""
                        if current.strip() != fields.zip_code.strip():
                            print(
                                f"    [GEICO] Step 2: ZIP overwrite "
                                f"({current!r} -> {fields.zip_code})"
                            )
                            await zip_box.first.fill(
                                fields.zip_code, timeout=5_000
                            )
                            await self.page.keyboard.press("Tab")
                            await self.page.wait_for_timeout(1_000)
                        else:
                            print(
                                "    [GEICO] Step 2: ZIP already matches "
                                "auto-pop, skipping"
                            )
                except Exception as e:
                    print(f"    [GEICO] WARN: ZIP overwrite failed: {e}")

            if fields.owner_city:
                print(f"    [GEICO] Step 2: City -> {fields.owner_city}")
                try:
                    # City combobox is native <select>; option set varies but
                    # always includes the resolved city + "OTHER".
                    await self.select_by_options_signature(
                        ["OTHER"], fields.owner_city
                    )
                except Exception as e:
                    # Fall back to trusting auto-pop.
                    print(
                        f"    [GEICO] WARN: city select failed "
                        f"(trusting auto-pop): {e}"
                    )
        except Exception as e:
            print(f"    [GEICO] WARN: business address block failed: {e}")
            await self.screenshot("step2_business_address_error")

    # ------------------------------------------------------------------
    # Business info (ownership type, name, business phone)
    # ------------------------------------------------------------------

    async def _fill_business_info(self, fields: MappedFields) -> None:
        """Business ownership type, business name, business phone."""
        try:
            if fields.business_ownership_type:
                print(
                    f"    [GEICO] Step 2: Ownership type -> "
                    f"{fields.business_ownership_type}"
                )
                try:
                    await self.select_by_options_signature(
                        ["Limited Liability Company", "Trust"],
                        fields.business_ownership_type,
                    )
                except Exception as e:
                    print(f"    [GEICO] WARN: ownership-type select failed: {e}")

            if fields.business_name is not None:
                print(
                    f"    [GEICO] Step 2: Business Name -> {fields.business_name}"
                )
                box = self.page.get_by_role(
                    "textbox", name="What is the customer's business name?"
                )
                if await box.count() == 0:
                    box = self.page.get_by_role(
                        "textbox", name=re.compile(r"business name", re.I)
                    )
                if await box.count() > 0:
                    await box.first.fill(fields.business_name, timeout=5_000)
                else:
                    print("    [GEICO] WARN: business name textbox not found")

            if fields.owner_phone is not None:
                print(
                    f"    [GEICO] Step 2: Business phone -> {fields.owner_phone}"
                )
                box = self.page.get_by_role(
                    "textbox", name="Please confirm the business phone number"
                )
                if await box.count() == 0:
                    box = self.page.get_by_role(
                        "textbox", name=re.compile(r"business phone", re.I)
                    )
                if await box.count() > 0:
                    await box.first.fill(fields.owner_phone, timeout=5_000)
                else:
                    print("    [GEICO] WARN: business phone textbox not found")
        except Exception as e:
            print(f"    [GEICO] WARN: business info block failed: {e}")
            await self.screenshot("step2_business_info_error")

    # ------------------------------------------------------------------
    # Radio "Is the owner a driver on the policy?"
    # ------------------------------------------------------------------

    async def _answer_owner_is_driver(self, is_driver: bool) -> None:
        """Yes is default-checked by GEICO. Click No only when needed."""
        if is_driver:
            print("    [GEICO] Step 2: Owner is driver -> Yes (default)")
            return
        print("    [GEICO] Step 2: Owner is driver -> No")
        try:
            await self.click_question_radio(
                "owner a driver on the policy", "No"
            )
        except Exception as e:
            print(f"    [GEICO] WARN: owner-is-driver radio failed: {e}")
            await self.screenshot("step2_owner_is_driver_error")

    # ------------------------------------------------------------------
    # Submit
    # ------------------------------------------------------------------

    async def _click_next(self) -> None:
        """Click Next at the bottom of the form and wait for Step 3."""
        print("    [GEICO] Step 2: Clicking Next...")
        await self.remove_overlays()
        try:
            btn = self.page.get_by_role("button", name="Next")
            await btn.first.click(timeout=10_000)
        except Exception as e:
            await self.screenshot("step2_next_click_error")
            raise RuntimeError(f"Failed to click Next on Step 2: {e}") from e

        await self._await_step3_or_verification()

    async def _await_step3_or_verification(self, timeout_s: float = 30.0) -> None:
        """Resolve the outcome of the Step 2 submit.

        GEICO runs a server-side owner identity check on submit, so the title
        flipping to 'Vehicles' is NOT a reliable success signal (the wizard
        can bounce back to Step 2). Poll for whichever real outcome appears:

          * SUCCESS  -> the Vehicles form mounts (its first question, the VIN
                        'Do you have it handy?' radio group, becomes visible).
          * VERIFY   -> bounced back to Step 2 with an 'unable to verify'
                        banner + an SSN field. Raise OwnerVerificationError
                        (never auto-fill SSN). Retriable -> HALT.
          * HARD ERR -> GEICO's 'There was a problem...' page. Retriable.
        """
        vehicles_marker = self.page.locator("gds-radio-button-group").filter(
            has_text=_flex_text_regex("Do you have it handy")
        )
        verify_banner = self.page.get_by_text("unable to verify", exact=False)
        ssn_field = self.page.get_by_text("Social Security Number", exact=False)
        hard_error = self.page.get_by_text(
            "There was a problem while processing", exact=False
        )

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            # Success: the Vehicles form's first question is on screen.
            try:
                if (
                    await vehicles_marker.count() > 0
                    and await vehicles_marker.first.is_visible()
                ):
                    print("    [GEICO] Step 2 -> Step 3 (Vehicles) loaded")
                    return
            except Exception:
                pass

            # Soft verification failure: SSN requested. Never auto-fill it.
            try:
                if (
                    await verify_banner.count() > 0
                    or await ssn_field.count() > 0
                ):
                    await self.screenshot("step2_owner_verification_failed")
                    raise OwnerVerificationError(
                        "GEICO could not verify the owner's identity and is "
                        "requesting the Business Owner SSN. SSN is sensitive "
                        "and is not auto-filled — manual intervention needed."
                    )
            except OwnerVerificationError:
                raise
            except Exception:
                pass

            # Hard server error page (retriable transient).
            try:
                if await hard_error.count() > 0:
                    await self.screenshot("step2_hard_error")
                    raise RuntimeError(
                        "GEICO returned a server error ('There was a problem "
                        "while processing the information you submitted') after "
                        "the Step 2 submit (transient — will retry)."
                    )
            except RuntimeError:
                raise
            except Exception:
                pass

            await self.page.wait_for_timeout(500)

        await self.screenshot("step2_to_step3_navigation_error")
        raise RuntimeError(
            "Step 2 submit did not reach a known outcome (Vehicles form, "
            f"verification prompt, or error page) within {timeout_s:.0f}s."
        )
