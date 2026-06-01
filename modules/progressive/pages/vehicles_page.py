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

        candidates = [
            self.page.get_by_role("button", name="Add Vehicle"),
            self.page.get_by_role("button", name="Add a Vehicle"),
            self.page.get_by_role("button", name="Add vehicle", exact=False),
            self.page.get_by_role("link", name="Add Vehicle", exact=False),
            self.page.get_by_role("button", name="Add another vehicle", exact=False),
        ]
        for loc in candidates:
            n = await loc.count()
            for i in range(n):
                el = loc.nth(i)
                try:
                    if await el.is_visible():
                        await el.scroll_into_view_if_needed(timeout=3_000)
                        await el.click(timeout=10_000)
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
        """Click Continue to proceed to the Drivers page."""
        print("    [Progressive] Continuing to DRIVERS...")
        btn = self.page.get_by_role("button", name="Continue").last
        await btn.click(timeout=10_000)
        await self.page.wait_for_load_state("networkidle", timeout=60_000)


class MostCommonVehiclesPage(BasePage):
    """Intermediate page with 6 vehicle-type buttons.

    URL: pageName=MostCommonVehicles
    """

    async def select_vehicle_type(self, trailer_type: str) -> None:
        """Pick the most appropriate type for the trailer string."""
        label = self._map_to_button(trailer_type)
        print(f"    [Progressive] Selecting vehicle type: {label}")
        btn = self.page.get_by_role("button", name=label, exact=True)
        await btn.click(timeout=10_000)
        await self.page.wait_for_load_state("networkidle", timeout=30_000)

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
        await self.page.wait_for_timeout(800)

        # Comp/Coll question appears when loan=No
        if vehicle.has_loan == "No":
            await self._set_radio(
                "Does the customer need Comprehensive or Collision coverage",
                "Yes",  # default Yes for accurate quote
            )
            await self.page.wait_for_timeout(800)
            # Equipment value (required when Comp/Coll=Yes)
            await self._set_radio(
                "What is the total value of all permanently attached equipment",
                "$0 to $2,000",
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

        await vin_box.first.fill(vin)
        lookup_btn = self.page.get_by_role("button", name="Lookup VIN")
        if await lookup_btn.count() > 0:
            await lookup_btn.first.click(timeout=10_000)
            await self.page.wait_for_load_state("networkidle", timeout=20_000)
            await self.page.wait_for_timeout(1_500)

    async def _fill_by_ymm(
        self, year: Optional[int], make: Optional[str], model: Optional[str]
    ) -> None:
        """Use Year/Make/Model entry (cascading comboboxes)."""
        if not (year and make and model):
            print(f"    [Progressive] WARN: Y/M/M incomplete - year={year} make={make} model={model}")
            return
        print(f"    [Progressive] Adding by Y/M/M: {year} {make} {model}")
        ymm_radio = self.page.get_by_role("radio", name="Year, Make, Model")
        if await ymm_radio.count() > 0:
            await ymm_radio.first.click(timeout=2_000)
            await self.page.wait_for_timeout(500)

        await self._set_combobox_by_label("Year", str(year))
        await self._set_combobox_by_label("Make", make)
        await self._set_combobox_by_label("Model", model)

    async def _handle_vehicle_type_mismatch(self, trailer_type: Optional[str]) -> None:
        """If a 'Vehicle Type' combobox appeared (VIN didn't match selected type),
        pick the best option."""
        combo = self.page.get_by_role("combobox", name="Vehicle Type")
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
        suv_combo = self.page.get_by_role("combobox", name="What type of SUV is this?")
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
                await zip_box.first.fill(zip_code)
                await self.page.keyboard.press("Tab")
                await self.page.wait_for_timeout(800)

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
        """Generic helper for Sencha ExtJS comboboxes."""
        combo = self.page.get_by_role("combobox", name=label, exact=False)
        if await combo.count() == 0:
            return
        try:
            await combo.first.click(timeout=5_000)
            await self.page.wait_for_timeout(500)
            opt = self.page.get_by_role("option", name=option_text, exact=False).first
            if await opt.count() > 0:
                await opt.click(timeout=5_000)
                await self.page.wait_for_timeout(500)
        except Exception as e:
            print(f"    [Progressive] WARN: combobox '{label}' = '{option_text}' failed: {e}")

    async def _set_radio(self, group_label: str, value: str) -> None:
        group = self.page.get_by_role("radiogroup", name=group_label, exact=False)
        if await group.count() == 0:
            return
        try:
            await group.get_by_role("radio", name=value, exact=True).click(timeout=5_000)
            await self.page.wait_for_timeout(300)
        except Exception as e:
            print(f"    [Progressive] WARN: radio '{group_label}' = '{value}' failed: {e}")

    async def _click_continue(self) -> None:
        """Click Continue at the bottom (saves vehicle, returns to VehicleSummary)."""
        print("    [Progressive] Saving vehicle...")
        btn = self.page.get_by_role("button", name="Continue").last
        await btn.click(timeout=10_000)
        await self.page.wait_for_load_state("networkidle", timeout=30_000)
        await self.page.wait_for_timeout(1_500)
