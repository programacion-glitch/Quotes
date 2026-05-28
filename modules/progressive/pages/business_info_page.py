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
        """
        Select business type via quick button or combobox.
        If Trucker/Contractor is chosen, a sub-type dropdown appears.
        """
        if not commodity:
            print("    [Progressive] WARN: no commodity provided, skipping")
            return
        print(f"    [Progressive] Selecting business type for: {commodity}")

        # Map incoming commodity to the best quick-button + sub-type
        quick, subtype = self._map_commodity(commodity)

        # Click quick button if available
        if quick:
            print(f"    [Progressive] Quick button: {quick}")
            btn = self.page.get_by_role("button", name=quick, exact=True)
            if await btn.count() > 0:
                await btn.first.click(timeout=5_000)
                await self.page.wait_for_timeout(1_500)
        else:
            # Fall back to combobox search
            combo = self.page.get_by_role("combobox", name="Business type list")
            await combo.click()
            search_term = commodity.split(",")[0].strip().split()[0]
            await combo.type(search_term, delay=80)
            await self.page.wait_for_timeout(1_200)
            option = self.page.get_by_role("option").first
            if await option.count() > 0:
                await option.click(timeout=5_000)

        # If sub-type needed (Trucker -> Type of Trucker)
        if subtype:
            print(f"    [Progressive] Sub-type: {subtype}")
            await self.page.wait_for_timeout(500)
            sub_combo = self.page.get_by_role("combobox", name="Type of Trucker")
            if await sub_combo.count() > 0:
                await sub_combo.click()
                # Pick option by visible name
                opt = self.page.get_by_role("option", name=subtype).first
                if await opt.count() > 0:
                    await opt.click(timeout=5_000)
                    await self.page.wait_for_timeout(500)

    def _map_commodity(self, commodity: str) -> tuple[Optional[str], Optional[str]]:
        """Map profile commodity to (quick_button, trucker_subtype)."""
        c = (commodity or "").upper()

        # Dirt/sand/gravel -> dedicated quick button (no sub-type needed there)
        if "DIRT" in c or "SAND" in c or "GRAVEL" in c:
            # Actually routing through Trucker+DSG gives better options
            return ("Trucker", "Dirt, Sand and Gravel")

        # Flatbed/dry van/reefer/box truck -> General Freight trucker
        trucker_keywords = [
            "FLATBED", "DRY VAN", "REEFER", "BOX TRUCK", "STRAIGHT",
            "CARGO VAN", "GENERAL FREIGHT", "FREIGHT",
        ]
        if any(k in c for k in trucker_keywords):
            return ("Trucker", "General Freight / Other")

        # Specific commodity -> Trucker with matching sub-type
        subtype_map = {
            "AUTO HAULER": "Auto Hauler",
            "AGRICULTURAL": "Agricultural",
            "AGRICULTUR": "Agricultural",
            "COAL": "Coal",
            "CONTAINER": "Containers",
            "DEBRIS": "Debris Removal",
            "FRACKING": "Fracking, Sand or Water",
            "FRAC SAND": "Fracking, Sand or Water",
            "GARBAGE": "Garbage & Trash",
            "TRASH": "Garbage & Trash",
            "HAZARDOUS": "Hazardous Materials / Placards",
            "HAZMAT": "Hazardous Materials / Placards",
            "HOUSEHOLD": "Household Goods Mover",
            "LIVESTOCK": "Livestock",
            "LOGGING": "Logging / Wood Chips",
            "WOOD CHIP": "Logging / Wood Chips",
            "MACHINERY": "Machinery & Heavy Equipment",
            "HEAVY EQUIP": "Machinery & Heavy Equipment",
            "MOBILE HOME": "Mobile Home Toter",
            "OILFIELD": "Oilfield Materials",
            "REFRIG": "Refrigerated Goods",
            "BUILDING MATERIAL": "General Freight / Other",
        }
        for key, value in subtype_map.items():
            if key in c:
                return ("Trucker", value)

        # Other top-level categories
        if "TOW" in c:
            return ("Towing", None)
        if "LANDSCAP" in c:
            return ("Landscaper", None)
        if "CONTRACTOR" in c or "CONSTRUC" in c:
            return ("Contractor", None)  # NOTE: Contractor needs its own sub-type

        # Default: Trucker / General Freight
        return ("Trucker", "General Freight / Other")

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
            # First try the SAFER prefilled radio (looks like "STREET CITY STATE ZIP")
            safer_addr_radio = self.page.locator(
                'input[type="radio"]'
            ).filter(has=self.page.get_by_text(street, exact=False))
            used_radio = False
            if await safer_addr_radio.count() > 0:
                try:
                    await safer_addr_radio.first.click(timeout=2_000)
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

    async def _click_start_quote(self) -> None:
        """Click 'Ok, start quote.' to proceed to VehicleSummary."""
        print("    [Progressive] Clicking 'Ok, start quote.'...")
        await self.remove_overlays()
        btn = self.page.get_by_role("button", name="Ok, start quote.")
        await btn.first.click(timeout=10_000)
        # The next page is VehicleSummary
        await self.page.wait_for_load_state("networkidle", timeout=60_000)
        print("    [Progressive] Quote started - moved to VehicleSummary")
