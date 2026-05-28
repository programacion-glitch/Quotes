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
        if coverages.bodily_injury_limit and coverages.bodily_injury_limit != "$1,000,000 CSL":
            await self._set_combobox(
                "Bodily Injury and Property Damage Liability",
                coverages.bodily_injury_limit,
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
        combos = self.page.get_by_role("combobox", name=label, exact=False)
        count = await combos.count()
        if count == 0:
            print(f"    [Progressive] WARN: no combobox '{label}' found")
            return
        print(f"    [Progressive] Setting {count}x '{label}' = '{option_text}'")
        for i in range(count):
            try:
                await combos.nth(i).click(timeout=5_000)
                await self.page.wait_for_timeout(400)
                opt = self.page.get_by_role("option", name=option_text, exact=False).first
                if await opt.count() > 0:
                    await opt.click(timeout=5_000)
                    await self.page.wait_for_timeout(400)
                else:
                    # close the dropdown
                    await self.page.keyboard.press("Escape")
            except Exception as e:
                print(f"    [Progressive] WARN: '{label}'[{i}] = '{option_text}' failed: {e}")

    async def capture_price(self) -> QuotePrice:
        """Extract the displayed premium without modifying the page."""
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
        btn = self.page.get_by_role("button", name="Finish & Buy").last
        await btn.click(timeout=10_000)
        await self.page.wait_for_load_state("networkidle", timeout=60_000)

    # ---- Helpers ----

    async def _set_combobox(self, label: str, option_text: str) -> None:
        """Open a Sencha combobox by label and pick an option by visible text."""
        combo = self.page.get_by_role("combobox", name=label, exact=False)
        if await combo.count() == 0:
            print(f"    [Progressive] WARN: combobox '{label}' not found")
            return
        await combo.first.click()
        await self.page.wait_for_timeout(500)
        opt = self.page.get_by_role("option", name=option_text, exact=False).first
        if await opt.count() > 0:
            await opt.click(timeout=5_000)
            await self.page.wait_for_timeout(500)

    async def _set_radio(self, group_label: str, value: str) -> None:
        """Click a radio inside a named radiogroup."""
        group = self.page.get_by_role("radiogroup", name=group_label, exact=False)
        if await group.count() == 0:
            return
        await group.get_by_role("radio", name=value, exact=True).click()
        await self.page.wait_for_timeout(300)

    async def _expand_coverage(self, name: str) -> None:
        """Expand a '+' button next to a special coverage section if collapsed."""
        btn = self.page.get_by_role("button", name=name, exact=True)
        if await btn.count() == 0:
            return
        # Already expanded if attribute 'expanded' is true; safest is just to click
        try:
            await btn.first.click(timeout=5_000)
            await self.page.wait_for_timeout(800)
        except Exception:
            pass

    async def _recalculate_if_needed(self) -> None:
        """Click Recalculate button if it's visible (after coverage changes)."""
        btn = self.page.get_by_role("button", name="Recalculate")
        if await btn.count() > 0:
            print("    [Progressive] Recalculating premium...")
            await btn.last.click(timeout=10_000)
            await self.page.wait_for_load_state("networkidle", timeout=30_000)
            await self.page.wait_for_timeout(2_000)

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
            await self.page.wait_for_timeout(800)

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
            await self.page.wait_for_timeout(800)

    async def _configure_motor_truck_cargo(self, limit: str) -> None:
        """Fill Motor Truck Cargo subform with the given limit.

        Note: Motor Truck Cargo typically has additional questions (refrigeration,
        commodities, deductible) that appear progressively. Live exploration of
        these specific fields is pending — current code sets only the limit
        and hopes Progressive applies sensible defaults for the rest.
        """
        print(f"    [Progressive] Configuring Motor Truck Cargo: {limit}")
        await self._expand_coverage("Motor Truck Cargo")
        await self._set_combobox("Motor Truck Cargo coverage limit", limit)
        done = self.page.get_by_role("button", name="Done with this coverage")
        if await done.count() > 0:
            await done.first.click(timeout=5_000)
            await self.page.wait_for_timeout(800)

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
            await self.page.wait_for_timeout(800)
