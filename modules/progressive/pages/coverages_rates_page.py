"""
CoveragesRates page (RATES step in wizard).

URL: pageName=CoveragesRates
Validated live 2026-05-25.

This is THE page where the premium is calculated and displayed.

Top-level layout:
  - Premium banner: "$XX,XXX.XX per year" + pay-in-full discount
  - Coverages applied to all vehicles (BI/PD, UM/UIM, PIP)
  - Per-vehicle coverages (Comp, Collision, Med Pay, Rental, Roadside, Fire&Theft)
  - Special coverages: Hired Auto Liability, Employer Non-Owned, Motor Truck Cargo,
    Non-Owned Trailer Physical Damage (each expandable with a "+" button)

After any change, page shows "The coverages have changed, please 'recalculate'..."
with a Recalculate button — must be clicked before Finish & Buy.
"""

import re
from dataclasses import dataclass
from typing import Optional

from modules.progressive.pages.base_page import BasePage
from modules.progressive.field_mapper import MappedFields


@dataclass
class QuotePrice:
    """Captured premium information from the RATES page."""
    annual_premium: Optional[str] = None         # "$53,064.00"
    pay_in_full_amount: Optional[str] = None     # "$38,143.00"
    pay_in_full_savings: Optional[str] = None    # "$7,812.00"
    quote_provided_by: Optional[str] = None      # "Progressive County Mutual Ins Co"
    quote_number: Optional[str] = None           # "CA116960411"
    raw_text: str = ""


class CoveragesRatesPage(BasePage):
    """Progressive wizard - CoveragesRates page (RATES step)."""

    async def customize_and_capture(self, fields: MappedFields) -> QuotePrice:
        """
        Apply coverage selections, recalculate, capture the premium.

        Args:
            fields: mapped fields including coverages preferences.

        Returns:
            QuotePrice with extracted premium info.
        """
        await self.page.wait_for_load_state("networkidle", timeout=30_000)
        await self.remove_overlays()

        coverages = fields.coverages

        # ---- Per-policy coverages (apply to all vehicles) ----

        # Bodily Injury + Property Damage Liability limit
        # Normalize abbreviated labels (e.g. "$1M CSL" → "$1 million CSL") to match
        # Progressive's actual dropdown option text.
        if coverages.bodily_injury_limit:
            bi_label = self._normalize_bi_limit(coverages.bodily_injury_limit)
            # "$1 million CSL" is Progressive's default — skip unless value differs
            if bi_label != "$1 million CSL":
                await self._set_combobox(
                    "Bodily Injury and Property Damage Liability",
                    bi_label,
                )

        # Uninsured / Underinsured Motorist Bodily Injury
        if coverages.uninsured_motorist_limit:
            await self._set_combobox(
                "Uninsured/Underinsured Motorist Bodily Injury",
                coverages.uninsured_motorist_limit,
            )
            # Property Damage half — Progressive's combo name is "Uninsured Motorist Bodily Injury"
            # (yes, the label is duplicated by Progressive)
            await self._set_combobox(
                "Uninsured Motorist Bodily Injury",
                coverages.uninsured_motorist_limit,
            )

        # Personal Injury Protection
        if coverages.personal_injury_protection_limit:
            await self._set_combobox(
                "Personal Injury Protection",
                coverages.personal_injury_protection_limit,
            )

        # ---- Per-vehicle coverages ----

        # Comp / Coll deductibles + Med Pay + Rental + Roadside + Fire&Theft
        # All vehicles get the same per-policy defaults unless overridden.
        await self._apply_per_vehicle_coverages(coverages)

        # ---- Special / business coverages ----

        if coverages.hired_auto:
            await self._configure_hired_auto(coverages)

        if coverages.non_owned_auto:
            await self._configure_non_owned_auto(coverages)

        if coverages.motor_truck_cargo_limit:
            await self._configure_motor_truck_cargo(coverages.motor_truck_cargo_limit)

        if coverages.non_owned_trailer_phys_damage_limit:
            await self._configure_non_owned_trailer_phys_damage(
                coverages.non_owned_trailer_phys_damage_limit
            )

        # Recalculate if any change was made
        await self._recalculate_if_needed()

        # Capture the price
        return await self.capture_price()

    async def _apply_per_vehicle_coverages(self, coverages) -> None:
        """Set Comp deductible, Coll deductible, Med Pay, Rental, Roadside, Fire&Theft.

        Each appears once per vehicle in a 'group' region named after the vehicle.
        For policy-wide defaults we set the first instance of each combobox; the others
        inherit unless explicitly overridden per vehicle (not currently supported).
        """
        # Comprehensive deductible
        if coverages.comp_deductible:
            await self._set_combobox_all(
                "Comprehensive",
                coverages.comp_deductible,
                expected_default="$500 Deductible",
            )

        # Collision deductible
        if coverages.coll_deductible:
            await self._set_combobox_all(
                "Collision",
                coverages.coll_deductible,
                expected_default="$500 Deductible",
            )

        # Medical Payments (per vehicle)
        if coverages.medical_payments_limit:
            await self._set_combobox_all(
                "Medical Payments",
                coverages.medical_payments_limit,
            )

        # Rental Reimbursement (per vehicle)
        if coverages.rental_reimbursement_limit:
            await self._set_combobox_all(
                "Rental Reimbursement",
                coverages.rental_reimbursement_limit,
            )

        # Roadside Assistance (per vehicle) - default "Selected w/ $0 Deductible"
        if coverages.roadside_assistance != "Selected w/ $0 Deductible":
            await self._set_combobox_all("Roadside Assistance", coverages.roadside_assistance)

        # Fire & Theft w/ Combined Additional Coverage (per vehicle)
        if coverages.fire_theft_cac:
            await self._set_combobox_all(
                "Fire & Theft w/ Combined Additional Coverage",
                coverages.fire_theft_cac,
            )

    async def _set_combobox_all(
        self,
        label: str,
        option_text: str,
        expected_default: Optional[str] = None,
    ) -> None:
        """Set EVERY occurrence of a combobox with the given label (one per vehicle)."""
        combo_loc = await self.find_combo(label, exact=False)
        count = await combo_loc.count()
        if count == 0:
            print(f"    [Progressive] WARN: no combobox '{label}' found")
            return
        print(f"    [Progressive] Setting {count}x '{label}' = '{option_text}'")
        for i in range(count):
            try:
                await self.safe_select_combo(combo_loc.nth(i), option_text)
            except Exception as e:
                print(f"    [Progressive] WARN: '{label}'[{i}] = '{option_text}' failed: {e}")

    async def capture_price(self) -> QuotePrice:
        """Extract the displayed premium without modifying the page."""
        # Safety net: ensure ExtJS finished re-rendering the price banner
        try:
            await self.wait_for_extjs_idle(timeout_ms=10_000)
        except Exception as e:
            print(f"    [Progressive] WARN: capture_price extjs_idle: {e}")
        # Diagnostic screenshot before reading so we can debug capture failures
        await self.screenshot("rates_before_capture")

        price = QuotePrice()

        # Quote number from header
        try:
            page_text = await self.page.inner_text("body")
            m = re.search(r"Quote\s+Number:?\s*(CA\d{8,12})", page_text, re.IGNORECASE)
            if m:
                price.quote_number = m.group(1)

            # Annual premium - look for the first $X,XXX.XX preceded/followed by "per year"
            m = re.search(
                r"\$([\d,]+\.\d{2})\s*(?:per year|Total premium amount\s*\$[\d,]+\.\d{2}\s*per year)",
                page_text,
                re.IGNORECASE,
            )
            if not m:
                m = re.search(r"Total premium amount\s*\$([\d,]+\.\d{2})", page_text, re.IGNORECASE)
            if m:
                price.annual_premium = f"${m.group(1)}"

            # Pay in full
            m = re.search(
                r"Or save \$([\d,]+\.\d{2}) by paying in full:\s*\$([\d,]+\.\d{2})",
                page_text,
                re.IGNORECASE,
            )
            if m:
                price.pay_in_full_savings = f"${m.group(1)}"
                price.pay_in_full_amount = f"${m.group(2)}"

            # Quote provided by
            m = re.search(r"Quote provided by:\s*([^\n]+)", page_text)
            if m:
                price.quote_provided_by = m.group(1).strip()

            price.raw_text = page_text[:2000]
        except Exception as e:
            print(f"    [Progressive] Price capture warning: {e}")

        print(f"    [Progressive] PRICE CAPTURED: {price.annual_premium} / year")
        if price.pay_in_full_amount:
            print(f"    [Progressive]   Pay-in-full: {price.pay_in_full_amount} (saves {price.pay_in_full_savings})")
        if price.quote_provided_by:
            print(f"    [Progressive]   Carrier: {price.quote_provided_by}")
        if price.quote_number:
            print(f"    [Progressive]   Quote #: {price.quote_number}")

        return price

    async def proceed_to_final_details(self) -> None:
        """Click 'Finish & Buy' to advance to AdditionalDetails (NOT payment)."""
        print("    [Progressive] Advancing to FINAL DETAILS...")
        await self._recalculate_if_needed()
        await self.safe_click_continue(expect_url_changes_from="CoveragesRates")

    # ---- Helpers ----

    # BI/PD liability option text normalization:
    # BlueQuote PDF uses abbreviated forms; Progressive UI uses spelled-out forms.
    _BI_LIMIT_PROGRESSIVE_LABEL: dict = {
        "$500K CSL":       "$500,000 CSL",
        "$750K CSL":       "$750,000 CSL",
        "$1M CSL":         "$1 million CSL",
        "$1,000,000 CSL":  "$1 million CSL",
        "$500,000 CSL":    "$500,000 CSL",
        "$750,000 CSL":    "$750,000 CSL",
    }

    def _normalize_bi_limit(self, limit: str) -> str:
        """Translate abbreviated BI/PD limit labels to Progressive's displayed option text."""
        return self._BI_LIMIT_PROGRESSIVE_LABEL.get(limit, limit)

    async def _set_combobox(self, label: str, option_text: str) -> None:
        """Open a Sencha combobox by label and pick an option by visible text."""
        combo = await self.find_combo(label, exact=False)
        if await combo.count() == 0:
            print(f"    [Progressive] WARN: combobox '{label}' not found")
            return
        try:
            await self.safe_select_combo(combo.first, option_text)
        except Exception as e:
            print(f"    [Progressive] WARN: combobox '{label}' = '{option_text}' failed: {e}")

    async def _set_radio(self, group_label: str, value: str) -> None:
        """Click a radio inside a named radiogroup."""
        group = await self.find_radiogroup(group_label, exact=False)
        if await group.count() == 0:
            return
        try:
            await self.safe_radio(group, value)
        except Exception as e:
            print(f"    [Progressive] WARN: radio '{group_label}' = '{value}' failed: {e}")

    async def _expand_coverage(self, name: str) -> bool:
        """Expand a '+' button next to a special coverage section if collapsed.

        Returns True if the button was found and clicked, False if the section
        was not present on the page (coverage not available for this quote).
        """
        btn = self.page.get_by_role("button", name=name, exact=True)
        if await btn.count() == 0:
            return False
        # Already expanded if attribute 'expanded' is true; safest is just to click
        try:
            await btn.first.click(timeout=5_000)
            # Wait for ExtJS to finish rendering the expanded subform
            await self.wait_for_extjs_idle()
        except Exception:
            pass
        return True

    async def _recalculate_if_needed(self) -> None:
        """Click Recalculate button if it's visible (after coverage changes)."""
        btn = self.page.get_by_role("button", name="Recalculate")
        if await btn.count() > 0:
            print("    [Progressive] Recalculating premium...")
            await btn.last.click(timeout=10_000)
            await self.page.wait_for_load_state("networkidle", timeout=30_000)
            # ExtJS recalculate is an internal Ajax that may not trigger
            # networkidle reliably. Wait for ExtJS idle + DOM stable.
            try:
                await self.wait_for_extjs_idle(timeout_ms=15_000)
            except Exception as e:
                print(f"    [Progressive] WARN: wait_for_extjs_idle after recalc: {e}")

    # ---- Special coverages ----

    async def _configure_hired_auto(self, coverages) -> None:
        """Fill the Hired Auto Liability subform."""
        print("    [Progressive] Configuring Hired Auto Liability...")
        await self._expand_coverage("Hired Auto Liability")

        # Q1: How much spent renting/hiring/borrowing
        await self._set_radio(
            "How much did the customer spend in renting, hiring, or borrowing vehicles last year",
            coverages.hired_auto_spent_last_year,
        )

        # Q2: Contractual requirement (must be Yes for coverage to be available)
        await self._set_radio(
            "Is hired auto requested because of a contractual requirement?",
            "Yes" if coverages.hired_auto_contractual else "No",
        )

        if not coverages.hired_auto_contractual:
            print("    [Progressive] WARN: Hired Auto requires contractual=Yes; coverage will be unavailable")
            return

        # Q3: Broker any trips
        await self._set_radio(
            "Does the customer broker any trips?",
            "Yes" if coverages.hired_auto_brokers_trips else "No",
        )

        # Q4: How many autos rented/hired/borrowed
        await self._set_combobox(
            "How many autos did the customer rent, hire or borrow in the last year?",
            coverages.hired_auto_count_last_year,
        )

        # Q5: Freight broker
        await self._set_radio(
            "Does the customer operate as a freight-broker or freight-forwarder",
            "Yes" if coverages.hired_auto_freight_broker else "No",
        )

        # Q6: UIIA/intermodal endorsement
        await self._set_radio(
            "Is a UIIA or intermodal endorsement required?",
            "No",
        )

        # Q7: Limit
        await self._set_combobox("Hired Auto coverage limit", coverages.hired_auto_limit)

        # Done with this coverage button
        done = self.page.get_by_role("button", name="Done with this coverage")
        if await done.count() > 0:
            await done.first.click(timeout=5_000)
            # Wait for ExtJS to collapse the subform after Done
            await self.wait_for_extjs_idle()

    async def _configure_non_owned_auto(self, coverages) -> None:
        """Fill Employer Non-Owned Auto Liability subform."""
        print("    [Progressive] Configuring Employer Non-Owned Auto Liability...")
        await self._expand_coverage("Employer Non-Owned Auto Liability")

        await self._set_radio(
            "Are non-owned vehicles which are not listed on the policy used in the business?",
            "Yes" if coverages.non_owned_used_in_business else "No",
        )

        if not coverages.non_owned_used_in_business:
            return

        await self._set_radio(
            "On average, how many times per week?",
            coverages.non_owned_frequency,
        )

        await self._set_combobox(
            "How many people does the customer utilize to conduct their business?",
            coverages.non_owned_people_count,
        )

        await self._set_combobox(
            "Employer Non-Owned Auto Liability coverage limit",
            coverages.non_owned_limit,
        )

        done = self.page.get_by_role("button", name="Done with this coverage")
        if await done.count() > 0:
            await done.first.click(timeout=5_000)
            # Wait for ExtJS to collapse the subform after Done
            await self.wait_for_extjs_idle()

    async def _configure_motor_truck_cargo(self, limit: str = "$100,000") -> None:
        """Expand Motor Truck Cargo and set limit. Handles subform questions for distributor commodities."""
        print(f"    [Progressive] Configuring Motor Truck Cargo: {limit}")
        expanded = await self._expand_coverage("Motor Truck Cargo")
        if not expanded:
            print(f"    [Progressive] WARN: could not expand Motor Truck Cargo; skipping")
            return

        # Wait for ExtJS to render the subform (commodities pages can have animations)
        try:
            await self.wait_for_extjs_idle(timeout_ms=5_000)
        except Exception:
            pass
        await self.page.wait_for_timeout(800)  # extra cushion for animations

        # Iteratively answer MTC subform Yes/No questions that Progressive
        # reveals for distributor commodities. Default No for all (RYD-style
        # bottled-water/food carriers don't need refrigeration / mobile homes /
        # documents extras). After each answer, Progressive may reveal the
        # next question; the loop runs once per known question.
        #
        # Each tuple: (display_name, full_question_text_for_find, answer)
        known_subform_questions = [
            (
                "mobile/modular homes",
                "Does the customer require cargo coverage for mobile/modular homes",
                "No",
            ),
            (
                "business documents",
                "Does the customer require cargo coverage for business documents",
                "No",
            ),
            (
                "refrigeration breakdown",
                "Does the customer require Refrigeration Breakdown coverage",
                "No",
            ),
            (
                "targeted commodities",
                "Does the customer require cargo coverage for targeted commodities",
                "No",
            ),
            (
                "explosives",
                "Does the customer require cargo coverage for explosives",
                "No",
            ),
        ]
        for label_hint, question, answer in known_subform_questions:
            group = await self.find_radiogroup(question, timeout_ms=1_500)
            if not await self.field_exists(group, wait_ms=1_000):
                continue
            print(f"    [Progressive] MTC subform: {label_hint} = {answer}")
            try:
                await self.safe_radio(group, answer)
            except Exception as e:
                print(f"    [Progressive] WARN: MTC '{label_hint}' radio failed: {e}")
            try:
                await self.wait_for_extjs_idle(timeout_ms=5_000)
            except Exception:
                pass
            await self.page.wait_for_timeout(800)

        # Diagnostic snapshot (kept to detect further subform questions next iteration)
        await self.screenshot("mtc_after_expansion")
        try:
            nearby = await self.page.evaluate(
                """() => {
                    const out = {labels: [], comboboxes: [], buttons: [], radios: []};
                    document.querySelectorAll('label, .x-form-item-label').forEach(el => {
                        const t = (el.innerText || '').trim();
                        if (t && el.offsetParent !== null) out.labels.push(t);
                    });
                    document.querySelectorAll('[role="combobox"]').forEach(el => {
                        const name = el.getAttribute('aria-label') ||
                                     (el.previousElementSibling && el.previousElementSibling.innerText) || '';
                        if (el.offsetParent !== null) out.comboboxes.push(name.trim());
                    });
                    document.querySelectorAll('button, a.x-btn, .x-btn-inner').forEach(el => {
                        const t = (el.innerText || '').trim();
                        if (t && el.offsetParent !== null) out.buttons.push(t);
                    });
                    document.querySelectorAll('[role="radio"]').forEach(el => {
                        const name = el.getAttribute('aria-label') ||
                                     (el.closest('label') && el.closest('label').innerText) || '';
                        if (el.offsetParent !== null) out.radios.push(name.trim());
                    });
                    const dedupe = arr => [...new Set(arr)].slice(0, 40);
                    return {
                        labels: dedupe(out.labels),
                        comboboxes: dedupe(out.comboboxes),
                        buttons: dedupe(out.buttons),
                        radios: dedupe(out.radios),
                    };
                }"""
            )
            print(f"    [Progressive] MTC DIAGNOSTIC — visible after expansion/subform:")
            print(f"    [Progressive]   labels (first 40): {nearby.get('labels', [])[:40]}")
            print(f"    [Progressive]   comboboxes: {nearby.get('comboboxes', [])}")
            print(f"    [Progressive]   buttons: {nearby.get('buttons', [])}")
            print(f"    [Progressive]   radios: {nearby.get('radios', [])}")
        except Exception as e:
            print(f"    [Progressive] MTC DIAGNOSTIC failed: {e}")

        # Detect which MTC configuration path is active:
        #   Trucker path     → "Motor Truck Cargo coverage limit" combobox visible
        #   Distributor path → "+ Add a commodity" link visible
        limit_combo = self.page.get_by_role("combobox", name="Motor Truck Cargo coverage limit")
        add_commodity = self.page.get_by_text("Add a commodity", exact=False)

        if await self.field_exists(limit_combo, wait_ms=1_500):
            # Trucker path: set limit directly
            await self._set_combobox("Motor Truck Cargo coverage limit", limit)
        elif await self.field_exists(add_commodity, wait_ms=1_500):
            # Distributor path: open Add a commodity dialog and add at least one
            await self._add_mtc_commodities()
        else:
            print(f"    [Progressive] WARN: MTC neither limit combobox nor Add-commodity link visible; skipping")
            print(f"    [Progressive]   Screenshot saved at logs/progressive_mtc_after_expansion.png")
            return

        done = self.page.get_by_role("button", name="Done with this coverage")
        if await done.count() > 0:
            await done.first.click(timeout=5_000)
            # Wait for ExtJS to collapse the subform after Done
            await self.wait_for_extjs_idle()

    async def _add_mtc_commodities(self) -> None:
        """Open the inline 'Add a commodity' form and pick a commodity for MTC.

        For Beverage Distributor commodities, Progressive shows TWO cascading
        comboboxes (NOT a popup dialog):
          1. 'Commodity Type:' with placeholder 'Select category'
          2. 'Commodity:' with placeholder 'Select commodity' (filtered)

        The row auto-commits when both combos have values (no Save button).
        A small × button closes the row.

        Strategy: enumerate Category options, pick the first one that exists
        from our preference order; then enumerate Commodity options for that
        category and pick the first that matches RYD-style keywords.
        """
        print(f"    [Progressive] MTC: opening 'Add a commodity' inline form...")
        add_link = self.page.get_by_text("Add a commodity", exact=False).first
        try:
            await add_link.scroll_into_view_if_needed(timeout=2_000)
            await add_link.click(timeout=5_000)
        except Exception:
            try:
                await add_link.click(timeout=5_000, force=True)
            except Exception as e:
                print(f"    [Progressive] WARN: 'Add a commodity' link click failed: {e}")
                return

        # Wait for the inline form (two combos) to render
        try:
            await self.wait_for_extjs_idle(timeout_ms=5_000)
        except Exception:
            pass
        await self.page.wait_for_timeout(800)

        # Save a screenshot of the inline form for debugging
        await self.screenshot("mtc_commodity_dialog")

        # Step 1: open the Commodity Type (category) combo by clicking its
        # placeholder-bearing input, then enumerate visible options and pick
        # the first match from our preference list.
        category_input = self.page.locator(
            'input[placeholder="Select category"]'
        ).first
        if not await self.field_exists(category_input, wait_ms=1_500):
            print("    [Progressive] WARN: MTC 'Select category' input not visible")
            return

        category_preferences = [
            "Food", "Beverage", "Drink", "Water",
            "Wholesale", "Retail", "Grocery",
            "Pet", "Animal",
            "General", "Other",
        ]
        chosen_category = await self._pick_first_combo_option(
            category_input, category_preferences, label="Commodity Type"
        )
        if not chosen_category:
            print("    [Progressive] WARN: no matching commodity category found; canceling row")
            await self._cancel_commodity_row()
            return

        # Step 2: open the Commodity combo (now filtered by category) and
        # pick the first available option from our preference list.
        try:
            await self.wait_for_extjs_idle(timeout_ms=3_000)
        except Exception:
            pass
        await self.page.wait_for_timeout(500)

        commodity_input = self.page.locator(
            'input[placeholder="Select commodity"]'
        ).first
        if not await self.field_exists(commodity_input, wait_ms=1_500):
            print("    [Progressive] WARN: MTC 'Select commodity' input not visible after category")
            await self._cancel_commodity_row()
            return

        commodity_preferences = [
            "Water", "Bottled water",
            "Food", "Pet food", "Packaged food",
            "Beverage", "Beverages",
            "Charcoal",
            "General", "Other", "Misc",
        ]
        chosen_commodity = await self._pick_first_combo_option(
            commodity_input, commodity_preferences, label="Commodity"
        )
        if not chosen_commodity:
            # Last resort: pick whatever the first option is (we already
            # committed to a category; better any commodity than none).
            chosen_commodity = await self._pick_first_visible_combo_option(
                commodity_input, label="Commodity (first available)"
            )

        if not chosen_commodity:
            print("    [Progressive] WARN: no commodity selectable; canceling row")
            await self._cancel_commodity_row()
            return

        # Both combos filled — Progressive auto-commits the row. Just let
        # ExtJS settle.
        try:
            await self.wait_for_extjs_idle(timeout_ms=5_000)
        except Exception:
            pass
        await self.page.wait_for_timeout(800)
        print(f"    [Progressive] MTC commodity row committed: {chosen_category!r} / {chosen_commodity!r}")

    async def _pick_first_combo_option(
        self, combo_input, preferences: list, *, label: str
    ) -> Optional[str]:
        """Click an ExtJS combo input, enumerate visible options, click the first
        one whose name contains a preference keyword. Returns the selected text or None.
        """
        try:
            await combo_input.click(timeout=3_000)
        except Exception:
            try:
                await combo_input.click(timeout=3_000, force=True)
            except Exception as e:
                print(f"    [Progressive] WARN: {label} combo click failed: {e}")
                return None
        await self.page.wait_for_timeout(500)

        # ExtJS dropdown panel: x-boundlist with li.x-boundlist-item children
        try:
            visible_options = await self.page.evaluate(
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
            visible_options = []
        print(f"    [Progressive] {label} options visible: {visible_options[:30]}")

        # Pick first preference that matches (case-insensitive substring)
        for pref in preferences:
            pref_lower = pref.lower()
            for opt_text in visible_options:
                if pref_lower in opt_text.lower():
                    try:
                        opt = self.page.get_by_role(
                            "option", name=opt_text, exact=True
                        ).first
                        if not await self.field_exists(opt, wait_ms=500):
                            opt = self.page.locator(
                                f"li.x-boundlist-item:has-text({opt_text!r})"
                            ).first
                        await opt.click(timeout=3_000)
                        print(f"    [Progressive] {label} selected: {opt_text!r}")
                        return opt_text
                    except Exception as e:
                        print(f"    [Progressive] {label} option click failed for {opt_text!r}: {e}")
                        continue
        return None

    async def _pick_first_visible_combo_option(
        self, combo_input, *, label: str
    ) -> Optional[str]:
        """Re-open the combo and click whatever the first visible option is.
        Used as last-resort fallback when no preference keyword matches.
        """
        try:
            await combo_input.click(timeout=3_000, force=True)
        except Exception:
            return None
        await self.page.wait_for_timeout(500)

        try:
            visible_options = await self.page.evaluate(
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
            visible_options = []

        if not visible_options:
            return None
        first = visible_options[0]
        try:
            opt = self.page.locator(
                f"li.x-boundlist-item:has-text({first!r})"
            ).first
            await opt.click(timeout=3_000)
            print(f"    [Progressive] {label} = {first!r} (first available)")
            return first
        except Exception:
            return None

    async def _cancel_commodity_row(self) -> None:
        """Click the small × button to cancel an open commodity row."""
        try:
            x_btn = self.page.locator(
                'a.x-tool[aria-label*="close" i], a.x-tool-close, .x-tool-img.x-tool-img-default-close'
            ).first
            if await self.field_exists(x_btn, wait_ms=500):
                await x_btn.click(timeout=2_000, force=True)
                print("    [Progressive] MTC commodity row canceled (× clicked)")
        except Exception:
            pass

    async def _configure_non_owned_trailer_phys_damage(self, limit: str) -> None:
        """Fill Non-Owned Trailer Physical Damage subform."""
        print(f"    [Progressive] Configuring Non-Owned Trailer Physical Damage: {limit}")
        await self._expand_coverage("Non-Owned Trailer Physical Damage")
        await self._set_combobox(
            "Non-Owned Trailer Physical Damage coverage limit",
            limit,
        )
        done = self.page.get_by_role("button", name="Done with this coverage")
        if await done.count() > 0:
            await done.first.click(timeout=5_000)
            # Wait for ExtJS to collapse the subform after Done
            await self.wait_for_extjs_idle()
