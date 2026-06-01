"""
Business Info Page Object for Progressive wizard.

First page of the quote wizard after "Add Products to Quote".
URL: clpolicy.foragentsonly.com/Express/Default.aspx?pageName=BusinessOwnerInfo

All selectors VALIDATED LIVE on 2026-04-09 using USDOT 2998569 (M&D CUSTOM FREIGHT LLC).
"""

from typing import Optional

from modules.progressive.pages.base_page import BasePage
from modules.progressive.field_mapper import MappedFields


# Quick-access business type buttons that appear on the page
QUICK_TYPE_BUTTONS = [
    "Contractor",
    "Dirt, Sand and Gravel",
    "Landscaper",
    "Towing",
    "Trucker",
]

# Sub-type options that appear when "Trucker" is selected
# (Values confirmed from the combobox "Type of Trucker")
TRUCKER_SUBTYPES = [
    "Agricultural",
    "Auto Hauler",
    "Coal",
    "Containers",
    "Debris Removal",
    "Dirt, Sand and Gravel",
    "Escort Vehicles",
    "Expediters",
    "Fracking, Sand or Water",
    "Freight Forwarder",
    "Garbage & Trash",
    "General Freight / Other",
    "Hazardous Materials / Placards",
    "Hotshot Transport",
    "Household Goods Mover",
    "Livestock",
    "Logging / Wood Chips",
    "Machinery & Heavy Equipment",
    "Mobile Home Toter",
    "Oilfield Materials",
    "Refrigerated Goods",
]


class BusinessInfoPage(BasePage):
    """Progressive wizard - BusinessOwnerInfo page.

    Flow:
      1. Currently insured with Progressive? -> No
      2. USDOT Yes/No/NotYet -> Yes
      3. Fill USDOT Number
      4. Click "Verify" (required before submit)
      5. "Does this USDOT belong to customer?" -> Yes
      6. Entity type (Individual / Partnership / Corporation or LLC)
      7. Business Name (and DBA if Individual)
      8. Business Type (quick button or combobox) -> may open sub-type dropdown
      9. Hazmat placard Yes/No (appears for Trucker)
     10. Owner First/Last/Address/ZIP/City/DOB
     11. Click "Ok, start quote."
    """

    async def fill_and_submit(self, fields: MappedFields) -> None:
        """Fill the entire BusinessOwnerInfo page and submit.

        If `fields.effective_date` is supplied, sets the policy start date.
        """
        await self.page.wait_for_load_state("networkidle", timeout=30_000)
        await self.remove_overlays()

        if fields.effective_date:
            await self._set_effective_date(fields.effective_date)

        await self._answer_currently_insured(False)
        await self._answer_has_usdot(bool(fields.usdot))

        if fields.usdot:
            await self._fill_usdot_number(fields.usdot)
            await self._click_verify_usdot()
            await self._confirm_usdot_belongs_to_customer(True)

        await self._select_entity_type(fields.entity_type)
        await self._fill_business_name(fields.business_name, fields.dba_name)
        await self._select_business_type(fields.commodity)
        await self._answer_hazmat_placard(False)  # default No
        await self._fill_owner_info(
            fields.owner_name,
            street=fields.owner_street,
            zip_code=fields.owner_zip,
            city=fields.owner_city,
            dob=fields.owner_dob,
        )
        # Conditional required question for trucking/dirt-sand-gravel classes.
        await self._answer_oil_gas_fields(False)
        await self._click_start_quote()

    async def _set_effective_date(self, date_str: str) -> None:
        """Set the policy effective date (mm/dd/yyyy)."""
        print(f"    [Progressive] Effective date: {date_str}")
        combo = self.page.get_by_role(
            "combobox",
            name="When should this Progressive Commercial Auto policy start?",
        )
        if await combo.count() > 0:
            await combo.first.fill(date_str)
            await self.page.keyboard.press("Tab")
            await self.page.wait_for_timeout(500)

    # ---- Individual step helpers ----

    async def _answer_currently_insured(self, is_insured: bool) -> None:
        """Answer 'Is the customer currently insured with Progressive Commercial Auto?'"""
        answer = "Yes" if is_insured else "No"
        print(f"    [Progressive] Currently insured with Progressive: {answer}")
        group = self.page.get_by_role(
            "radiogroup",
            name="Is the customer currently insured with Progressive Commercial Auto?",
        )
        await group.get_by_role("radio", name=answer, exact=True).click()
        await self.page.wait_for_timeout(300)

    async def _answer_has_usdot(self, has_usdot: bool) -> None:
        """
        Answer 'Does the customer have a USDOT Number?'
        Three options validated:
          - "Yes - the customer has a USDOT number"
          - "No - and the customer will not have a USDOT number"
          - "Not Yet - but the customer has applied/will apply for a USDOT number within 60 days"
        """
        if has_usdot:
            label = "Yes - the customer has a USDOT number"
        else:
            label = "No - and the customer will not have a USDOT number"
        print(f"    [Progressive] Has USDOT: {'Yes' if has_usdot else 'No'}")
        group = self.page.get_by_role(
            "radiogroup",
            name="Does the customer have a USDOT Number?",
        )
        await group.get_by_role("radio", name=label).click()
        await self.page.wait_for_timeout(500)

    async def _fill_usdot_number(self, usdot: str) -> None:
        """Fill the USDOT Number input that appears after choosing Yes."""
        print(f"    [Progressive] Filling USDOT: {usdot}")
        # Label: "USDOT Number associated with the customer's business:"
        box = self.page.get_by_role(
            "textbox",
            name="USDOT Number associated with the customer's business:",
        )
        await box.wait_for(state="visible", timeout=10_000)
        await box.fill(usdot)

    async def _click_verify_usdot(self) -> None:
        """
        Click the 'Verify' button next to USDOT.
        CRITICAL: without this click, the page will reject submission with
        'Please use the Verify USDOT button to verify your USDOT Number.'
        """
        print("    [Progressive] Clicking Verify USDOT...")
        btn = self.page.get_by_role("button", name="Verify USDOT")
        if await btn.count() == 0:
            # Fallback: label may just be "Verify"
            btn = self.page.locator("span.g-btn-text", has_text="Verify").first
        await btn.click(timeout=10_000)
        # Wait for SAFER lookup to complete
        await self.page.wait_for_timeout(3_000)

    async def _confirm_usdot_belongs_to_customer(self, confirm: bool) -> None:
        """
        After Verify, Progressive asks: 'Does this USDOT Number belong to
        the customer's business?' — answer Yes to continue.
        """
        answer = "Yes" if confirm else "No"
        print(f"    [Progressive] USDOT belongs to customer: {answer}")
        group = self.page.get_by_role(
            "radiogroup",
            name="Does this USDOT Number belong to the customer's business?",
        )
        await group.get_by_role("radio", name=answer, exact=True).click()
        await self.page.wait_for_timeout(500)

    async def _select_entity_type(self, entity_type: str) -> None:
        """
        Select business structure. Three radio options:
          - "Individual / Sole Proprietor"
          - "Partnership"
          - "Corporation or LLC / Non-Profit"
        """
        et_upper = (entity_type or "").upper()
        if "LLC" in et_upper or "CORP" in et_upper:
            label = "Corporation or LLC / Non-Profit"
        elif "PARTNER" in et_upper:
            label = "Partnership"
        else:
            label = "Individual / Sole Proprietor"

        print(f"    [Progressive] Selecting entity type: {label}")
        group = self.page.get_by_role(
            "radiogroup",
            name="How is the customer's business structured?",
        )
        await group.get_by_role("radio", name=label).click()
        await self.page.wait_for_timeout(500)

    async def _fill_business_name(
        self, name: Optional[str], dba: Optional[str] = None
    ) -> None:
        """Fill Business Name (LLC/Corp) and DBA (Individual).

        Progressive renders Business Name as a RADIO with two options:
          1. The SAFER-resolved name (from USDOT lookup) — preferred when present
          2. "Enter a different Business Name" → reveals a textbox
        """
        if not name:
            return
        print(f"    [Progressive] Setting business name: {name}")
        await self.page.wait_for_timeout(500)

        # Try the SAFER pre-poblated radio first (matches name exactly)
        safer_radio = self.page.get_by_role("radio", name=name, exact=False)
        if await safer_radio.count() > 0:
            try:
                await safer_radio.first.click(timeout=3_000)
                print(f"    [Progressive] Used SAFER-resolved business name radio")
                await self.page.wait_for_timeout(500)
            except Exception:
                pass
        else:
            # Fall back to "Enter a different Business Name" + textbox
            diff_radio = self.page.get_by_role("radio", name="Enter a different Business Name")
            if await diff_radio.count() > 0:
                await diff_radio.first.click(timeout=3_000)
                await self.page.wait_for_timeout(500)
            box = self.page.get_by_role("textbox", name="Business Name")
            if await box.count() > 0:
                await box.first.fill(name)

        if dba:
            dba_box = self.page.get_by_role(
                "textbox", name="DBA Name (Optional)"
            )
            if await dba_box.count() > 0:
                await dba_box.first.fill(dba)

    async def _select_business_type(self, commodity: Optional[str]) -> None:
        """Select the business type via the 'Business type list' combobox.

        This combobox IS the required "keyword describing your business" field.
        The quick-button shortcuts ("Trucker", etc.) do NOT populate it, so the
        START page rejects submission ("This field is required") — we must drive
        the combobox itself. Its accessible name ("Business type list") and the
        option labels are stable; only the per-session ExtJS ids change.
        """
        if not commodity:
            print("    [Progressive] WARN: no commodity provided, skipping")
            return
        search_term, preferred = self._map_commodity_to_option(commodity)
        print(
            f"    [Progressive] Business type: '{commodity}' -> "
            f"option~'{preferred or search_term}'"
        )

        combo = self.page.get_by_role("combobox", name="Business type list")
        await combo.wait_for(state="visible", timeout=15_000)
        await combo.click()
        await self.page.wait_for_timeout(400)

        # Prefer the exact mapped option from the full (non-virtualized) list.
        opt = None
        if preferred:
            cand = self.page.get_by_role("option", name=preferred, exact=False)
            if await cand.count() > 0:
                opt = cand.first
        # Otherwise type to filter, then take the first remaining option.
        if opt is None:
            try:
                await combo.fill(search_term)
            except Exception:
                await self.page.keyboard.type(search_term, delay=60)
            await self.page.wait_for_timeout(1_200)
            options = self.page.get_by_role("option")
            if await options.count() > 0:
                opt = options.first

        if opt is not None:
            await opt.click(timeout=5_000)
            await self.page.wait_for_timeout(1_000)
        else:
            print(
                f"    [Progressive] WARN: no business-type option matched "
                f"'{search_term}'"
            )

    def _map_commodity_to_option(
        self, commodity: str
    ) -> tuple[str, Optional[str]]:
        """Map a BlueQuote commodity to (search_term, preferred_option_text)
        for the Business type list combobox. `preferred` is an exact-ish option
        label when known; `search_term` filters the list as a fallback for
        anything not explicitly mapped (keeps this dynamic for any BlueQuote)."""
        c = (commodity or "").upper()
        table = [
            (("DIRT", "SAND", "GRAVEL"), "Dirt Sand", "Dirt Sand & Gravel (For A Fee)"),
            (("FRACK",), "Fracking", "Fracking Sand Hauling"),
            (("COAL",), "Coal", "Coal Hauling"),
            (("AUTO HAUL", "CAR HAUL"), "Auto Hauler", "Auto Hauler (For Hire Trucking)"),
            (("LIVESTOCK",), "Livestock", "Livestock Hauling (For A Fee)"),
            (("LOG", "WOOD CHIP"), "Logging", "Logging Trucker"),
            (("GARBAGE", "TRASH"), "Garbage", "Garbage & Trash Hauling/Removal"),
            (("HAZARD", "HAZMAT"), "Hazardous", "Hazardous Materials Hauling"),
            (("CONTAINER",), "Container", "Container Hauling"),
            (("AGRICULTUR", "FARM PRODUCE"), "Agricultural", "Agricultural Hauling (For A Fee)"),
            (("DAIRY",), "Dairy", "Dairy Products Hauling (For A Fee)"),
            (("REFRIG", "REEFER", "FROZEN"), "Frozen Foods", "Frozen Foods Hauling"),
        ]
        for keys, term, opt in table:
            if any(k in c for k in keys):
                return (term, opt)
        # General freight family.
        if any(
            k in c
            for k in ("FLATBED", "DRY VAN", "BOX TRUCK", "STRAIGHT",
                      "CARGO VAN", "FREIGHT", "GENERAL")
        ):
            return ("General Freight", "General Freight Hauler")
        # Last resort: filter by the first meaningful word of the commodity.
        skip = {"THE", "FOR", "AND", "100%", "OF"}
        word = next(
            (w for w in c.replace(",", " ").replace("%", " ").split()
             if len(w) > 2 and w not in skip),
            "Hauling",
        )
        return (word.title(), None)

    async def _answer_hazmat_placard(self, has_placard: bool) -> None:
        """
        After business type, Progressive asks (for Trucker):
        'Do any listed vehicles or the load require a hazardous material placard?'
        """
        group = self.page.get_by_role(
            "radiogroup",
            name="Do any listed vehicles or the load require a hazardous material placard?",
        )
        if await group.count() == 0:
            return  # Question didn't appear (not all types trigger it)

        answer = "Yes" if has_placard else "No"
        print(f"    [Progressive] Hazmat placard: {answer}")
        await group.get_by_role("radio", name=answer, exact=True).click()
        await self.page.wait_for_timeout(300)

    async def _fill_owner_info(
        self,
        owner_name: Optional[str],
        street: Optional[str] = None,
        zip_code: Optional[str] = None,
        city: Optional[str] = None,
        dob: Optional[str] = None,
    ) -> None:
        """Fill First/Last name, Street Address, ZIP, City, DOB."""
        if not owner_name:
            print("    [Progressive] WARN: no owner name provided")
            return
        print(f"    [Progressive] Setting owner: {owner_name}")

        parts = owner_name.strip().split()
        first_name = parts[0] if parts else ""
        last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

        first_box = self.page.get_by_role("textbox", name="First Name")
        if await first_box.count() > 0:
            await first_box.first.fill(first_name)

        last_box = self.page.get_by_role("textbox", name="Last Name")
        if await last_box.count() > 0:
            await last_box.first.fill(last_name)

        # Home Address: Progressive renders this as a RADIO when SAFER returned
        # an address (e.g. for USDOT-verified businesses).
        # Try SAFER radio first if street is provided AND matches; else click "Enter a different address"
        if street:
            print(f"    [Progressive] Street address: {street}")
            # Prefer the SAFER pre-verified address radio. Its accessible name
            # is the full "STREET CITY STATE ZIP", so we match by the street
            # substring (role+name is stable; the previous has-text filter never
            # matched because radio inputs have no text children, which forced
            # the manual-entry path and triggered an address-validation warning
            # that blocked submission).
            used_radio = False
            safer_addr_radio = self.page.get_by_role(
                "radio", name=street, exact=False
            )
            if await safer_addr_radio.count() > 0:
                try:
                    await safer_addr_radio.first.click(timeout=3_000)
                    used_radio = True
                    print("    [Progressive] Used SAFER-resolved home address radio")
                    await self.page.wait_for_timeout(500)
                except Exception:
                    pass

            if not used_radio:
                # Fall back to "Enter a different address" + manual fields
                diff_radio = self.page.get_by_role(
                    "radio", name="Enter a different address"
                )
                if await diff_radio.count() > 0:
                    try:
                        await diff_radio.first.click(timeout=2_000)
                        await self.page.wait_for_timeout(500)
                    except Exception:
                        pass
                box = self.page.get_by_role("textbox", name="Street Address")
                if await box.count() > 0:
                    await box.first.fill(street)

                if zip_code:
                    print(f"    [Progressive] ZIP: {zip_code}")
                    zb = self.page.get_by_role("textbox", name="ZIP Code")
                    if await zb.count() > 0:
                        await zb.first.fill(zip_code)
                        await self.page.keyboard.press("Tab")
                        await self.page.wait_for_timeout(1_000)

                if city:
                    print(f"    [Progressive] City: {city}")
                    cb = self.page.get_by_role("textbox", name="City")
                    if await cb.count() > 0:
                        try:
                            current = await cb.first.input_value()
                        except Exception:
                            current = ""
                        if not current:
                            await cb.first.fill(city)

        if dob:
            print(f"    [Progressive] DOB: {dob}")
            box = self.page.get_by_role("textbox", name="Date of Birth")
            if await box.count() == 0:
                box = self.page.get_by_role("combobox", name="Date of Birth")
            if await box.count() > 0:
                await box.first.fill(dob)
                await self.page.keyboard.press("Tab")

    async def _answer_oil_gas_fields(self, hauls_oil_gas: bool) -> None:
        """Conditional required question shown for trucking / dirt-sand-gravel
        classes: 'Are any vehicles used to haul to or from oil & gas fields?'

        Default No (most dirt/sand/gravel haulers are not oilfield). The
        radiogroup carries the question as its accessible name (stable), even
        though its DOM id/name are per-session ExtJS hashes. Optional: silently
        skips when the question isn't rendered for this business type.
        """
        group = self.page.get_by_role(
            "radiogroup",
            name="Are any vehicles used to haul to or from oil & gas fields?",
        )
        if await group.count() == 0:
            return
        answer = "Yes" if hauls_oil_gas else "No"
        print(f"    [Progressive] Oil & gas fields hauling: {answer}")
        await group.get_by_role("radio", name=answer, exact=True).click()
        await self.page.wait_for_timeout(300)

    async def _click_start_quote(self) -> None:
        """Click 'Ok, start quote.' and CONFIRM the page actually advances.

        Progressive keeps us on pageName=BusinessOwnerInfo and shows inline
        validation errors when a required field is missing/invalid, so a plain
        networkidle wait would be a false "advanced" signal (this masked the
        owner-DOB / oil&gas gaps). We wait for the URL to leave
        BusinessOwnerInfo; if it doesn't, we collect the validation messages
        and unanswered required questions so the failure is actionable for any
        BlueQuote.
        """
        print("    [Progressive] Clicking 'Ok, start quote.'...")
        await self.remove_overlays()
        btn = self.page.get_by_role("button", name="Ok, start quote.")
        await btn.first.click(timeout=10_000)
        try:
            await self.page.wait_for_function(
                "() => !location.href.includes('pageName=BusinessOwnerInfo')",
                timeout=30_000,
            )
            await self.page.wait_for_load_state("networkidle", timeout=30_000)
            print("    [Progressive] Quote started - moved to VehicleSummary")
        except Exception:
            errors = await self._collect_validation_errors()
            await self.screenshot("start_quote_did_not_advance")
            raise RuntimeError(
                "START page did not advance after 'Ok, start quote.' — a "
                f"required field is missing or invalid. Page reported: {errors}"
            )

    async def _collect_validation_errors(self) -> str:
        """Scrape visible inline error messages + unanswered required questions
        from the START page, to make a non-advance failure self-explanatory."""
        try:
            return await self.page.evaluate(
                """() => {
                    const msgs = [];
                    document.querySelectorAll(
                        '.error-message, .x-form-invalid-field, [class*="error"]'
                    ).forEach(e => {
                        const t = (e.textContent || '').replace(/\\s+/g,' ').trim();
                        if (t && e.offsetParent !== null) msgs.push(t.slice(0,90));
                    });
                    // Required labels (label.requiredField) whose field group
                    // has no checked/filled control.
                    document.querySelectorAll('label.requiredField').forEach(l => {
                        const grpId = (l.id || '').replace(/^c_/, 'f_');
                        const grp = document.getElementById(grpId);
                        if (!grp) return;
                        const checked = grp.querySelector('input:checked');
                        const filled = Array.from(grp.querySelectorAll('input,select'))
                            .some(i => i.value && i.value.trim());
                        if (!checked && !filled) {
                            const q = (l.textContent || '').replace(/\\s+/g,' ').trim();
                            if (q) msgs.push('UNANSWERED: ' + q.slice(0,70));
                        }
                    });
                    return Array.from(new Set(msgs)).slice(0,10).join(' || ')
                        || '(no visible validation message)';
                }"""
            )
        except Exception:
            return "(could not collect validation errors)"
