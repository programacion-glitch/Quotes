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
from modules.progressive.mappings import TRAILER_TILE_MAP, expand_make
from modules.progressive.business_type_classifier import ai_pick_from_options
from modules.progressive.vehicle_amounts import resolve_vehicle_value
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
            # Collapse internal whitespace: a two-line tile label like
            # 'Refrigerated\nDry Freight' must read as 'Refrigerated Dry Freight'
            # so it matches TRAILER_TILE_MAP and the live combo option.
            norm = [' '.join(t.split()) for t in result]
            return [t for t in norm if t and t.lower() not in self._NON_TILE_LABELS]
        except Exception:
            return fallback

    # "Other / Not Listed" is NOT a destination tile — it's an EXPANDER that
    # reveals the FULL trailer taxonomy (Refrigerated Dry Freight, Tank, Horse,
    # Low-Boy, ...). The "Most common trailers" screen shows a business-type
    # curated subset; the real tile is often behind this expander.
    _OTHER_NOT_LISTED = "Other / Not Listed"

    def _strict_tile_match(self, trailer_type: str, options: list):
        """Keyword/exact/token match against `options` (excluding the expander).
        No AI, no raise — returns a Resolution or None."""
        selectable = [o for o in options if o != self._OTHER_NOT_LISTED]
        t = (trailer_type or "").upper()
        token = next((k for k in TRAILER_TILE_MAP if k in t), None)
        mapped = TRAILER_TILE_MAP.get(token) if token else None
        if mapped and mapped in selectable:
            return Resolution("Trailer tile", mapped, "MATCHED", trailer_type, "mapping")
        try:
            res = resolve_choice("Trailer tile", trailer_type, selectable)
            if res.value in selectable:
                return res
        except UnmappableValueError:
            pass
        return None

    async def resolve_tile(self, trailer_type: str) -> Resolution:
        """Resolve against the CURRENTLY visible tiles: strict match, then AI
        against the live options (excluding the expander), else HALT."""
        options = await self._enumerate_tiles()
        res = self._strict_tile_match(trailer_type, options)
        if res is not None:
            return res
        selectable = [o for o in options if o != self._OTHER_NOT_LISTED]
        ai_choice = ai_pick_from_options(trailer_type, selectable)
        if ai_choice and ai_choice in selectable:
            return Resolution("Trailer tile", ai_choice, "MATCHED", trailer_type, "ai")
        screenshot = await self.screenshot("trailer_tile_unmapped")
        raise UnmappableValueError(
            field="Trailer tile",
            source_value=trailer_type,
            available_options=list(selectable),
            screenshot_path=screenshot,
        )

    async def _click_tile(self, label: str) -> None:
        tile = self.page.get_by_text(label, exact=True).first
        await tile.click(force=True)

    async def select_trailer_type(self, trailer_type: str) -> None:
        """Pick the tile for the trailer string. Strict match on the common
        tiles first; if not there, expand 'Other / Not Listed' to the full
        taxonomy and resolve again (strict + AI) before clicking. HALT if the
        full list still has no match."""
        options = await self._enumerate_tiles()
        res = self._strict_tile_match(trailer_type, options)
        if res is None and self._OTHER_NOT_LISTED in options:
            print(f"    [Progressive] '{trailer_type}' not a common trailer; "
                  f"expanding '{self._OTHER_NOT_LISTED}'")
            await self._click_tile(self._OTHER_NOT_LISTED)
            await self.wait_for_extjs_idle()
            await self.page.wait_for_timeout(600)
            res = await self.resolve_tile(trailer_type)   # full list; raises if absent
        elif res is None:
            res = await self.resolve_tile(trailer_type)   # no expander; AI/HALT on common
        print(f"    [Progressive] Selecting trailer type: {res.value} ({res.note})")
        await self._click_tile(res.value)
        await self.wait_for_extjs_idle()


class AddTrailerPage(BasePage):
    """Add-Trailer ("Trailer Information") form.

    Fields confirmed live (JUAREZ 2026-06-05), in screen order:
      - Trailer Type (read-only display + Edit button; set on the tile picker)
      - "VIN" textbox (Optional, NO Lookup button)
      - "Year" combobox
      - "Make" combobox
      - "Zip code where the vehicle is located" textbox (pre-filled)
      - "Farthest one-way distance this trailer travels for work" combobox
      - "Is there a loan/lease on this trailer?" radio: Yes-Loan | Yes-Lease | No
      - Continue button

    NOT present on this form (unlike AddVehicle): GVW, tonnage, trailer-hitch,
    business-use, For-Hire. Comp/Coll + equipment + value MAY reveal after
    loan=No (mirrors the powered vehicle); each is guarded by field_exists and
    self-skips when the trailer form does not ask.
    """

    REQUIRED_FIELDS = ("year", "make", "vin")
    CONDITIONAL_FIELDS = ("vehicle_value", "vehicle_has_no_equipment")
    OPTIONAL_FIELDS = ("garaging_zip",)

    def __init__(self, page):
        super().__init__(page)
        self.warnings: list[str] = []

    def _log_skipped(self, field: str, reason: str) -> None:
        msg = f"add_trailer: skipped '{field}' — {reason}"
        print(f"    [Progressive] {msg}")
        self.warnings.append(msg)

    async def fill_from_mapped(self, trailer: MappedVehicle) -> None:
        """Fill the AddTrailer form from a MappedVehicle and click Continue.

        Confirmed live (JUAREZ 2026-06-05) the Trailer Information form is
        simpler than AddVehicle — fields, in screen order:
          - Trailer Type (read-only; already chosen on the tile picker)
          - VIN (label "VIN", Optional, NO Lookup button)
          - Year (combobox), Make (combobox)
          - ZIP ("Zip code where the vehicle is located", pre-filled)
          - Distance ("Farthest one-way distance this trailer travels for work")
          - Loan/lease radio ("Is there a loan/lease on this trailer?")
        There is NO GVW / tonnage / trailer-hitch / business-use combobox here.
        Comp/Coll + value may reveal after loan=No (mirrors the powered vehicle);
        every such step is guarded by field_exists so it self-skips if absent.

        APD conditional on trailer.value (same convention as powered vehicles):
          - trailer.value set    → Comp/Coll = Yes + fill Vehicle Value
          - trailer.value None   → Comp/Coll = No (liability-only)
        """
        await self.page.wait_for_load_state("networkidle", timeout=30_000)
        # The AddTrailer ExtJS form builds its fields after navigation; let it
        # settle so VIN/Year/Make are present before we touch them (a one-shot
        # selector check raced and intermittently missed the VIN field).
        try:
            await self.wait_for_extjs_idle(timeout_ms=8_000)
        except Exception:
            pass

        # Trailer Type is already chosen on the preceding tile picker
        # (MostCommonTrailersPage.select_trailer_type); it shows here read-only
        # next to an Edit button, so there is nothing to set on this form.

        # 1. VIN (labelled just "VIN", Optional, no Lookup button)
        if trailer.vin:
            await self._fill_by_vin(trailer.vin)

        # 2. Year + Make comboboxes. Required; only set when the VIN did not
        #    already auto-populate them (see _set_year / _set_make).
        await self._set_year(trailer.year)
        await self._set_make(trailer.make)

        # 3. ZIP override if different from pre-filled owner ZIP
        if trailer.garaging_zip:
            await self._set_zip(trailer.garaging_zip)

        # 4. Distance — label "Farthest one-way distance this trailer travels
        #    for work" (matched by the "Farthest one-way distance this" prefix).
        await self._set_distance(trailer.radius_miles)

        # 5. Loan/Lease
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
                await self._tick_no_equipment_checkbox()
                # Normalize the raw Blue-Quote value (US/latino) before filling,
                # like AddVehiclePage: '$14.000' is $14,000, not $14 — filling
                # the raw string makes ExtJS read '$14' (< the $100 floor) and
                # Progressive rejects the form.
                screenshot = await self.screenshot("trailer_value")
                val = resolve_vehicle_value(trailer.value, screenshot_path=screenshot)
                await self._fill_vehicle_value(
                    default=str(int(val)) if val else "25000"
                )
            else:
                print(
                    "    [Progressive] Trailer APD = No (Blue Quote has no "
                    "Value for this trailer); skipping equipment + Value section"
                )

        # 8. Continue
        await self._click_continue()

    # ---- VIN entry helper ----

    async def _fill_by_vin(self, vin: str) -> None:
        """Enter the trailer VIN.

        Confirmed live: the trailer form labels the field just "VIN" (with an
        "Optional" sub-label) and has NO "Lookup VIN" button — unlike the
        powered-vehicle form. We fill it and blur so any inline ExtJS decode of
        Year/Make can fire; Year/Make are then set explicitly by _set_year /
        _set_make if the decode did not populate them.
        """
        print(f"    [Progressive] Adding trailer by VIN: {vin}")
        # The trailer VIN field carries NO aria-label/placeholder; its accessible
        # name comes from aria-labelledby and reads "VIN Optional" (confirmed via
        # DIAG), so an exact "VIN" match misses. Use a partial accessible-name
        # match, then the ExtJS VIN validation type ('alphanumericPre1981', a
        # stable per-field-type marker on the name attribute).
        #
        # Crucially we WAIT for the field to render rather than a one-shot count
        # check: the AddTrailer form builds asynchronously and a count==0 race
        # used to fall through to the wrong selector and time out intermittently.
        vin_box = None
        for loc in (
            self.page.get_by_role("textbox", name="VIN"),
            self.page.locator('input[name*="alphanumericPre1981"]'),
        ):
            try:
                await loc.first.wait_for(state="visible", timeout=8_000)
                vin_box = loc
                break
            except Exception:
                continue
        if vin_box is None:
            vin_box = await self.find_by_label_text("VIN")
            if await vin_box.count() == 0:
                vin_box = self.page.get_by_role(
                    "textbox", name="Vehicle Identification Number (VIN)"
                )
        # verify=False because ExtJS may format VIN mid-stream (uppercase/mask)
        await self.safe_fill(vin_box.first, vin, verify=False)
        await self.blur_active_element()
        await self.page.wait_for_timeout(1_000)

    # ---- Trailer-specific field helpers ----

    async def _combo_current_value(self, combo) -> str:
        """Read an ExtJS combobox's current input value (empty string on error)."""
        try:
            return (await combo.first.input_value()).strip()
        except Exception:
            return ""

    async def _set_year(self, year: Optional[int]) -> None:
        """Set the Year combobox — unless the VIN already auto-decoded it."""
        combo = await self.find_combo("Year")
        if await combo.count() == 0:
            self._log_skipped("year", "combo not present (VIN may have decoded it)")
            return
        current = await self._combo_current_value(combo)
        if current:
            print(f"    [Progressive] Trailer Year already set: {current!r}")
            return
        if not year:
            self._log_skipped("year", "no value and combo empty")
            return
        await self.safe_select_combo(combo, str(year))
        print(f"    [Progressive] Trailer Year = {year}")

    async def _set_make(self, make: Optional[str]) -> None:
        """Set the (required) Make combobox — unless the VIN already decoded it.

        Blue-Quote make strings are abbreviated/noisy (e.g. 'BIGT 16G' for a
        Big Tex 16GN gooseneck), so a direct combo match usually misses. We then
        fall back to a typeahead-filtered match: type the make's leading letters
        to filter the (very long) manufacturer list, enumerate the filtered
        options, and select ONLY on a confident prefix match — never an
        arbitrary first option. If nothing confident matches we leave it empty
        and let the Continue-step validation surface the real options.
        """
        combo = await self.find_combo("Make")
        if await combo.count() == 0:
            self._log_skipped("make", "combo not present (VIN may have decoded it)")
            return
        current = await self._combo_current_value(combo)
        if current:
            print(f"    [Progressive] Trailer Make already set: {current!r}")
            return
        if not make:
            self._log_skipped("make", "no value and combo empty")
            return
        # Expand known abbreviations first ('GD' -> 'Great Dane'): some are not a
        # prefix/substring of the full name so neither match strategy finds them.
        resolved = expand_make(make)
        # 1) Direct tolerant match (exact/partial via safe_select_combo).
        try:
            await self.safe_select_combo(combo, resolved)
            print(f"    [Progressive] Trailer Make = {resolved!r}"
                  f"{'' if resolved == make else f' (from {make!r})'}")
            return
        except Exception:
            pass
        # 2) Typeahead-filtered confident match.
        matched = await self._select_make_by_prefix(combo, resolved)
        if matched:
            print(f"    [Progressive] Trailer Make = {matched!r} (typeahead from {make!r})")
            return
        # 3) Free-text commit: many ExtJS make combos accept a typed value not in
        #    the list (forceSelection=false). 'Heil' has no list option, so type
        #    it and commit with Enter.
        freetext = await self._commit_make_freetext(combo, resolved)
        if freetext:
            print(f"    [Progressive] Trailer Make = {freetext!r} (free text from {make!r})")
            return
        # 4) The make isn't a listed manufacturer at all. Fall back to a generic
        #    'Other' make if the combo offers one, so the required field is set.
        other = await self._select_other_make(combo)
        if other:
            print(f"    [Progressive] Trailer Make = {other!r} (no listed make for {make!r})")
            self.warnings.append(f"add_trailer: make {make!r} not listed; used {other!r}")
            return
        print(f"    [Progressive] WARN: Trailer Make {make!r} (->{resolved!r}) not matched in combo")
        self.warnings.append(f"add_trailer: make {make!r} not matched in combo")

    async def _commit_make_freetext(self, combo, make: str) -> Optional[str]:
        """Type `make` and commit it with Enter. Works when the combo accepts
        free text (forceSelection=false). Verifies the value stuck. Returns the
        committed value or None."""
        try:
            await self.blur_active_element()
            await self.page.wait_for_timeout(200)
            await combo.first.click(timeout=5_000)
            await self.page.wait_for_timeout(250)
            try:
                await self.page.keyboard.press("Control+A")
                await self.page.keyboard.press("Delete")
            except Exception:
                pass
            await self.page.keyboard.type(make, delay=50)
            await self.page.wait_for_timeout(400)
            await self.page.keyboard.press("Enter")
            await self.page.wait_for_timeout(400)
            await self.blur_active_element()
            val = await self._combo_current_value(combo)
            token = make.strip().split()[0].upper() if make.strip() else ""
            if val and token and token[:3] in val.upper():
                return val
        except Exception as e:
            print(f"    [DIAG] make free-text commit failed: {e}")
        return None

    async def _select_other_make(self, combo) -> Optional[str]:
        """Select a generic 'Other'/'Not Listed'/'Misc' option in the Make combo
        for makes Progressive doesn't list. Returns the chosen label or None."""
        import re
        try:
            await self.blur_active_element()
            await self.page.wait_for_timeout(200)
            await combo.first.click(timeout=5_000)
            await self.page.wait_for_timeout(400)
            try:
                await self.page.keyboard.press("Control+A")
                await self.page.keyboard.press("Delete")
            except Exception:
                pass
            await self.page.keyboard.type("Other", delay=60)
            await self.page.wait_for_timeout(700)
            opts = await self._enumerate_combo_options()
            cand = next(
                (o for o in opts if re.search(r"other|not listed|misc", o, re.I)),
                None,
            )
            if cand:
                opt = self.page.get_by_role("option", name=cand, exact=True).first
                if await opt.count() == 0:
                    opt = self.page.locator(
                        f"li.x-boundlist-item:has-text({cand!r})"
                    ).first
                await opt.click(timeout=5_000)
                await self.page.wait_for_timeout(400)
                return cand
        except Exception as e:
            print(f"    [DIAG] other-make select failed: {e}")
        return None

    async def _enumerate_combo_options(self) -> list:
        """Read the visible ExtJS dropdown option labels (boundlist first, then
        role=option as a fallback)."""
        try:
            opts = await self.page.evaluate(
                """() => {
                    const out = [];
                    document.querySelectorAll('li.x-boundlist-item').forEach(el => {
                        if (el.offsetParent !== null) {
                            const t = (el.innerText || '').trim();
                            if (t) out.push(t);
                        }
                    });
                    return out;
                }"""
            )
        except Exception:
            opts = []
        if not opts:
            try:
                raw = await self.page.get_by_role("option").all_inner_texts()
                opts = [o.strip() for o in raw if o.strip()]
            except Exception:
                opts = []
        return [" ".join(o.split()) for o in opts if o.strip()]

    async def _select_make_by_prefix(self, combo, make: str) -> Optional[str]:
        """Filter the Make list by typing the make's leading letters, then pick
        the best option (prefix match, else AI over the filtered list). A prior
        failed direct attempt can leave the dropdown open, so we close + reopen +
        clear before typing (typing into a toggled-closed combo returned 0
        options for 'HEIL')."""
        import re
        tokens = re.findall(r"[A-Za-z]+", make.upper())
        if not tokens:
            return None
        first = tokens[0]                    # e.g. "HEIL"
        prefix = first[:3]                   # e.g. "HEI"
        try:
            # Clean state: close any open dropdown, focus fresh, clear residual.
            await self.blur_active_element()
            await self.page.wait_for_timeout(200)
            await combo.first.click(timeout=5_000)
            await self.page.wait_for_timeout(250)
            try:
                await self.page.keyboard.press("Control+A")
                await self.page.keyboard.press("Delete")
            except Exception:
                pass
            await self.page.keyboard.type(prefix, delay=60)
            await self.page.wait_for_timeout(900)
            opts = await self._enumerate_combo_options()
            print(f"    [DIAG] Make options for prefix {prefix!r} "
                  f"({len(opts)}): {opts[:40]}")
            if not opts:
                return None

            def compact(s: str) -> str:
                return re.sub(r"[^A-Z0-9]", "", s.upper())

            cf = compact(first)
            best = None
            for o in opts:
                co = compact(o)
                if co.startswith(cf) or cf.startswith(co):
                    best = o
                    break
            if best is None:
                for o in opts:
                    if cf in compact(o):
                        best = o
                        break
            if best is None:
                # Last resort: let the AI map the abbreviation to one of the
                # filtered makes (e.g. 'HEIL' -> 'Heil').
                ai = ai_pick_from_options(make, opts)
                if ai and ai in opts:
                    best = ai
            if best is not None:
                opt = self.page.get_by_role("option", name=best, exact=True).first
                if await opt.count() == 0:
                    opt = self.page.locator(
                        f"li.x-boundlist-item:has-text({best!r})"
                    ).first
                await opt.click(timeout=5_000)
                await self.page.wait_for_timeout(500)
                return best
        except Exception as e:
            print(f"    [DIAG] make prefix select failed: {e}")
        return None

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
