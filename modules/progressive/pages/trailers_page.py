"""
Trailer page for Progressive wizard.

STATUS: SKELETON — selectors marked as `TODO(Task 10)` pending live DIAG
dump from Task 9. Structure mirrors `vehicles_page.AddVehiclePage`; each
step has the same shape so Task 10's job is to confirm selectors against
the captured DOM rather than designing the page object from scratch.

Flow (assumed, to be confirmed by DIAG):
  VehicleSummary
    → "Add Trailer" / "Add Another Trailer" button
    → AddTrailer form (this module)
    → Continue → back to VehicleSummary

Conditional fields (assumed, to be confirmed):
  - Trailer Type combobox (Dry Van / Reefer / Flatbed / Dump / Tank / Gooseneck)
  - GVW combobox (may not be asked for trailers — confirm)
  - Loan/Lease radio reveals Comp/Coll question on "No"
  - Comp/Coll = Yes reveals Vehicle Value + "no equipment" checkbox
"""

from typing import Optional

from modules.progressive.choice_resolver import resolve_choice, Resolution
from modules.progressive.field_mapper import MappedVehicle
from modules.progressive.mappings import TRAILER_TILE_MAP
from modules.progressive.pages._exceptions import UnmappableValueError
from modules.progressive.pages.base_page import BasePage


class MostCommonTrailersPage(BasePage):
    """Intermediate tile picker shown after clicking 'Add Trailer'.

    URL: pageName=MostCommonTrailers (analogous to MostCommonVehicles).
    Live evidence (JUAREZ run): a "Most common trailers" tile picker with
    tiles: Dry Freight Trailer / Flatbed Trailer / Refrigerated Dry Freight /
    Gooseneck Trailer / Other / Not Listed. Mirrors MostCommonVehiclesPage
    exactly — fail-loud tile resolution, never a silent catch-all.
    """

    # Labels the tile-enumeration selector ([role=button]/button) also captures
    # — wizard nav tabs and summary action buttons — which are NOT trailer tiles.
    # Filtered out so a HALT diagnostic lists real tiles, not nav chrome.
    _NON_TILE_LABELS = frozenset(s.lower() for s in {
        "Quote Comments", "START", "VEHICLES", "DRIVERS", "BUSINESS", "RATES",
        "FINAL DETAILS", "PAYMENT", "COMPLETE", "Continue", "Edit", "Remove",
        "Back", "Save & Return Later",
    })

    async def _enumerate_tiles(self) -> list:
        """Read the trailer-type tile labels actually rendered on screen."""
        fallback = list(dict.fromkeys(TRAILER_TILE_MAP.values()))
        try:
            result = await self.page.evaluate(
                """() => Array.from(document.querySelectorAll(
                    '.x-btn-inner, [role=button], .tile, button'
                )).filter(el => el.offsetParent !== null)
                  .map(el => (el.innerText || '').trim())
                  .filter(t => t.length > 0)"""
            )
            if not isinstance(result, list):
                return fallback
            return [t for t in result if t.lower() not in self._NON_TILE_LABELS]
        except Exception:
            return fallback

    async def resolve_tile(self, trailer_type: str) -> Resolution:
        """Resolve the Blue-Quote trailer string to a tile actually on screen.
        Raises UnmappableValueError (HALT) instead of guessing a catch-all."""
        options = await self._enumerate_tiles()
        t = (trailer_type or "").upper()
        token = next((k for k in TRAILER_TILE_MAP if k in t), None)
        mapping = {trailer_type: TRAILER_TILE_MAP[token]} if token else None
        screenshot = await self.screenshot("trailer_tile_unmapped")
        res = resolve_choice(
            "Trailer tile", trailer_type, options,
            mapping=mapping, screenshot_path=screenshot,
        )
        if res.value not in options:
            raise UnmappableValueError(
                field="Trailer tile",
                source_value=trailer_type,
                available_options=list(options),
                screenshot_path=screenshot,
            )
        return res

    async def select_trailer_type(self, trailer_type: str) -> None:
        """Pick the most appropriate tile for the trailer string, or HALT."""
        res = await self.resolve_tile(trailer_type)
        print(f"    [Progressive] Selecting trailer type: {res.value} ({res.note})")
        tile = self.page.get_by_text(res.value, exact=True).first
        await tile.click(force=True)
        await self.wait_for_extjs_idle()


class AddTrailerPage(BasePage):
    """Add-Trailer form. URL token: pageName=AddTrailer (TODO confirm via DIAG).

    Fields (assumed, mirroring AddVehiclePage — confirm against DIAG dump):
      - "Add Trailer By" radio: "Year, Make, Model" | "VIN" (default VIN)
      - VIN textbox + "Lookup VIN" button
      - "Trailer Type" combobox (Dry Van / Reefer / Flatbed / Dump / Tank / Gooseneck …)
      - ZIP textbox (pre-filled from owner address; overwrite if different)
      - "Farthest one-way distance this trailer typically travels…" combobox
      - "What is the gross vehicle weight?" combobox (may not exist for trailers)
      - "Is there a loan/lease on this trailer?" radio: Yes-Loan | Yes-Lease | No
      - "Does the customer need Comprehensive or Collision coverage…" radio (post-loan)
      - "What is the total value of all permanently attached equipment…" radio
      - "Vehicle Value" / "Trailer Value" textbox (when Comp/Coll = Yes)
      - Continue button
    """

    REQUIRED_FIELDS = ("year", "make", "model", "vin")
    CONDITIONAL_FIELDS = ("vehicle_value", "vehicle_has_no_equipment")
    OPTIONAL_FIELDS = ("trailer_type", "garaging_zip", "gvw")

    def __init__(self, page):
        super().__init__(page)
        self.warnings: list[str] = []

    def _log_skipped(self, field: str, reason: str) -> None:
        msg = f"add_trailer: skipped '{field}' — {reason}"
        print(f"    [Progressive] {msg}")
        self.warnings.append(msg)

    async def fill_from_mapped(self, trailer: MappedVehicle) -> None:
        """Fill the AddTrailer form from a MappedVehicle and click Continue.

        Mirrors AddVehiclePage.fill_from_mapped step-for-step. APD conditional
        on trailer.value (same convention as PR-A for powered vehicles):
          - trailer.value set    → Comp/Coll = Yes + fill Vehicle Value
          - trailer.value None   → Comp/Coll = No (liability-only)
        """
        await self.page.wait_for_load_state("networkidle", timeout=30_000)

        # 1. VIN or Y/M/M entry
        # TODO(Task 10): confirm whether the VIN/YMM radio toggle exists.
        # The form may default to VIN directly without a radio (trailers
        # commonly skip the YMM cascade because VIN is mandatory in TX).
        if trailer.vin:
            await self._fill_by_vin(trailer.vin)
        else:
            await self._fill_by_ymm(trailer.year, trailer.make, trailer.model)

        # 2. Trailer Type combobox (likely required, even with VIN)
        # TODO(Task 10): confirm combobox label. Candidates from existing UI:
        #   - "Trailer Type"
        #   - "What type of trailer is this?"
        await self._set_trailer_type(trailer.trailer_type)

        # 3. ZIP override if different from pre-filled owner ZIP
        if trailer.garaging_zip:
            await self._set_zip(trailer.garaging_zip)

        # 4. Distance (may share the same combobox label as AddVehicle)
        # TODO(Task 10): confirm distance combobox exists on trailer form.
        await self._set_distance(trailer.radius_miles)

        # 5. GVW (may not be asked for trailers — call is no-op if combobox
        # not found, courtesy of _set_combobox_by_label's silent skip)
        # TODO(Task 10): confirm GVW combobox present.
        await self._set_combobox_by_label(
            "What is the gross vehicle weight?", trailer.gvw
        )

        # 6. Loan/Lease
        loan_label = {
            "Loan": "Yes - Loan",
            "Lease": "Yes - Lease",
            "No": "No",
        }.get(trailer.has_loan, "No")
        await self._set_radio("Is there a loan/lease on this", loan_label)

        # Wait for ExtJS to render conditional Comp/Coll question
        try:
            await self.wait_for_extjs_idle(timeout_ms=5_000)
        except Exception:
            pass
        await self.page.wait_for_timeout(600)

        # 7. APD conditional on trailer.value (mirrors AddVehicle PR-A behavior)
        if trailer.has_loan == "No":
            wants_apd = bool(trailer.value)
            apd_answer = "Yes" if wants_apd else "No"
            await self._set_radio(
                "Does the customer need Comprehensive or Collision coverage",
                apd_answer,
            )
            try:
                await self.wait_for_extjs_idle(timeout_ms=5_000)
            except Exception:
                pass
            await self.page.wait_for_timeout(800)

            if wants_apd:
                # TODO(Task 10): confirm checkbox + value textbox labels for
                # trailer form. May be identical to AddVehicle ("Vehicle Value"
                # + "Vehicle has no equipment") or trailer-specific
                # ("Trailer Value" + "Trailer has no equipment").
                await self._tick_no_equipment_checkbox()
                await self._fill_vehicle_value(default=trailer.value)
            else:
                print(
                    "    [Progressive] Trailer APD = No (Blue Quote has no "
                    "Value for this trailer); skipping equipment + Value section"
                )

        # 8. Continue
        await self._click_continue()

    # ---- VIN / YMM entry helpers ----

    async def _fill_by_vin(self, vin: str) -> None:
        """Enter VIN and trigger Lookup. Mirrors AddVehiclePage._fill_by_vin.

        TODO(Task 10): confirm the VIN textbox label. If different from
        AddVehicle's "Vehicle Identification Number (VIN)", update the
        get_by_role lookup.
        """
        print(f"    [Progressive] Adding trailer by VIN: {vin}")
        # VIN radio toggle (if present)
        vin_radio = self.page.get_by_role("radio", name="VIN", exact=True)
        if await vin_radio.count() > 0:
            try:
                await vin_radio.first.click(timeout=2_000)
            except Exception:
                pass

        # TODO(Task 10): confirm VIN textbox accessible name
        vin_box = self.page.get_by_role(
            "textbox", name="Vehicle Identification Number (VIN)"
        )
        # Could be pre-filled from suggestion — clear if needed
        try:
            current = await vin_box.first.input_value()
            if current and current != vin:
                clear_btn = self.page.get_by_role("button", name="Clear VIN")
                if await clear_btn.count() > 0:
                    await clear_btn.first.click()
                    await self.page.wait_for_timeout(500)
        except Exception:
            pass

        # verify=False because ExtJS may format VIN mid-stream (uppercase/mask)
        await self.safe_fill(vin_box.first, vin, verify=False)
        lookup_btn = self.page.get_by_role("button", name="Lookup VIN")
        if await lookup_btn.count() > 0:
            await lookup_btn.first.click(timeout=10_000)
            await self.page.wait_for_load_state("networkidle", timeout=20_000)
            await self.page.wait_for_timeout(1_500)

    async def _fill_by_ymm(
        self, year: Optional[int], make: Optional[str], model: Optional[str]
    ) -> None:
        """Fallback Year/Make/Model entry. Same fragility caveat as AddVehicle.

        Trailer Blue Quotes commonly have VIN; this path is best-effort only.
        """
        if not (year and make and model):
            print(
                f"    [Progressive] WARN: Y/M/M incomplete - "
                f"year={year} make={make} model={model}"
            )
            return
        print(
            f"    [Progressive] Adding trailer by Y/M/M (fragile path): "
            f"{year} {make} {model}"
        )
        ymm_radio = self.page.get_by_role("radio", name="Year, Make, Model")
        if await ymm_radio.count() > 0:
            await ymm_radio.first.click(timeout=2_000)
            await self.page.wait_for_timeout(500)

        await self.safe_select_combo(await self.find_combo("Year"), str(year))
        try:
            await self.page.keyboard.press("Tab")
            await self.page.wait_for_timeout(800)
        except Exception:
            pass
        await self.safe_select_combo(await self.find_combo("Make"), make)
        await self.safe_select_combo(await self.find_combo("Model"), model)

    # ---- Trailer-specific field helpers ----

    async def _set_trailer_type(self, trailer_type: Optional[str]) -> None:
        """Map Blue Quote trailer type string to Progressive combobox option.

        TODO(Task 10): confirm combobox label + option labels from DIAG.
        Mapping below is a best-guess based on Progressive's typical UI taxonomy.
        """
        if not trailer_type:
            self._log_skipped("trailer_type", "no value provided")
            return

        t = (trailer_type or "").upper()
        option_label = "Other / Not Listed"  # safe fallback
        if "GOOSENECK" in t:
            option_label = "Gooseneck"
        elif "DRY VAN" in t or "DRYVAN" in t:
            option_label = "Dry Van"
        elif "REEFER" in t or "REFRIGERAT" in t:
            option_label = "Refrigerated"
        elif "FLATBED" in t or "FLAT BED" in t:
            option_label = "Flatbed"
        elif "DUMP" in t:
            option_label = "Dump"
        elif "TANK" in t:
            option_label = "Tank"
        elif "LOWBOY" in t or "LOW BOY" in t:
            option_label = "Lowboy"
        elif "CAR HAULER" in t or "CARHAULER" in t:
            option_label = "Car Hauler"

        await self._set_combobox_by_label("Trailer Type", option_label)

    async def _set_zip(self, zip_code: str) -> None:
        """ZIP textbox helper. Same shape as AddVehicle.

        TODO(Task 10): confirm ZIP textbox accessible name. May be
        "Zip code where the trailer is located" instead of "vehicle".
        """
        zip_box = self.page.get_by_role(
            "textbox", name="Zip code where the vehicle is located"
        )
        if await zip_box.count() == 0:
            zip_box = self.page.get_by_role(
                "textbox", name="Zip code where the trailer is located"
            )
        if await zip_box.count() > 0:
            try:
                current = await zip_box.first.input_value()
            except Exception:
                current = ""
            if current != zip_code:
                await self.safe_fill(zip_box.first, zip_code, verify=False)

    async def _set_distance(self, radius_miles: str) -> None:
        """Distance combobox. Reuses AddVehicle's option labels.

        TODO(Task 10): confirm combobox exists on trailer form.
        """
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
            "Farthest one-way distance this", option
        )

    async def _set_combobox_by_label(self, label: str, option_text: str) -> None:
        """Generic ExtJS combobox helper. Silently no-ops if not found."""
        combo = await self.find_combo(label)
        if await combo.count() == 0:
            return
        try:
            await self.safe_select_combo(combo, option_text)
        except Exception as e:
            print(
                f"    [Progressive] WARN: combobox '{label}' = "
                f"'{option_text}' failed: {e}"
            )

    async def _set_radio(self, group_label: str, value: str) -> None:
        """Find radiogroup and pick value. Same shape as AddVehicle._set_radio."""
        group = await self.find_radiogroup(group_label)
        if not await self.field_exists(group, wait_ms=2_500):
            print(
                f"    [Progressive] _set_radio: '{group_label}' "
                f"not visible (skipped)"
            )
            return
        try:
            await self.safe_radio(group, value)
            print(f"    [Progressive] _set_radio: '{group_label}' = '{value}'")
        except Exception as e:
            print(
                f"    [Progressive] WARN: radio '{group_label}' = "
                f"'{value}' failed: {e}"
            )

    # ---- APD / Value / Equipment helpers ----

    async def _tick_no_equipment_checkbox(self) -> None:
        """Tick 'Vehicle has no equipment' checkbox.

        TODO(Task 10): confirm checkbox label. May be trailer-specific:
        "Trailer has no equipment".
        """
        cb = self.page.get_by_role("checkbox", name="Vehicle has no equipment")
        if await cb.count() == 0:
            cb = self.page.get_by_role(
                "checkbox", name="Trailer has no equipment"
            )
        if await self.field_exists(cb, wait_ms=1500):
            try:
                await self.safe_checkbox(cb, check=True)
                print(
                    "    [Progressive] Equipment value: ticked "
                    "'has no equipment'"
                )
            except Exception as e:
                print(
                    f"    [Progressive] WARN: 'has no equipment' "
                    f"click failed: {e}"
                )
        else:
            self._log_skipped("vehicle_has_no_equipment", "field_not_rendered")

    async def _fill_vehicle_value(self, default: str = "25000") -> None:
        """Fill the Trailer/Vehicle Value textbox.

        TODO(Task 10): confirm placeholder/aria name. Likely "Trailer Value"
        or "Vehicle Value" placeholder.
        """
        try:
            await self.wait_for_extjs_idle(timeout_ms=5_000)
        except Exception:
            pass
        await self.page.wait_for_timeout(600)
        candidates = [
            self.page.locator('input[placeholder="Trailer Value"]'),
            self.page.locator('input[placeholder="Vehicle Value"]'),
            self.page.get_by_role("textbox", name="Trailer Value", exact=True),
            self.page.get_by_role("textbox", name="Vehicle Value", exact=True),
            self.page.get_by_role(
                "textbox", name="If this trailer was sold today", exact=False
            ),
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
                    await self.safe_fill(el, default, verify=False)
                    await self.wait_for_currency_formatted(el)
                    actual = ""
                    try:
                        actual = (await el.input_value()).strip()
                    except Exception:
                        pass
                    if actual:
                        print(f"    [Progressive] Trailer value: ${actual}")
                        return
                except Exception as e:
                    print(
                        f"    [Progressive] Trailer Value selector failed: {e}"
                    )
                    continue
        print(
            "    [Progressive] WARN: 'Trailer Value' textbox "
            "not found / not filled"
        )

    async def _click_continue(self) -> None:
        """Save trailer and verify URL advances off AddTrailer.

        TODO(Task 10): confirm URL token. May be 'AddTrailer' or share the
        AddVehicle token.
        """
        print("    [Progressive] Saving trailer...")
        await self.safe_click_continue(expect_url_changes_from="AddTrailer")

        # Validation banner check
        banner = self.page.get_by_text(
            "Please take a look at the", exact=False
        )
        if await banner.count() > 0 and await banner.first.is_visible():
            try:
                full = (await banner.first.text_content()) or ""
            except Exception:
                full = "(could not read banner text)"
            await self.screenshot("trailer_save_validation_error")
            raise RuntimeError(
                f"AddTrailer Continue did not advance — validation error: "
                f"{full.strip()[:300]}"
            )
