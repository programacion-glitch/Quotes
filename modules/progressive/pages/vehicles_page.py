"""
Vehicle pages for Progressive wizard.

All selectors validated LIVE 2026-05-25 with USDOT 2998569 (M&D CUSTOM FREIGHT LLC).

Flow:
  VehicleSummary
    → "Add" on a suggested vehicle  OR  "Add Vehicle" → MostCommonVehicles
    → MostCommonVehicles: click vehicle type button
    → AddVehicle: fill form (VIN or Y/M/M, ZIP, distance, GVW, loan, comp/coll, etc.)
    → Continue → back to VehicleSummary
    → repeat per vehicle
    → Continue → DRIVERS step

Dynamic-fields warnings:
  - Selecting Vehicle Type=Sport Utility Vehicle reveals "What type of SUV is this?" + Annual Mileage
  - Selecting loan=No reveals "Does the customer need Comprehensive or Collision coverage..."
  - Selecting Comp/Coll=Yes reveals "What is the total value of all permanently attached equipment..."
"""

from typing import List, Optional

from modules.progressive.field_mapper import MappedVehicle
from modules.progressive.pages.base_page import BasePage


VEHICLE_TYPES = [
    "Truck Tractor",
    "Box Truck",
    "Pickup Truck",
    "Flatbed Truck",
    "Cargo Van",
    "Other / Not Listed",
]


class VehicleSummaryPage(BasePage):
    """VehicleSummary page - lists vehicles on the quote.

    URL: pageName=VehicleSummary
    Heading: "Here are the vehicles on the quote:"
    Progressive may pre-detect vehicles via "We found vehicles..." with Add buttons.
    """

    async def add_vehicle(self) -> None:
        """Open the add-vehicle (MostCommonVehicles) page.

        The VehicleSummary renders different controls depending on whether
        Progressive pre-detected vehicles for the USDOT. Try, in order:
          1. a visible "Add Vehicle" button (various casings/labels),
          2. an "Add another vehicle" link,
          3. a pre-detected suggestion's "Add" button.
        Waiting for visibility + scrolling avoids the flaky "element is not
        visible" timeout seen on the ExtJS-rendered summary.
        """
        await self.page.wait_for_load_state("networkidle", timeout=30_000)
        print("    [Progressive] Adding new vehicle...")

        # Scroll to bottom so the gray footer with 'Add Vehicle' / 'Add
        # Trailer' is in view (otherwise the role lookup may pick a hidden
        # variant rendered elsewhere on the page).
        try:
            await self.page.evaluate(
                "window.scrollTo(0, document.body.scrollHeight)"
            )
            await self.page.wait_for_timeout(500)
        except Exception:
            pass

        # Try text-based and role-based selectors. ExtJS can render the
        # "Add Vehicle" control as a button, link or styled div, so text
        # match catches all. force=True bypasses overlap/visibility checks
        # from ExtJS overlays that may cover the button.
        candidates = [
            self.page.get_by_text("Add Vehicle", exact=True),
            self.page.get_by_role("button", name="Add Vehicle", exact=True),
            self.page.get_by_role("button", name="Add a Vehicle"),
            self.page.get_by_role("link", name="Add Vehicle", exact=False),
            self.page.get_by_role("button", name="Add another vehicle", exact=False),
        ]
        for loc in candidates:
            n = await loc.count()
            for i in range(n):
                el = loc.nth(i)
                try:
                    if not await el.is_visible():
                        continue
                    await el.scroll_into_view_if_needed(timeout=3_000)
                    await el.click(force=True, timeout=10_000)
                    await self.page.wait_for_load_state(
                        "networkidle", timeout=30_000
                    )
                    return
                except Exception:
                    continue

        # Fallback: a pre-detected suggestion with a plain "Add" button.
        if await self.add_suggested_vehicle(0):
            return

        await self.screenshot("vehicle_summary_no_add_button")
        raise RuntimeError(
            "Could not find a visible 'Add Vehicle' control on VehicleSummary"
        )

    async def add_trailer(self) -> None:
        """Click 'Add Trailer' / 'Add Another Trailer'."""
        await self.page.wait_for_load_state("networkidle", timeout=30_000)
        print("    [Progressive] Adding trailer...")
        btn = self.page.get_by_role("button", name="Add Another Trailer")
        if await btn.count() == 0:
            btn = self.page.get_by_role("button", name="Add Trailer")
        await btn.first.click(timeout=10_000)
        await self.page.wait_for_load_state("networkidle", timeout=30_000)

    async def add_suggested_vehicle(self, index: int = 0) -> bool:
        """Click 'Add' on the Nth pre-detected suggestion.

        Note: this STILL routes through MostCommonVehicles. The VIN gets
        pre-filled on the AddVehicle form but the type still needs to be chosen.
        """
        add_buttons = self.page.get_by_role("button", name="Add", exact=True)
        count = await add_buttons.count()
        if count == 0 or index >= count:
            return False
        await add_buttons.nth(index).click(timeout=10_000)
        await self.page.wait_for_load_state("networkidle", timeout=30_000)
        return True

    async def click_continue(self) -> None:
        """Click Continue to proceed to the Drivers page.

        VehicleSummary may list SAFER-suggested vehicles we chose NOT to add
        (e.g. the customer's personal cars). Clicking Continue often pops a
        native browser confirm() dialog or an ExtJS modal asking whether to
        leave them off — auto-accept either. Then verify URL advanced.
        """
        print("    [Progressive] Continuing to DRIVERS...")

        # Auto-accept any browser confirm/alert dialogs that appear during
        # this click (e.g. "Are you sure you want to skip 5 SAFER vehicles?").
        async def _on_dialog(dialog):
            print(f"    [Progressive] Auto-accepting dialog: {dialog.message[:80]!r}")
            try:
                await dialog.accept()
            except Exception:
                pass

        self.page.on("dialog", lambda d: __import__("asyncio").create_task(_on_dialog(d)))

        try:
            await self.page.evaluate(
                "window.scrollTo(0, document.body.scrollHeight)"
            )
            await self.page.wait_for_timeout(400)
        except Exception:
            pass

        # BasePage.safe_click_continue handles: blur → text/role fallback →
        # force=True → JS dispatch → retry loop → URL verification.
        await self.safe_click_continue(expect_url_changes_from="VehicleSummary")


class MostCommonVehiclesPage(BasePage):
    """Intermediate page with 6 vehicle-type buttons.

    URL: pageName=MostCommonVehicles
    """

    async def select_vehicle_type(self, trailer_type: str) -> None:
        """Pick the most appropriate type for the trailer string.

        The vehicle type options are rendered as clickable tiles (styled divs
        or buttons). Use get_by_text to find the tile by visible label and
        force=True to bypass any overlay checks.
        """
        label = self._map_to_button(trailer_type)
        print(f"    [Progressive] Selecting vehicle type: {label}")
        tile = self.page.get_by_text(label, exact=True).first
        await tile.click(force=True)
        await self.wait_for_extjs_idle()

    async def click_add_trailer_instead(self) -> None:
        """Switch from vehicle flow to trailer flow."""
        link = self.page.get_by_role("button", name="Add a trailer instead")
        if await link.count() == 0:
            link = self.page.get_by_role("link", name="Add a trailer instead")
        await link.click(timeout=10_000)
        await self.page.wait_for_load_state("networkidle", timeout=30_000)

    def _map_to_button(self, trailer_type: str) -> str:
        """Map blue-quote trailer string to Progressive's button label."""
        t = (trailer_type or "").upper()
        if "FLATBED" in t:
            return "Flatbed Truck"
        if "BOX" in t or "STRAIGHT" in t or "DRY VAN" in t or "REEFER" in t:
            return "Box Truck"
        if "PICKUP" in t:
            return "Pickup Truck"
        if "CARGO VAN" in t:
            return "Cargo Van"
        if "TRACTOR" in t:
            return "Truck Tractor"
        return "Other / Not Listed"


class AddVehiclePage(BasePage):
    """Add-Vehicle form.

    URL: pageName=AddVehicle

    Fields (validated live):
      - "Add Vehicle By" radio: "Year, Make, Model" | "VIN" (default)
      - VIN textbox + "Lookup VIN" button
      - "Vehicle Type" combobox (post-VIN, when type doesn't match)
      - "What type of SUV is this?" combobox (when Vehicle Type=SUV)
      - "Annual Mileage" combobox (for personal-class vehicles)
      - ZIP textbox (pre-filled from owner address)
      - "Farthest one-way distance this vehicle typically travels..." combobox
      - "What is the gross vehicle weight?" combobox
      - "What is this vehicle's tonnage?" combobox (Pickup-only)
      - "How many driving wheels does this vehicle have?" combobox (Pickup-only)
      - "What type of trailer hitch does this vehicle have?" combobox (Pickup-only)
      - "Is this vehicle used for business, personal or both?" radio
      - "Is there a loan/lease on this vehicle?" radio: Yes-Loan | Yes-Lease | No
      - "Does the customer need Comprehensive or Collision coverage..." radio (post-loan)
      - "What is the total value of all permanently attached equipment..." radio
      - Continue button
    """

    REQUIRED_FIELDS = ("year", "make", "model", "vin", "vehicle_value")
    CONDITIONAL_FIELDS = ("vehicle_has_no_equipment", "plate_number")
    OPTIONAL_FIELDS = ("body_type", "garaging_zip")

    def __init__(self, page):
        super().__init__(page)
        self.warnings: list[str] = []

    def _log_skipped(self, field: str, reason: str) -> None:
        msg = f"add_vehicle: skipped '{field}' — {reason}"
        print(f"    [Progressive] {msg}")
        self.warnings.append(msg)

    async def fill_from_mapped(self, vehicle: MappedVehicle) -> None:
        """Fill the AddVehicle form from a MappedVehicle and click Continue."""
        await self.page.wait_for_load_state("networkidle", timeout=30_000)

        if vehicle.vin:
            await self._fill_by_vin(vehicle.vin)
        else:
            await self._fill_by_ymm(vehicle.year, vehicle.make, vehicle.model)

        # If vehicle type mismatch dropdown appears, pick best
        await self._handle_vehicle_type_mismatch(vehicle.trailer_type)

        # ZIP (Progressive pre-fills with owner ZIP; we may need to overwrite)
        if vehicle.garaging_zip:
            await self._set_zip(vehicle.garaging_zip)

        # Farthest distance — convert simple miles to Progressive's option label
        await self._set_distance(vehicle.radius_miles)

        # GVW
        await self._set_combobox_by_label(
            "What is the gross vehicle weight?", vehicle.gvw
        )

        # Business/personal use - default Business Only
        await self._set_radio("Is this vehicle used for business, personal or both?", "Business Only")

        # Loan/Lease
        loan_label = {
            "Loan": "Yes - Loan",
            "Lease": "Yes - Lease",
            "No": "No",
        }.get(vehicle.has_loan, "No")
        await self._set_radio("Is there a loan/lease on this vehicle?", loan_label)
        # Wait for ExtJS to render the conditional Comp/Coll question
        # that's revealed by loan=No (an 800ms flat wait was too short for
        # Beverage Distributor commodities — replaced with dynamic wait).
        try:
            await self.wait_for_extjs_idle(timeout_ms=5_000)
        except Exception:
            pass
        await self.page.wait_for_timeout(600)

        # Comp/Coll question appears when loan=No. The customer's APD intent
        # is signaled by the Blue Quote "Value" column:
        #   - vehicle.value set    → customer wants APD (Comp + Coll = Yes)
        #   - vehicle.value None   → liability-only (Comp + Coll = No, skips
        #                            equipment+value sub-form entirely)
        # Note: when has_loan != "No" Progressive auto-requires Comp/Coll
        # (it's a lender mandate) so we DON'T expose this branch.
        if vehicle.has_loan == "No":
            wants_apd = bool(vehicle.value)
            apd_answer = "Yes" if wants_apd else "No"
            await self._set_radio(
                "Does the customer need Comprehensive or Collision coverage",
                apd_answer,
            )
            # Wait for ExtJS to render the equipment + value fields that
            # are revealed by Comp/Coll=Yes (no-op if we answered No).
            try:
                await self.wait_for_extjs_idle(timeout_ms=5_000)
            except Exception:
                pass
            await self.page.wait_for_timeout(800)

            if wants_apd:
                # Equipment value: Progressive's 2026-06 UI uses a free-text
                # "Value" textbox plus a "Vehicle has no equipment" checkbox.
                # We assume no permanently-attached equipment by default.
                await self._tick_no_equipment_checkbox()
                # Vehicle market value: use the Blue Quote Value column. If
                # it's missing we'd never enter this branch (wants_apd=False).
                await self._fill_vehicle_value(default=vehicle.value)
            else:
                print(
                    "    [Progressive] APD = No (Blue Quote has no Value for "
                    "this vehicle); skipping equipment + Vehicle Value section"
                )

        await self._click_continue()

    async def _fill_by_vin(self, vin: str) -> None:
        """Use VIN entry path."""
        print(f"    [Progressive] Adding vehicle by VIN: {vin}")
        # Make sure VIN radio is selected
        vin_radio = self.page.get_by_role("radio", name="VIN", exact=True)
        if await vin_radio.count() > 0:
            try:
                await vin_radio.first.click(timeout=2_000)
            except Exception:
                pass

        vin_box = self.page.get_by_role(
            "textbox", name="Vehicle Identification Number (VIN)"
        )
        # Could be pre-filled from suggested vehicle - check and clear if needed
        try:
            current = await vin_box.first.input_value()
            if current and current != vin:
                clear_btn = self.page.get_by_role("button", name="Clear VIN")
                if await clear_btn.count() > 0:
                    await clear_btn.first.click()
                    await self.page.wait_for_timeout(500)
        except Exception:
            pass

        # VIN is format-restricted; verify=False avoids mismatch on raw vs
        # formatted input_value (ExtJS may auto-uppercase or mask mid-stream).
        await self.safe_fill(vin_box.first, vin, verify=False)
        lookup_btn = self.page.get_by_role("button", name="Lookup VIN")
        if await lookup_btn.count() > 0:
            await lookup_btn.first.click(timeout=10_000)
            await self.page.wait_for_load_state("networkidle", timeout=20_000)
            await self.page.wait_for_timeout(1_500)

    async def _fill_by_ymm(
        self, year: Optional[int], make: Optional[str], model: Optional[str]
    ) -> None:
        """Use Year/Make/Model entry (cascading comboboxes).

        WARNING (validated live 2026-06-01): The ExtJS combobox cascade is
        fragile. After selecting Year, the Make combobox stays
        `aria-disabled="true"` indefinitely — Progressive's onchange handler
        for Year doesn't always fire from a Playwright option click.

        Use VIN entry instead whenever the Blue Quote provides a VIN. This
        method is kept as a best-effort fallback for the rare case where
        a vehicle has Y/M/M but no VIN; do not rely on it for happy-path
        end-to-end runs.

        TODO: investigate forcing the cascade via JS, e.g.
            Ext.getCmp('<year-combo-id>').fireEvent('select', ...);
        or sending a Tab/blur keystroke after the option click.
        """
        if not (year and make and model):
            print(f"    [Progressive] WARN: Y/M/M incomplete - year={year} make={make} model={model}")
            return
        print(f"    [Progressive] Adding by Y/M/M (fragile path): {year} {make} {model}")
        ymm_radio = self.page.get_by_role("radio", name="Year, Make, Model")
        if await ymm_radio.count() > 0:
            await ymm_radio.first.click(timeout=2_000)
            await self.page.wait_for_timeout(500)

        await self.safe_select_combo(await self.find_combo("Year"), str(year))
        # Try a Tab to nudge the cascade. Does not fix all cases.
        try:
            await self.page.keyboard.press("Tab")
            await self.page.wait_for_timeout(800)
        except Exception:
            pass
        await self.safe_select_combo(await self.find_combo("Make"), make)
        await self.safe_select_combo(await self.find_combo("Model"), model)

    async def _handle_vehicle_type_mismatch(self, trailer_type: Optional[str]) -> None:
        """If a 'Vehicle Type' combobox appeared (VIN didn't match selected type),
        pick the best option."""
        combo = await self.find_combo("Vehicle Type")
        if await combo.count() == 0:
            return
        # Map trailer type to a Vehicle Type combo option
        t = (trailer_type or "").upper()
        option_label = "Sport Utility Vehicle"  # fallback for unknown
        if "PICKUP" in t:
            option_label = "Pickup"
        elif "VAN" in t:
            option_label = "Cargo Van"
        elif "FLATBED" in t:
            option_label = "Flatbed Truck"

        await combo.first.click()
        await self.page.wait_for_timeout(400)
        opt = self.page.get_by_role("option", name=option_label, exact=False).first
        if await opt.count() > 0:
            await opt.click(timeout=5_000)
            await self.page.wait_for_timeout(1_000)

        # If "What type of SUV is this?" appeared after picking SUV, pick "SUV"
        suv_combo = await self.find_combo("What type of SUV is this?")
        if await suv_combo.count() > 0:
            await suv_combo.first.click()
            await self.page.wait_for_timeout(400)
            await self.page.get_by_role("option", name="SUV", exact=True).first.click()
            await self.page.wait_for_timeout(500)

    async def _set_zip(self, zip_code: str) -> None:
        zip_box = self.page.get_by_role(
            "textbox", name="Zip code where the vehicle is located"
        )
        if await zip_box.count() > 0:
            try:
                current = await zip_box.first.input_value()
            except Exception:
                current = ""
            if current != zip_code:
                # verify=False because the ZIP field may auto-format (add dash)
                await self.safe_fill(zip_box.first, zip_code, verify=False)

    async def _set_distance(self, radius_miles: str) -> None:
        """Convert simple radius string to Progressive's option label."""
        r = (radius_miles or "").lower()
        if "500" in r or "over" in r or "more than" in r:
            option = "More than 500 miles"
        elif "300" in r:
            option = "300 miles"
        elif "200" in r:
            option = "200 miles"
        elif "100" in r:
            option = "100 miles"
        elif "50" in r:
            option = "50 miles"
        else:
            option = "More than 500 miles"
        await self._set_combobox_by_label(
            "Farthest one-way distance this vehicle typically travels", option
        )

    async def _set_combobox_by_label(self, label: str, option_text: str) -> None:
        """Generic helper for Sencha ExtJS comboboxes via BasePage primitives."""
        combo = await self.find_combo(label)
        if await combo.count() == 0:
            return
        try:
            await self.safe_select_combo(combo, option_text)
        except Exception as e:
            print(f"    [Progressive] WARN: combobox '{label}' = '{option_text}' failed: {e}")

    async def _set_radio(self, group_label: str, value: str) -> None:
        """Find a radiogroup by partial accessible-name match and pick `value`.

        Uses field_exists (which polls until visible) instead of bare count()
        — the question may be revealed by a sibling radio (e.g. Comp/Coll
        appears AFTER loan=No), and ExtJS render is asynchronous.
        Logs both success and "not found" so silent skips can be diagnosed.
        """
        group = await self.find_radiogroup(group_label)
        if not await self.field_exists(group, wait_ms=2_500):
            print(f"    [Progressive] _set_radio: '{group_label}' not visible (skipped)")
            return
        try:
            await self.safe_radio(group, value)
            print(f"    [Progressive] _set_radio: '{group_label}' = '{value}'")
        except Exception as e:
            print(f"    [Progressive] WARN: radio '{group_label}' = '{value}' failed: {e}")

    async def _tick_no_equipment_checkbox(self) -> None:
        """Tick the 'Vehicle has no equipment' checkbox to satisfy the
        'value of permanently attached equipment' required field."""
        cb = self.page.get_by_role("checkbox", name="Vehicle has no equipment")
        if await self.field_exists(cb, wait_ms=1500):
            try:
                await self.safe_checkbox(cb, check=True)
                print("    [Progressive] Equipment value: ticked 'Vehicle has no equipment'")
            except Exception as e:
                print(f"    [Progressive] WARN: 'Vehicle has no equipment' click failed: {e}")
        else:
            self._log_skipped("vehicle_has_no_equipment", "field_not_rendered")

    async def _fill_vehicle_value(self, default: str = "50000") -> None:
        """Fill the 'If this vehicle was sold today, how much would it be worth'
        textbox. Required since Progressive 2026-06 when Comp/Coll = Yes.

        The visible input has placeholder 'Vehicle Value'. ExtJS numberfields
        accept Playwright's .fill() reliably; .type() with delay can be lost
        if the field's validator runs mid-stream. Verify=False because ExtJS
        applies currency formatting ($) post-fill, changing the raw input_value.
        wait_for_currency_formatted ensures ExtJS finished before Continue.
        """
        # Ensure ExtJS finished rendering the equipment subform — the Vehicle
        # Value field is revealed by the "Vehicle has no equipment" checkbox
        # (or by entering an explicit equipment value). Without this wait,
        # all candidate selectors return count=0 because the input hasn't been
        # mounted yet.
        try:
            await self.wait_for_extjs_idle(timeout_ms=5_000)
        except Exception:
            pass
        await self.page.wait_for_timeout(600)
        candidates = [
            self.page.locator('input[placeholder="Vehicle Value"]'),
            self.page.get_by_role("textbox", name="Vehicle Value", exact=True),
            self.page.get_by_role("textbox", name="Vehicle Value", exact=False),
            self.page.get_by_role(
                "textbox", name="If this vehicle was sold today", exact=False
            ),
        ]
        for loc in candidates:
            n = await loc.count()
            for i in range(n):
                el = loc.nth(i)
                try:
                    if not await el.is_visible():
                        continue
                    await el.scroll_into_view_if_needed(timeout=2_000)
                    # verify=False: ExtJS formats the value with $ after Tab,
                    # so raw input_value won't match the plain "50000" we filled.
                    await self.safe_fill(el, default, verify=False)
                    # Wait for currency formatting to complete before Continue —
                    # Progressive silently rejects the vehicle save if ExtJS
                    # hasn't committed the model change yet (known 2026-06 bug).
                    await self.wait_for_currency_formatted(el)
                    actual = ""
                    try:
                        actual = (await el.input_value()).strip()
                    except Exception:
                        pass
                    if actual:
                        print(f"    [Progressive] Vehicle market value: ${actual}")
                        return
                    print(
                        f"    [Progressive] Vehicle Value fill didn't stick "
                        f"(input_value={actual!r}); trying next selector"
                    )
                except Exception as e:
                    print(f"    [Progressive] Vehicle Value selector failed: {e}")
                    continue
        print("    [Progressive] WARN: 'Vehicle Value' textbox not found / not filled")

    async def _click_continue(self) -> None:
        """Click Continue at the bottom (saves vehicle, returns to VehicleSummary).

        After clicking, check that the page advanced — if Progressive shows
        a validation banner ('Please take a look at the N item(s) below'),
        raise a clear error so the operator knows what's missing instead of
        marching forward into the next step blindly.

        BasePage.safe_click_continue handles blur → force click → JS dispatch
        → retry → URL verification against 'AddVehicle' token.
        """
        print("    [Progressive] Saving vehicle...")
        await self.safe_click_continue(expect_url_changes_from="AddVehicle")

        # Validation banner check — if we're somehow still here with a banner,
        # raise a clear error.
        banner = self.page.get_by_text(
            "Please take a look at the", exact=False
        )
        if await banner.count() > 0 and await banner.first.is_visible():
            try:
                full = (await banner.first.text_content()) or ""
            except Exception:
                full = "(could not read banner text)"
            await self.screenshot("vehicle_save_validation_error")
            raise RuntimeError(
                f"AddVehicle Continue did not advance — validation error on page: "
                f"{full.strip()[:300]}"
            )
