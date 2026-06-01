"""
Vehicle pages for the GEICO wizard (Step 3).

Step 3 is internally three sub-pages that the wizard cycles per vehicle:

  VehicleEntryPage         -> "Tell us about the vehicle"  (VIN / Y/M/M form)
  CompCollSubPage          -> "Tell us more about your {YEAR} {MAKE} {MODEL}."
                              (single comp/coll Yes/No radio)
  VehicleSummaryPage       -> "Vehicles and Trailers" summary listing
                              vehicles + "Add Vehicle or Trailer" + "Looks Good".

Selectors / quirks validated live (see docs/Proceso GEICO.md "Step 3: Vehicles"):

  - VIN decode auto-populates Year / Make / Model and REORDERS the Vehicle Type
    combobox options so the decoded type lands first. Rule 4: VIN decode wins;
    we only override Vehicle Type when there is no VIN.
  - Farthest one-way distance is a native <select> with stable option labels
    (`0-25`, `26-50`, ..., `More than 500`). Use `select_by_options_signature`.
    Plain `select_option` sometimes fails silently for these custom widgets.
  - The "personal use" radio lives inside shadow DOM. The clickable proxy has
    an id like `<root>-ForPersonalUseYes-shadow` /
    `<root>-ForPersonalUseNo-shadow`. We locate by id-substring.
  - Garaging address is pre-populated from owner address; we leave it alone
    (Block 2 spec).
  - The "Add Vehicle or Trailer" entry on the summary is a list item, not a
    button. We click by visible text.
  - After "Looks Good" the page title changes to "Drivers & Incidents".

This file mirrors the multi-class layout of
`modules/progressive/pages/vehicles_page.py` so `quote_flow._add_all_vehicles`
can loop in the same way: entry -> comp/coll -> summary -> (add another | done).
"""

from playwright.async_api import Page

from modules.geico.field_mapper import MappedVehicle
from modules.geico.pages.base_page import BasePage


# Signature lists used to locate the right native <select> when ids are dynamic.
# Each list MUST contain option texts that uniquely identify the target combobox.
_DISTANCE_OPTIONS_SIGNATURE = ["0-25", "More than 500"]
_VEHICLE_TYPE_OPTIONS_SIGNATURE = ["Dump Truck", "Tractor", "Pickup Truck"]


class VehicleEntryPage(BasePage):
    """The 'Tell us about the vehicle' page with the VIN entry form.

    Auto-appears at start of Step 3 and again after each
    `VehicleSummaryPage.add_another()`.
    """

    async def fill_and_submit(self, vehicle: MappedVehicle) -> None:
        """Fill the vehicle-entry form and click Next.

        Steps follow docs/Proceso GEICO.md Step 3 sub-page 1.
        """
        print("    [GEICO] Step 3: filling vehicle entry form...")
        await self.page.wait_for_load_state("networkidle", timeout=30_000)

        # 1. Radio "Do you have VIN handy?"
        if vehicle.vin:
            await self.click_question_radio("Do you have it handy", "Yes")
            # 2. VIN textbox appears.
            await self._fill_vin_and_decode(vehicle.vin)
            # 3. Vehicle Type: VIN decode wins. Do NOT override.
        else:
            await self.click_question_radio("have the VIN handy", "No")
            # 3. With no VIN we must set Vehicle Type explicitly (if known).
            if vehicle.vehicle_type:
                print(
                    f"    [GEICO] Step 3: setting Vehicle Type "
                    f"(no VIN) -> {vehicle.vehicle_type}"
                )
                try:
                    await self.select_by_options_signature(
                        _VEHICLE_TYPE_OPTIONS_SIGNATURE,
                        vehicle.vehicle_type,
                    )
                except RuntimeError as e:
                    print(f"    [GEICO] WARN: Vehicle Type select failed: {e}")

        # 4. Garaging address is auto-populated; leave it.

        # 5. Farthest one-way distance combobox.
        print(
            f"    [GEICO] Step 3: one-way distance -> {vehicle.one_way_distance}"
        )
        try:
            await self.select_by_options_signature(
                _DISTANCE_OPTIONS_SIGNATURE,
                vehicle.one_way_distance,
            )
        except RuntimeError as e:
            print(f"    [GEICO] WARN: distance select failed: {e}")

        # 6. Radio "Is this vehicle ever used for personal use?"
        await self.click_question_radio(
            "ever used for personal use",
            "Yes" if vehicle.has_personal_use else "No",
        )

        # 7. Click Next.
        print("    [GEICO] Step 3: submitting vehicle entry...")
        await self._click_next()

    async def _fill_vin_and_decode(self, vin: str) -> None:
        """Fill VIN textbox and wait 3 s for GEICO's server-side decode.

        After decode, Year/Make/Model auto-populate and the Vehicle Type
        combobox options reorder, surfacing the decoded type first.
        """
        print(f"    [GEICO] Step 3: filling VIN {vin} (waiting for decode)...")
        vin_box = self.page.get_by_role(
            "textbox", name="Vehicle Identification Number"
        )
        if await vin_box.count() == 0:
            # Fallback: any textbox whose accessible name mentions VIN.
            vin_box = self.page.get_by_label("VIN", exact=False)
        await vin_box.first.wait_for(state="visible", timeout=10_000)
        await vin_box.first.fill(vin)
        # Some forms validate on blur; commit the value then wait for decode.
        try:
            await vin_box.first.press("Tab")
        except Exception:
            pass
        # 3-second hold for the VIN decode round-trip (Y/M/M auto-pop +
        # Vehicle Type combobox reorder with decoded type pre-selected).
        await self.page.wait_for_timeout(3_000)

    async def _click_next(self) -> None:
        """Click the Next button at the bottom of the entry form."""
        await self.remove_overlays()
        btn = self.page.get_by_role("button", name="Next")
        await btn.first.click(timeout=10_000)
        await self.page.wait_for_load_state("networkidle", timeout=30_000)


class CompCollSubPage(BasePage):
    """The 'Tell us more about your {YEAR} {MAKE} {MODEL}.' page.

    Single question: whether to add comprehensive/collision coverage.
    Auto-appears after `VehicleEntryPage.fill_and_submit()`.
    """

    async def answer(self, want_comp_coll: bool) -> None:
        """Pick Yes/No on the comp/coll radio and click Next."""
        print(
            f"    [GEICO] Step 3: comp/coll answer -> "
            f"{'Yes' if want_comp_coll else 'No'}"
        )
        await self.page.wait_for_load_state("networkidle", timeout=30_000)

        try:
            await self.click_question_radio(
                "comprehensive or collision coverage",
                "Yes" if want_comp_coll else "No",
            )
        except Exception as e:
            print(f"    [GEICO] WARN: comp/coll radio click failed: {e}")

        await self.remove_overlays()
        next_btn = self.page.get_by_role("button", name="Next")
        await next_btn.first.click(timeout=10_000)
        await self.page.wait_for_load_state("networkidle", timeout=30_000)


class VehicleSummaryPage(BasePage):
    """The 'Vehicles and Trailers' summary page.

    Lists vehicles added so far plus an "Add Vehicle or Trailer" list item
    (NOT a button) and a "Looks Good" button.
    """

    async def add_another(self) -> None:
        """Click 'Add Vehicle or Trailer' to start another vehicle entry."""
        print("    [GEICO] Step 3: adding another vehicle...")
        await self.page.wait_for_load_state("networkidle", timeout=30_000)
        await self.remove_overlays()

        # Live confirmed: it renders as a listitem with that visible text.
        listitem = self.page.locator(
            '[role="listitem"]:has-text("Add Vehicle or Trailer")'
        ).first
        if await listitem.count() > 0:
            try:
                await listitem.click(timeout=10_000)
                await self.page.wait_for_load_state(
                    "networkidle", timeout=30_000
                )
                return
            except Exception:
                pass

        # Fallback: plain text click.
        await self.page.get_by_text(
            "Add Vehicle or Trailer", exact=False
        ).first.click(timeout=10_000)
        await self.page.wait_for_load_state("networkidle", timeout=30_000)

    async def click_looks_good(self) -> None:
        """Click 'Looks Good' and wait for Step 4 ('Drivers & Incidents')."""
        print("    [GEICO] Step 3: clicking 'Looks Good' to advance to Step 4...")
        await self.page.wait_for_load_state("networkidle", timeout=30_000)
        await self.remove_overlays()

        # Capture the current step title BEFORE clicking so we can wait for it
        # to actually flip. "Drivers & Incidents" also lives in the persistent
        # step side-nav, so wait_for_text would match the breadcrumb instantly
        # and leave us driving the previous step's (stale) DOM — which broke the
        # owner-placeholder sub-page intermittently.
        prev_title = await self.page.title()

        btn = self.page.get_by_role("button", name="Looks Good")
        await btn.first.click(timeout=10_000)

        # Wait for the wizard's document.title to change away from the vehicles
        # step — the reliable signal that the drivers content has mounted.
        try:
            await self.wait_for_title_change(prev_title, timeout=30_000)
        except Exception:
            # As a softer fallback, just wait for the network to settle.
            await self.page.wait_for_load_state("networkidle", timeout=30_000)
        print("    [GEICO] Step 3: reached Step 4 (Drivers & Incidents).")
