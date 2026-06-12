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
from modules.geico.pages.base_page import BasePage, _flex_text_regex


# Find the Annual Mileage <select> (revealed for some vehicle/class combos;
# REQUIRED when present — live NUNEZ 2026-06-11). '1-4000' is its
# distinctive first bucket.
_JS_READ_ANNUAL_MILEAGE = """
    () => {
        const sel = Array.from(document.querySelectorAll('select')).find(s =>
            !s.disabled && Array.from(s.options)
                .some(o => (o.text || '').includes('1-4000')));
        if (!sel) return null;
        return {
            value: sel.value,
            texts: Array.from(sel.options)
                .map(o => (o.text || '').trim()).filter(t => t),
        };
    }
"""


# Signature lists used to locate the right native <select> when ids are dynamic.
# Each list MUST contain option texts that uniquely identify the target combobox.
_DISTANCE_OPTIONS_SIGNATURE = ["0-25", "More than 500"]
_VEHICLE_TYPE_OPTIONS_SIGNATURE = ["Dump Truck", "Tractor", "Pickup Truck"]

# Canonical order of GEICO's one-way-distance buckets. Pickups expose a
# TRIMMED set (starts at '101-200' — live ON THE GO 2026-06-11), so the
# desired bucket may be absent and the nearest at-or-above must be used.
_DISTANCE_ORDER = ["0-25", "26-50", "51-100", "101-200", "201-300",
                   "301-500", "More than 500"]


def nearest_distance_option(desired: str, options: list) -> str:
    """The desired bucket when available; otherwise the nearest available
    bucket at-or-above it; otherwise the first real option."""
    real = [o for o in options if o and "select" not in o.lower()]
    if desired in real:
        return desired
    try:
        start = _DISTANCE_ORDER.index(desired)
    except ValueError:
        start = 0
        if desired not in _DISTANCE_ORDER:
            return real[0] if real else desired
    for bucket in _DISTANCE_ORDER[start:]:
        if bucket in real:
            return bucket
    return real[-1] if real else desired


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

        # The entry form for vehicle N>1 mounts a beat AFTER add_another's
        # networkidle (live DDH 8-vehicle 2026-06-11: the VIN-handy radio
        # read unchecked because its group wasn't hydrated yet). Wait for the
        # VIN-handy question to be VISIBLE before touching it.
        vin_q = self.page.locator("gds-radio-button-group").filter(
            has_text=_flex_text_regex("have it handy")
        ).filter(visible=True)
        if not await self.field_exists(vin_q, wait_ms=20_000):
            self.note_warning(
                "vehicle entry form's VIN-handy question never became "
                "visible — proceeding (click_question_radio will retry)"
            )

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
                except Exception as e:
                    self.note_warning(f"Vehicle Type select failed: {e}")

        # 3b. VIN-decoded PICKUPS leave the Vehicle Type EMPTY and required
        # ('Which of the following best describes...' — live ON THE GO
        # 2026-06-11); tractors arrive pre-selected. Fill from the BlueQuote
        # type when the decode didn't pick one.
        if vehicle.vin and vehicle.vehicle_type:
            try:
                type_empty = await self.page.evaluate(
                    """() => {
                        const sel = Array.from(document.querySelectorAll('select'))
                            .find(s => (s.id || '').includes('OtherVehicleType'));
                        return sel ? (!sel.value || sel.value === '') : false;
                    }"""
                )
                if type_empty:
                    print(f"    [GEICO] Step 3: Vehicle Type empty post-decode "
                          f"-> {vehicle.vehicle_type}")
                    await self.select_by_js(
                        "OtherVehicleType", vehicle.vehicle_type
                    )
            except Exception as e:
                self.note_warning(f"post-decode Vehicle Type set failed: {e}")

        # 4. Garaging address is auto-populated; leave it.

        # 5. Farthest one-way distance combobox (id-stable across variants;
        # the option SET differs per vehicle type, so pick the nearest
        # available bucket when the desired one is absent).
        await self._set_distance(vehicle)

        # 6. Radio "Is this vehicle ever used for personal use?"
        await self.click_question_radio(
            "ever used for personal use",
            "Yes" if vehicle.has_personal_use else "No",
        )

        # 6a. Conditional (pickup variant, live ON THE GO 2026-06-11):
        # "Does the customer have any customizations?" -> No.
        try:
            grp = self.page.locator("gds-radio-button-group").filter(
                has_text=_flex_text_regex("have any customizations")
            )
            if await self.field_exists(grp, wait_ms=1_500):
                print("    [GEICO] Step 3: customizations -> No")
                await self.click_question_radio("have any customizations", "No")
        except Exception as e:
            self.note_warning(f"customizations radio failed: {e}")

        # 6b. Conditional (live NUNEZ 2026-06-11): "Was the customer's
        # vehicle purchased in the last 45 days?" — fleet units on a
        # BlueQuote are existing vehicles; default No.
        try:
            grp = self.page.locator("gds-radio-button-group").filter(
                has_text=_flex_text_regex("purchased in the last 45 days")
            )
            if await self.field_exists(grp, wait_ms=1_500):
                print("    [GEICO] Step 3: purchased in last 45 days -> No")
                await self.click_question_radio(
                    "purchased in the last 45 days", "No"
                )
        except Exception as e:
            self.note_warning(f"purchased-45-days radio failed: {e}")

        # 6c. Conditional: Annual Mileage (REQUIRED when revealed; the
        # BlueQuote carries no per-vehicle mileage).
        await self._fill_annual_mileage_if_present(vehicle)

        # 6d. Comp/coll can be MERGED into this form (live SOLANO/NUNEZ
        # 2026-06-11 — the standalone sub-page no longer always exists).
        # Answer it here when present; CompCollSubPage then no-ops.
        try:
            grp = self.page.locator("gds-radio-button-group").filter(
                has_text=_flex_text_regex("comprehensive or collision coverage")
            )
            if await self.field_exists(grp, wait_ms=1_500):
                print(
                    f"    [GEICO] Step 3: comp/coll (merged form) -> "
                    f"{'Yes' if vehicle.has_comp_coll else 'No'}"
                )
                await self.click_question_radio(
                    "comprehensive or collision coverage",
                    "Yes" if vehicle.has_comp_coll else "No",
                )
        except Exception as e:
            self.note_warning(f"merged comp/coll radio failed: {e}")

        # 7. Re-verify required selects JUST BEFORE Next: a late decode
        # re-render can wipe values committed earlier (live SOLANO
        # validation 2026-06-11: distance read back '51-100' at set time,
        # was '' at submit — the DCT lesson).
        await self._ensure_entry_required_filled(vehicle)

        # 8. Click Next (with one refill+retry cycle if validation blocks).
        print("    [GEICO] Step 3: submitting vehicle entry...")
        await self._click_next(vehicle)

    async def _fill_annual_mileage_if_present(self, vehicle: MappedVehicle) -> None:
        """Fill the Annual Mileage <select> when GEICO reveals it.

        The BlueQuote has no per-vehicle annual mileage. Heuristic: long
        radius (201+ mi one-way) -> the highest bucket; otherwise a middle
        bucket. Always surfaced as a warning so a human can review."""
        try:
            state = await self.page.evaluate(_JS_READ_ANNUAL_MILEAGE)
        except Exception:
            return
        if not isinstance(state, dict):
            return  # select absent (JS returned null/unexpected payload)
        if state.get("value"):
            return  # pre-filled — leave it
        texts = [
            t for t in state.get("texts", [])
            if t and "select" not in t.lower()
        ]
        if not texts:
            return
        long_haul = vehicle.one_way_distance in (
            "201-300", "301-500", "More than 500"
        )
        choice = texts[-1] if long_haul else texts[len(texts) // 2]
        self.note_warning(
            f"Annual Mileage defaulted to {choice!r} (radius "
            f"{vehicle.one_way_distance!r}; BlueQuote carries none — review)"
        )
        await self.select_by_options_signature(["1-4000"], choice)

    async def _fill_vin_and_decode(self, vin: str) -> None:
        """Fill the VIN and wait for GEICO's server-side decode BY CONDITION
        (the Year <select> gets a value) instead of a blind 3s sleep.

        VIN input variants seen live: accessible name 'Vehicle Identification
        Number' (HUMBERTO/NUNEZ) vs id GiveVinPreQuote with aria-label 'vin'
        and a dashed placeholder (SOLANO 2026-06-11).
        """
        print(f"    [GEICO] Step 3: filling VIN {vin} (waiting for decode)...")
        vin_box = self.page.get_by_role(
            "textbox", name="Vehicle Identification Number"
        )
        if await vin_box.count() == 0:
            vin_box = self.page.locator('[id*="GiveVinPreQuote"]')
        if await vin_box.count() == 0:
            # Last resort: any textbox whose accessible name mentions VIN.
            vin_box = self.page.get_by_label("VIN", exact=False)
        await vin_box.first.wait_for(state="visible", timeout=10_000)
        await vin_box.first.fill(vin)
        # Some forms validate on blur; commit the value then wait for decode.
        try:
            await vin_box.first.press("Tab")
        except Exception:
            pass
        # Condition-based decode wait: Year auto-populates when the decode
        # round-trip lands (observable signal). Budget is a cap, not a sleep.
        try:
            await self.page.wait_for_function(
                """() => {
                    const sel = Array.from(document.querySelectorAll('select'))
                        .find(s => (s.id || '').includes('GiveYear'));
                    return sel && sel.value && sel.value !== '';
                }""",
                timeout=25_000,
            )
        except Exception:
            self.note_warning(
                f"VIN decode did not populate Year within 25s (VIN {vin}) — "
                f"continuing; Vehicle Type may need manual override"
            )

    async def _set_distance(self, vehicle: MappedVehicle) -> None:
        """Set the one-way distance via its id-stable select. When the
        desired bucket is absent from this variant's option set, fall back
        to the nearest available bucket at-or-above (warned)."""
        from modules.geico.pages._exceptions import SelectVerifyError
        desired = vehicle.one_way_distance
        print(f"    [GEICO] Step 3: one-way distance -> {desired}")
        try:
            await self.select_by_js("FarthestOneWayDistance", desired)
            return
        except SelectVerifyError as e:
            pick = nearest_distance_option(desired, e.available_options)
            if pick != desired:
                self.note_warning(
                    f"distance {desired!r} unavailable for this vehicle "
                    f"type — using nearest bucket {pick!r}"
                )
                try:
                    await self.select_by_js("FarthestOneWayDistance", pick)
                    return
                except Exception as e2:
                    self.note_warning(f"distance fallback failed: {e2}")
            else:
                self.note_warning(f"distance select failed: {e}")
        except Exception as e:
            self.note_warning(f"distance select failed: {e}")

    async def _ensure_entry_required_filled(self, vehicle: MappedVehicle) -> None:
        """Generic pre-Next sweep: every VISIBLE empty <select> on the entry
        form gets filled — late decode re-renders wipe committed values and
        vehicle-type variants reveal selects we have no mapping for (live
        2026-06-11: distance reset on SOLANO; TypeOfTrailerHitch revealed
        for pickups on ON THE GO). Known ids get their proper value; unknown
        ones get the first real option WITH a warning (fail-soft + review).
        """
        try:
            empty = await self.page.evaluate(
                """() => Array.from(document.querySelectorAll('select'))
                    .filter(s => s.offsetParent !== null && !s.disabled
                                 && (!s.value || s.value === ''))
                    .map(s => ({
                        id: s.id || '',
                        options: Array.from(s.options)
                            .map(o => (o.text || '').trim())
                            .filter(t => t),
                    }))"""
            )
        except Exception:
            empty = []
        if not isinstance(empty, list):
            return

        for sel in empty:
            sid = sel.get("id", "")
            try:
                if "FarthestOneWayDistance" in sid:
                    self.note_warning(
                        f"distance empty at submit — refilling "
                        f"{vehicle.one_way_distance!r}"
                    )
                    await self._set_distance(vehicle)
                elif "OtherVehicleType" in sid and vehicle.vehicle_type:
                    self.note_warning(
                        f"vehicle type empty at submit — setting "
                        f"{vehicle.vehicle_type!r}"
                    )
                    await self.select_by_js(
                        "OtherVehicleType", vehicle.vehicle_type
                    )
                elif "TypeOfTrailerHitch" in sid:
                    # Pickup conditional (ON THE GO 2026-06-11). BlueQuotes
                    # carry no hitch info; 'None' is the safe default.
                    print("    [GEICO] Step 3: trailer hitch -> None")
                    await self.select_by_js("TypeOfTrailerHitch", "None")
                elif "AnnualMileage" in sid:
                    await self._fill_annual_mileage_if_present(vehicle)
                else:
                    real = [o for o in sel.get("options", [])
                            if "select" not in o.lower()]
                    if not real:
                        continue
                    self.note_warning(
                        f"unmapped required select {sid!r} — defaulting to "
                        f"{real[0]!r} (review)"
                    )
                    await self.select_by_js(
                        sid.split("_")[1] if "_" in sid else sid, real[0]
                    )
            except Exception as e:
                self.note_warning(f"sweep fill for {sid!r} failed: {e}")

    async def _click_next(self, vehicle: MappedVehicle) -> None:
        """Click the Next button at the bottom of the entry form.

        click_button targets the LAST visible Next (the top one is inert —
        live NUNEZ 2026-06-11). After the click, a visible validation banner
        means the submit was REFUSED: refill the required selects once and
        retry; if still blocked, fail fast with the banner text instead of
        timing out downstream."""
        for attempt in (1, 2):
            await self.remove_overlays()
            await self.click_button("Next")
            await self.page.wait_for_load_state("networkidle", timeout=30_000)
            try:
                blocker = await self.page.evaluate(
                    """() => {
                        const err = Array.from(document.querySelectorAll(
                            '[class*="error" i], [role="alert"]'
                        )).filter(el => el.offsetParent !== null)
                         .map(el => (el.innerText || '').trim())
                         .find(t => /make a selection|is required/i.test(t));
                        return err || null;
                    }"""
                )
            except Exception:
                blocker = None
            if not blocker:
                return
            if attempt == 1:
                self.note_warning(
                    f"vehicle entry submit refused ({blocker!r}) — "
                    f"refilling required selects and retrying"
                )
                await self._ensure_entry_required_filled(vehicle)
            else:
                await self.screenshot("step3_entry_submit_refused")
                raise RuntimeError(
                    f"Vehicle entry submit refused by validation after "
                    f"refill: {blocker!r}"
                )


class CompCollSubPage(BasePage):
    """The 'Tell us more about your {YEAR} {MAKE} {MODEL}.' page.

    Single question: whether to add comprehensive/collision coverage.
    Auto-appears after `VehicleEntryPage.fill_and_submit()`.
    """

    async def answer(self, want_comp_coll: bool) -> None:
        """Pick Yes/No on the comp/coll radio and click Next.

        NO-OP when the standalone sub-page doesn't exist: comp/coll is
        merged into the entry form on current builds (live SOLANO/NUNEZ
        2026-06-11) and the entry page already answered it — by now the
        wizard is on the Vehicle Summary, where clicking 'Next' would fail.
        """
        await self.page.wait_for_load_state("networkidle", timeout=30_000)

        grp = self.page.locator("gds-radio-button-group").filter(
            has_text=_flex_text_regex("comprehensive or collision coverage")
        )
        if not await self.field_exists(grp, wait_ms=2_000):
            print(
                "    [GEICO] Step 3: comp/coll sub-page absent "
                "(merged into the entry form) — skipping"
            )
            return

        print(
            f"    [GEICO] Step 3: comp/coll answer -> "
            f"{'Yes' if want_comp_coll else 'No'}"
        )
        try:
            await self.click_question_radio(
                "comprehensive or collision coverage",
                "Yes" if want_comp_coll else "No",
            )
        except Exception as e:
            self.note_warning(f"comp/coll radio click failed: {e}")

        await self.remove_overlays()
        # Last visible Next (two on the page; the top one is inert).
        await self.click_button("Next")
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

        # The summary mounts a beat AFTER the entry submit settles — wait
        # for its marker before hunting the add control (live DDH
        # 2026-06-11: an instant count()==0 raised while the entry form was
        # still on screen).
        try:
            await self.page.locator("gds-button").filter(
                has_text="Looks Good"
            ).last.wait_for(state="visible", timeout=30_000)
        except Exception:
            pass

        # Live SOLANO 2026-06-11: the add control is a plain
        # <li class="add-state"> WITHOUT role=listitem.
        for locator in (
            self.page.locator('li.add-state', has_text="Add Vehicle or Trailer"),
            self.page.locator('[role="listitem"]:has-text("Add Vehicle or Trailer")'),
            self.page.get_by_text("Add Vehicle or Trailer", exact=False),
        ):
            try:
                if not await self.field_exists(locator, wait_ms=3_000):
                    continue
                await locator.first.click(timeout=10_000)
                await self.page.wait_for_load_state(
                    "networkidle", timeout=30_000
                )
                return
            except Exception:
                continue
        await self.screenshot("step3_add_vehicle_control_missing")
        raise RuntimeError(
            "VehicleSummaryPage.add_another: no 'Add Vehicle or Trailer' "
            "control found (li.add-state / listitem / text)"
        )

    async def click_looks_good(self) -> None:
        """Click 'Looks Good' and wait for Step 4 ('Drivers & Incidents')."""
        print("    [GEICO] Step 3: clicking 'Looks Good' to advance to Step 4...")
        await self.page.wait_for_load_state("networkidle", timeout=30_000)
        await self.remove_overlays()

        # The summary mounts a beat after the entry submit settles — wait
        # for its marker before clicking (live YKZ 2026-06-11: the click
        # ran with the entry form still on screen).
        await self.page.locator("gds-button").filter(
            has_text="Looks Good"
        ).last.wait_for(state="visible", timeout=30_000)

        await self.click_button("Looks Good")

        # Dynamic outcome wait: drivers title (instant on success),
        # validation/server-error fail fast; 60s only as worst-case cap.
        await self.wait_for_step_outcome(
            ["Drivers & Incidents"], budget_ms=60_000
        )
        print("    [GEICO] Step 3: reached Step 4 (Drivers & Incidents).")
