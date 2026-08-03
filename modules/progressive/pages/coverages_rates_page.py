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
from pathlib import Path
from typing import Optional

from modules import decision_ledger
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

    def __init__(self, page):
        super().__init__(page)
        # Collected by quote_flow into QuoteResult.warnings.
        self.warnings: list = []

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

        # Stash the Blue-Quote commodity so the MTC cargo picker can classify it
        # (free text -> Progressive's cargo Type/Commodity lists) via the AI
        # classifier, instead of guessing from a hardcoded preference order.
        self._commodity = fields.commodity

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
                coverages.non_owned_trailer_phys_damage_limit,
                count=getattr(coverages, "non_owned_trailer_count", 0) or 1,
            )

        if getattr(coverages, "trailer_interchange_limit", None):
            await self._configure_trailer_interchange(
                coverages.trailer_interchange_limit
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
        # Comprehensive deductible. skip_not_selected: a column showing
        # "Not selected" is a unit we deliberately quoted liability-only
        # (e.g. trailer with no Value in the Blue Quote). Forcing a deductible
        # there makes Progressive require Equipment/Trailer Value and the
        # premium never materializes (live DIBOLL 2026-06-10).
        if coverages.comp_deductible:
            await self._set_combobox_all(
                "Comprehensive",
                coverages.comp_deductible,
                expected_default="$500 Deductible",
                skip_not_selected=True,
            )

        # Collision deductible (same liability-only guard as Comprehensive)
        if coverages.coll_deductible:
            await self._set_combobox_all(
                "Collision",
                coverages.coll_deductible,
                expected_default="$500 Deductible",
                skip_not_selected=True,
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

        # Roadside Assistance (per vehicle) — Diana 2026-06-25: debe ir SIEMPRE
        # seleccionado. Antes se saltaba cuando el valor era el default y
        # Progressive lo dejaba en 'Not selected' (no se agregaba). Ahora se
        # aplica siempre, salvo que explícitamente sea 'Not selected'.
        if (coverages.roadside_assistance
                and coverages.roadside_assistance.strip().lower() != "not selected"):
            await self._set_combobox_all("Roadside Assistance", coverages.roadside_assistance)
            decision_ledger.record("Roadside Assistance",
                                   coverages.roadside_assistance,
                                   page="Coverages/RATES", source="RULE",
                                   rule_id="R-001")

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
        skip_not_selected: bool = False,
    ) -> None:
        """Set EVERY occurrence of a combobox with the given label (one per vehicle).

        skip_not_selected: leave alone any column currently at "Not selected" —
        that unit was deliberately quoted without this coverage and selecting a
        value would trigger new required fields (Equipment/Trailer Value).
        """
        combo_loc = await self.find_combo(label, exact=False)
        count = await combo_loc.count()
        if count == 0:
            print(f"    [Progressive] WARN: no combobox '{label}' found")
            return
        print(f"    [Progressive] Setting {count}x '{label}' = '{option_text}'")
        for i in range(count):
            try:
                if skip_not_selected:
                    current = ""
                    try:
                        current = (await combo_loc.nth(i).input_value()) or ""
                    except Exception:
                        pass
                    if not current.strip() or "not selected" in current.lower():
                        print(
                            f"    [Progressive] '{label}'[{i}] is 'Not selected' "
                            f"(liability-only unit); leaving as-is"
                        )
                        continue
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

    async def _ensure_on_rates(self, *, timeout_ms: int = 30_000) -> None:
        """Garantiza que el wizard esté en RATES (pageName=CoveragesRates).

        No-op si ya está en RATES (evita re-rate). Si no, click el step 'RATES'
        del nav superior y espera a que cargue.
        """
        if await self.current_page_token() == "CoveragesRates":
            return
        await self.remove_overlays()
        try:
            await self.page.get_by_role("button", name="RATES", exact=True).click(
                force=True, timeout=10_000
            )
        except Exception:
            pass
        await self.wait_for_page("CoveragesRates", timeout_ms=timeout_ms)
        await self.wait_for_extjs_idle()

    async def download_quote_pdf(
        self, name: str, *, output_dir: str = "data/quote_pdfs", max_attempts: int = 2
    ) -> Optional[str]:
        """Descarga el PDF oficial (proposal) desde RATES.

        Flujo: 'Print, Email, Fax' -> radio 'Insurance Quote' -> checkbox 'Print'
        -> 'Print/Send' (abre popup con el PDF) -> captura la URL del popup ->
        fetch autenticado -> 'Return to quote'. Reintenta hasta `max_attempts`; si
        todos fallan devuelve None (el caller cae a save_page_pdf).

        PRE: el wizard está en RATES. POST: al retornar (éxito o None) queda en RATES.
        """
        from modules.progressive.pdf_downloader import download_progressive_pdf

        # `name` = basename final sin extensión (R-086: el caller lo arma con
        # quote_pdf_basename — fecha AAAA-MM-DD primero). Sin prefijos acá.
        out_path = Path(output_dir) / f"{name}.pdf"
        last_err = None
        for attempt in range(max_attempts):
            try:
                await self._ensure_on_rates()

                # 1) Print, Email, Fax -> PrintEmailFax
                await self.remove_overlays()
                await self.page.get_by_role(
                    "button", name="Print, Email, Fax"
                ).click(force=True, timeout=10_000)
                await self.wait_for_page("PrintEmailFax")
                await self.wait_for_extjs_idle()

                # 2) radio "Insurance Quote (with all bill plans)"
                await self.safe_radio(
                    self.page.get_by_role("radiogroup").first,
                    "Insurance Quote (with all bill plans)",
                )
                await self.wait_for_extjs_idle()

                # 3) checkbox "Print" -> revela "Print/Send"
                await self.safe_checkbox(
                    self.page.get_by_role("checkbox", name="Print", exact=True)
                )
                print_send = self.page.get_by_role("button", name="Print/Send")
                await print_send.wait_for(state="visible", timeout=10_000)

                # 4) Print/Send -> popup con el PDF inline
                await self.remove_overlays()
                async with self.page.context.expect_page(timeout=20_000) as popup_info:
                    await print_send.click(force=True, timeout=10_000)
                popup = await popup_info.value
                try:
                    await popup.wait_for_url("**/PDFHandler.ashx**", timeout=15_000)
                except Exception:
                    pass
                pdf_url = popup.url
                try:
                    await popup.close()
                except Exception:
                    pass
                if "PDFHandler.ashx" not in pdf_url:
                    raise RuntimeError(
                        f"popup URL no es un endpoint PDFHandler: {pdf_url[:120]}"
                    )

                # 5) fetch desde self.page (quedó en PrintEmailFaxConfirm, clpolicy)
                info = await download_progressive_pdf(self.page, pdf_url, out_path)
                print(
                    f"    [Progressive] PDF oficial: {info['size']} bytes -> {info['path']}"
                )

                # PDF ya en disco: éxito. Volver a RATES es BEST-EFFORT — un hipo de
                # navegación NO debe descartar un PDF ya descargado ni disparar un
                # re-download (por eso el ensure va acá dentro de su propio try, y se
                # devuelve el path pase lo que pase con la navegación).
                saved_path = str(out_path)
                try:
                    await self.remove_overlays()
                    await self.page.get_by_role(
                        "button", name="Return to quote"
                    ).click(force=True, timeout=10_000)
                    await self._ensure_on_rates()
                except Exception as e:
                    print(
                        f"    [Progressive] WARN: PDF descargado OK pero no se pudo "
                        f"volver a RATES limpio ({e})"
                    )
                return saved_path

            except Exception as e:
                last_err = e
                print(
                    f"    [Progressive] download_quote_pdf intento "
                    f"{attempt + 1}/{max_attempts} falló: {e}"
                )
                try:
                    await self._ensure_on_rates()
                except Exception:
                    pass

        print(
            f"    [Progressive] PDF oficial no descargado tras {max_attempts} "
            f"intentos ({last_err})"
        )
        try:
            await self._ensure_on_rates()
        except Exception:
            pass
        return None

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
            # Learn the REAL option list on failure (e.g. BI '$500,000 CSL'
            # kept falling back to '$1 million CSL' on DDH 2026-06-11 and we
            # still don't know what the dropdown actually offers).
            try:
                await combo.first.click(timeout=2_000)
                await self.wait_for_options_open()
                opts = await self._visible_boundlist_options()
                print(f"    [Progressive]   '{label}' options visible: {opts[:30]}")
                await self._close_open_boundlist()
            except Exception:
                pass
            self.warnings.append(
                f"rates: combobox '{label}' = '{option_text}' failed (kept prior value)"
            )

    async def _visible_boundlist_options(self) -> list:
        """Texts of the currently open ExtJS boundlist's visible options."""
        try:
            return await self.page.evaluate(
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
            return []

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
        """Expand a special coverage section if it is collapsed.

        The expander is NOT a client-side toggle: the title anchor runs
        DCT.Util.customOnClick('<X>_open') which does a Duck Creek SERVER
        round-trip before the section re-renders expanded (header HTML dump
        2026-06-11). wait_for_extjs_idle does NOT see that XHR (it watches
        Ext.Ajax), so the old click→quick-check→re-click loop kept toggling
        the server state back and forth and sections ended collapsed —
        silently skipping MTC/Non-Owned-Trailer config on some quotes.

        Correct interaction: ONE real click on the title anchor, then POLL
        the header state ('+\\n<name>' collapsed / '-\\n<name>…' expanded)
        for up to 8s. Never re-click while the round-trip may be in flight.

        Returns True if the section is expanded, False if the section is
        not on the page or would not open.
        """
        btn = self.page.get_by_role("button", name=name, exact=True)
        n = await btn.count()
        if n == 0:
            return False
        # The page keeps HIDDEN duplicates of these anchors (same pattern as
        # the trailer tiles); .first can land on one whose click times out
        # silently — always target the VISIBLE match.
        target = None
        for i in range(n):
            if await btn.nth(i).is_visible():
                target = btn.nth(i)
                break
        if target is None:
            print(
                f"    [Progressive] _expand_coverage('{name}'): {n} matches "
                f"but none visible"
            )
            return False

        state = await self._section_expand_state(name)
        if state == "expanded":
            # Cached open across same-USDOT quotes — clicking would COLLAPSE.
            return True

        for attempt in range(2):
            try:
                await target.click(timeout=5_000)
            except Exception as e:
                print(
                    f"    [Progressive] _expand_coverage('{name}'): click "
                    f"failed: {type(e).__name__}: {e}"
                )
            # Poll for the POSITIVE expanded signal through the DCT
            # round-trip (500ms × 16 = 8s budget, exits as soon as it lands).
            for _ in range(16):
                await self.page.wait_for_timeout(500)
                state = await self._section_expand_state(name)
                if state == "expanded":
                    return True

        print(
            f"    [Progressive] _expand_coverage('{name}'): header still "
            f"collapsed after 2 click+poll attempts"
        )
        await self._dump_section_labels(name.split()[0])
        await self.screenshot(f"expand_{name.replace(' ', '_').lower()}_failed")
        return False

    async def _section_expand_state(self, name: str) -> str:
        """'collapsed' | 'expanded' | 'unknown' for a coverage section header.

        Live DOM 2026-06-11: the header container's innerText is exactly
        '+\\n<name>' while collapsed and starts with '-\\n<name>' once open.
        'unknown' covers mid-re-render moments (Duck Creek replaces the
        section DOM after its XHR) and evaluation failures.
        """
        try:
            return await self.page.evaluate(
                """(name) => {
                    const els = Array.from(document.querySelectorAll(
                        'div, span, a, button'
                    )).filter(el => el.offsetParent !== null);
                    for (const el of els) {
                        const t = (el.innerText || '').trim();
                        if (t === '+\\n' + name || t === '+ ' + name) {
                            return 'collapsed';
                        }
                        if (t.startsWith('-\\n' + name) || t.startsWith('- ' + name)) {
                            return 'expanded';
                        }
                    }
                    return 'unknown';
                }""",
                name,
            )
        except Exception:
            return "unknown"

    async def _recalculate_if_needed(self, *, max_attempts: int = 3) -> None:
        """Click Recalculate and POLL until the page shows a real premium.

        Live RYD 2026-06-03 run CA117053983 showed: after setting MTC
        commodity + limit, clicking Recalculate was logged but the page
        STILL showed '$******' + 'The coverages have changed, please
        recalculate to see your rate.' even after 30s networkidle +
        15s extjs_idle. Capture_price then read '$******' (no premium).

        Root cause: 'Done with this coverage' (which collapses MTC) and
        Recalculate compete on the ExtJS event queue. If Recalculate
        fires while Done is still propagating state, Progressive
        re-flags 'coverages changed' AFTER our click, leaving the page
        stuck.

        Fix: click Recalculate, then poll for either
          - a '$X,XXX.XX per year' pattern to APPEAR, OR
          - the 'please recalculate' message to DISAPPEAR.
        If neither happens within 20s, re-click Recalculate (up to
        max_attempts total).
        """
        btn = self.page.get_by_role("button", name="Recalculate")
        if await btn.count() == 0:
            return

        for attempt in range(1, max_attempts + 1):
            print(f"    [Progressive] Recalculating premium (attempt {attempt}/{max_attempts})...")
            try:
                # Re-resolve in case DOM changed since previous attempt
                btn_now = self.page.get_by_role("button", name="Recalculate")
                if await btn_now.count() == 0:
                    print("    [Progressive] Recalculate button no longer visible — assuming done")
                    return
                await btn_now.last.click(timeout=10_000)
            except Exception as e:
                print(f"    [Progressive] WARN: Recalculate click attempt {attempt}: {e}")

            try:
                await self.page.wait_for_load_state("networkidle", timeout=30_000)
            except Exception:
                pass
            try:
                await self.wait_for_extjs_idle(timeout_ms=15_000)
            except Exception as e:
                print(f"    [Progressive] WARN: wait_for_extjs_idle after recalc: {e}")

            # Poll for actual premium to APPEAR OR 'please recalculate' to DISAPPEAR
            try:
                await self.page.wait_for_function(
                    """() => {
                        const text = document.body.innerText || '';
                        // Real premium found?
                        const hasPremium = /\\$[\\d,]+\\.\\d{2}\\s*(per year|annual)/i.test(text);
                        // Still asking to recalculate?
                        const stillNeedsRecalc = /please\\s*['\\"]?recalculate['\\"]?\\s*to see your rate/i.test(text);
                        return hasPremium || !stillNeedsRecalc;
                    }""",
                    timeout=20_000,
                )
                print(f"    [Progressive] Recalculate completed (attempt {attempt})")
                return
            except Exception:
                if attempt < max_attempts:
                    print(f"    [Progressive] Recalc still pending after attempt {attempt}; retrying")
                    await self.page.wait_for_timeout(1_500)
                else:
                    print(
                        f"    [Progressive] WARN: premium did not materialize after "
                        f"{max_attempts} recalc attempts; capture_price will likely fail"
                    )

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
        await self.page.wait_for_timeout(300)  # cushion for non-ajax animations

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
            decision_ledger.record(f"MTC: {label_hint}", answer,
                                   page="Coverages/RATES", source="DEFAULT",
                                   rule_id="R-034")
            try:
                await self.safe_radio(group, answer)
            except Exception as e:
                print(f"    [Progressive] WARN: MTC '{label_hint}' radio failed: {e}")
            try:
                await self.wait_for_extjs_idle(timeout_ms=5_000)
            except Exception:
                pass
            await self.page.wait_for_timeout(200)

        # NOTE: a verbose MTC DIAGNOSTIC (labels/comboboxes/buttons/radios)
        # was here during initial Beverage-Distributor subform discovery
        # and is now emitted ONLY on the failure path (see the WARN at the
        # bottom of this method). The 'mtc_after_expansion' screenshot is
        # still saved for post-mortem if needed.
        await self.screenshot("mtc_after_expansion")

        # MTC configuration logic. Two paths share the SAME final step (set limit),
        # but the Distributor path adds a commodity FIRST which then reveals the
        # limit combobox.
        #
        #   Trucker path     → limit combobox visible from the start, no commodities
        #   Distributor path → commodity picker visible; after selecting a commodity,
        #                      Progressive reveals the limit combobox as required
        #
        # Verified via screenshot logs/progressive_rates_before_capture.png on
        # 2026-06-03 — after committing a Food & Beverage / Other Food & Beverages
        # row, "Motor Truck Cargo coverage limit" appears with a red "This field
        # is required" marker. Without setting it, recalc returns no premium.

        limit_combo = self.page.get_by_role(
            "combobox", name="Motor Truck Cargo coverage limit"
        )
        add_commodity = self.page.get_by_text("Add a commodity", exact=False)

        # Step A: if the Distributor commodity picker is visible, add a commodity.
        # The limit combobox is hidden until at least one commodity is committed.
        if await self.field_exists(add_commodity, wait_ms=1_500):
            await self._add_mtc_commodities()
            # After commit, wait for Progressive to render the now-required
            # limit combobox (the limit lookup downstream has its own poll).
            try:
                await self.wait_for_extjs_idle(timeout_ms=5_000)
            except Exception:
                pass
            await self.page.wait_for_timeout(200)

        # Step B: set the limit combobox (Trucker path had it from the start;
        # Distributor path just had it revealed).
        #
        # Live RYD run 2026-06-03 (CA117053870) showed Progressive's actual
        # option list uses "k" notation + combined deductible:
        #   '$5k with a $500 Deductible', '$5k with a $1,000 Deductible',
        #   '$10k with a $500 Deductible', ...,
        #   '$100k with a $1,000 Deductible', '$100k with a $2,500 Deductible',
        #   ..., '$250k with a $2,500 Deductible'
        # So an input of "$100,000" must be translated to "$100k" and matched
        # against the deductible variants. Preferences in cascade: exact with
        # $1,000 deductible (standard), exact with $2,500 deductible, then
        # partial "$Xk with a", then bare "$Xk", then the original input.
        if await self.field_exists(limit_combo, wait_ms=2_000):
            chosen_limit = await self._select_mtc_limit(limit_combo, limit)
            if not chosen_limit:
                msg = (
                    f"could not set Motor Truck Cargo limit "
                    f"(requested {limit!r}) — premium will NOT materialize "
                    f"while the limit is unset"
                )
                print(f"    [Progressive] WARN: {msg}")
                self.warnings.append(f"rates: {msg}")
        else:
            print(
                "    [Progressive] WARN: MTC limit combobox still not visible "
                "after commodity flow; quote will lack MTC limit"
            )
            print(
                "    [Progressive]   Screenshot saved at "
                "logs/progressive_mtc_after_expansion.png"
            )
            # Emit the DOM dump only on this failure path so the operator
            # can diagnose subform shape changes without verbose logs on
            # the happy path.
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
                        const dedupe = arr => [...new Set(arr)].slice(0, 30);
                        return {labels: dedupe(out.labels), comboboxes: dedupe(out.comboboxes)};
                    }"""
                )
                print(f"    [Progressive]   visible labels: {nearby.get('labels', [])[:20]}")
                print(f"    [Progressive]   visible comboboxes: {nearby.get('comboboxes', [])}")
            except Exception:
                pass
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
        await self.page.wait_for_timeout(300)

        # Save a screenshot of the inline form for debugging
        await self.screenshot("mtc_commodity_dialog")

        # Step 1: locate the Commodity Type (category) combo input.
        # Sencha ExtJS may render the visible placeholder as either:
        #   - the input's `placeholder` attribute (HTML5)
        #   - an emptyText overlay (separate element, not the input)
        #   - the input's `value` (older Sencha)
        # We try 3 strategies in order so we don't depend on a single DOM shape.
        category_input = await self._locate_commodity_combo_input(
            label_text="Commodity Type:",
            placeholder_text="Select category",
        )
        if category_input is None:
            print("    [Progressive] WARN: MTC 'Select category' input not located by any strategy")
            await self._dump_inline_form_dom("mtc_commodity_form_dom")
            return

        category_preferences = [
            "Food", "Beverage", "Drink", "Water",
            "Wholesale", "Retail", "Grocery",
            "Pet", "Animal",
            "General", "Other",
        ]
        chosen_category = await self._pick_first_combo_option(
            category_input, category_preferences, label="Commodity Type",
            commodity=getattr(self, "_commodity", None),
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
        await self.page.wait_for_timeout(200)

        commodity_input = await self._locate_commodity_combo_input(
            label_text="Commodity:",
            placeholder_text="Select commodity",
        )
        if commodity_input is None:
            print("    [Progressive] WARN: MTC 'Select commodity' input not located by any strategy")
            await self._dump_inline_form_dom("mtc_commodity_form_dom_after_category")
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
            commodity_input, commodity_preferences, label="Commodity",
            commodity=getattr(self, "_commodity", None),
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
        await self.page.wait_for_timeout(300)
        print(f"    [Progressive] MTC commodity row committed: {chosen_category!r} / {chosen_commodity!r}")

    async def _click_boundlist_option(self, opt_text: str, *, label: str) -> bool:
        """Click an ExtJS x-boundlist option by its exact text. Returns success."""
        try:
            opt = self.page.get_by_role("option", name=opt_text, exact=True).first
            if not await self.field_exists(opt, wait_ms=500):
                opt = self.page.locator(
                    f"li.x-boundlist-item:has-text({opt_text!r})"
                ).first
            await opt.click(timeout=3_000)
            print(f"    [Progressive] {label} selected: {opt_text!r}")
            return True
        except Exception as e:
            print(f"    [Progressive] {label} option click failed for {opt_text!r}: {e}")
            return False

    async def _pick_first_combo_option(
        self, combo_input, preferences: list, *, label: str,
        commodity: Optional[str] = None,
    ) -> Optional[str]:
        """Open an ExtJS combo, enumerate visible options, and select one.

        Selection order: (1) AI classification of `commodity` against the real
        option list (when commodity is provided) — maps free-text cargo like
        'SCRAP METAL 100%' to 'Metals/ Minerals/ Coal' even with no keyword
        overlap; (2) the first option matching a `preferences` keyword (the
        validated fallback, e.g. RYD beverage path). Returns the selected text
        or None.
        """
        try:
            await combo_input.click(timeout=3_000)
        except Exception:
            try:
                await combo_input.click(timeout=3_000, force=True)
            except Exception as e:
                print(f"    [Progressive] WARN: {label} combo click failed: {e}")
                return None
        await self.wait_for_options_open()

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

        # (1) AI-first: map the Blue-Quote commodity to the best real option.
        if commodity and visible_options:
            from modules.progressive.business_type_classifier import ai_pick_from_options
            dtype = "mtc_" + label.strip().lower().replace(" ", "_")  # mtc_commodity_type / mtc_commodity
            ai_choice = ai_pick_from_options(commodity, visible_options, decision_type=dtype)
            if ai_choice and await self._click_boundlist_option(ai_choice, label=f"{label} (ai)"):
                return ai_choice

        # (2) Fallback: first preference keyword that matches (case-insensitive).
        for pref in preferences:
            pref_lower = pref.lower()
            for opt_text in visible_options:
                if pref_lower in opt_text.lower():
                    if await self._click_boundlist_option(opt_text, label=label):
                        return opt_text
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
        await self.wait_for_options_open()

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

    async def _select_mtc_limit(self, combo_input, requested: str) -> Optional[str]:
        """Pick the MTC limit option that COVERS the requested amount.

        Progressive only offers fixed tiers ('$5k…$250k with a $X Deductible')
        but Blue Quotes can request any amount (live WHITE CASTLE 2026-06-11:
        'Others: $30,000' — no $30k tier exists). Exact tier wins; otherwise
        snap UP to the smallest tier that covers the request (the limit must
        cover the cargo value), preferring the standard $1,000 deductible.
        Falls back to the legacy preference cascade when the requested string
        has no parseable amount.
        """
        amount = self._parse_dollar_amount(requested)
        if amount is None:
            prefs = self._build_mtc_limit_preferences(requested)
            return await self._pick_first_combo_option(
                combo_input, prefs, label="Motor Truck Cargo limit"
            )

        try:
            await combo_input.click(timeout=3_000)
        except Exception:
            try:
                await combo_input.click(timeout=3_000, force=True)
            except Exception as e:
                print(f"    [Progressive] WARN: MTC limit combo click failed: {e}")
                return None
        await self.wait_for_options_open()

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
        print(f"    [Progressive] Motor Truck Cargo limit options visible: {visible_options[:30]}")

        chosen = self._choose_mtc_limit_option(visible_options, amount)
        if not chosen:
            await self._close_open_boundlist()
            return None

        chosen_text, chosen_value = chosen
        if chosen_value != amount:
            msg = (
                f"MTC limit ${amount:,} not offered by Progressive — "
                f"snapped to {chosen_text!r}"
            )
            print(f"    [Progressive] {msg}")
            self.warnings.append(f"rates: {msg}")

        try:
            opt = self.page.locator(
                f"li.x-boundlist-item:has-text({chosen_text!r})"
            ).first
            await opt.click(timeout=3_000)
            print(f"    [Progressive] Motor Truck Cargo limit selected: {chosen_text!r}")
            return chosen_text
        except Exception as e:
            print(f"    [Progressive] WARN: MTC limit option click failed: {e}")
            return None

    @staticmethod
    def _choose_mtc_limit_option(options: list, amount: int):
        """From '$Xk with a $Y Deductible' options, pick the tier covering
        `amount`: smallest value >= amount (or the largest available when
        nothing covers it), preferring deductible $1,000 > $2,500 > $500.
        Returns (option_text, option_value_dollars) or None.
        """
        import re
        parsed = []
        for opt in options:
            m = re.match(r"\$(\d+)k with a \$([\d,]+) Deductible", opt)
            if m:
                parsed.append(
                    (int(m.group(1)) * 1000, int(m.group(2).replace(",", "")), opt)
                )
        if not parsed:
            return None

        covering = [p for p in parsed if p[0] >= amount]
        best_value = (
            min(p[0] for p in covering) if covering else max(p[0] for p in parsed)
        )
        ded_rank = {1000: 0, 2500: 1, 500: 2}
        candidates = sorted(
            (p for p in parsed if p[0] == best_value),
            key=lambda p: ded_rank.get(p[1], 9),
        )
        return candidates[0][2], candidates[0][0]

    @staticmethod
    def _parse_dollar_amount(s: str):
        """'$30.000' / '$100,000' / '100000' / '$100k' → int dollars, else None.

        Dots and commas are both treated as thousands separators (Blue Quotes
        are often handwritten with either).
        """
        import re
        if not s:
            return None
        m = re.search(r"\$?\s*(\d[\d.,]*)\s*([kK])?", s)
        if not m:
            return None
        digits = m.group(1).replace(",", "").replace(".", "")
        try:
            n = int(digits)
        except ValueError:
            return None
        if m.group(2):
            n *= 1000
        return n or None

    @staticmethod
    def _build_mtc_limit_preferences(limit: str) -> list:
        """Convert a dollar-amount limit like '$100,000' into the cascading
        preference list used to match Progressive's MTC limit dropdown.

        Progressive's option format is '$Xk with a $Y Deductible' where Y is
        either $500, $1,000, or $2,500. We prefer $1,000 (standard) then
        $2,500, then any partial match. Falls back to the original string
        as a last resort (covers Trucker path which may use different format).
        """
        import re
        m = re.match(r"\$?([\d,]+)", limit or "")
        if not m:
            return [limit]
        digits = m.group(1).replace(",", "")
        try:
            n = int(digits)
        except ValueError:
            return [limit]
        k = n // 1000 if n >= 1000 else n
        k_form = f"${k}k"
        return [
            f"{k_form} with a $1,000 Deductible",
            f"{k_form} with a $2,500 Deductible",
            f"{k_form} with a $500 Deductible",
            f"{k_form} with a",  # partial — first match wins (typically $500 or $1,000)
            k_form,              # very partial ("$100k")
            limit,               # original input ("$100,000")
        ]

    async def _locate_commodity_combo_input(
        self, *, label_text: str, placeholder_text: str
    ):
        """Locate a combobox input by trying 3 strategies in order:

        1. Visible placeholder text overlay (click target = the text node)
        2. XPath traversal from the section label (most robust)
        3. Case-insensitive partial placeholder attribute match

        Returns a Locator if found and visible, None otherwise. Each strategy
        logs which one succeeded so we learn the actual DOM shape for next time.
        """
        # Strategy 1: click the visible placeholder text directly
        text_node = self.page.get_by_text(placeholder_text, exact=True).first
        if await self.field_exists(text_node, wait_ms=800):
            print(f"    [Progressive] commodity combo located via visible text: {placeholder_text!r}")
            return text_node

        # Strategy 2: XPath traversal from the section label
        # We use the EXACT match on the label, then walk to the next input
        # or any combobox-shaped element.
        label_loc = self.page.get_by_text(label_text, exact=False).first
        if await self.field_exists(label_loc, wait_ms=600):
            traversed = label_loc.locator(
                "xpath=following::input[@type='text' or not(@type)][1] | "
                "following::*[@role='combobox'][1]"
            ).first
            if await self.field_exists(traversed, wait_ms=800):
                print(f"    [Progressive] commodity combo located via label traversal from {label_text!r}")
                return traversed

        # Strategy 3: case-insensitive partial placeholder attribute
        key_word = placeholder_text.split()[-1]  # "category" or "commodity"
        partial = self.page.locator(f'input[placeholder*="{key_word}" i]').first
        if await self.field_exists(partial, wait_ms=600):
            print(f"    [Progressive] commodity combo located via partial placeholder: '*{key_word}*'")
            return partial

        # Strategy 4: original exact placeholder (kept for completeness)
        exact_ph = self.page.locator(f'input[placeholder="{placeholder_text}"]').first
        if await self.field_exists(exact_ph, wait_ms=400):
            print(f"    [Progressive] commodity combo located via exact placeholder: {placeholder_text!r}")
            return exact_ph

        return None

    async def _dump_inline_form_dom(self, label: str) -> None:
        """Dump the FULL inline commodity-form DOM to stdout for diagnostic.

        Called when no strategy finds the combo inputs — gives us the actual
        DOM shape so we can fix in a single iteration.
        """
        try:
            info = await self.page.evaluate(
                """() => {
                    // Find the commodity form container: look for the panel
                    // containing the 'Commodity Type:' label.
                    const labels = Array.from(document.querySelectorAll('label, .x-form-item-label, div, span'))
                        .filter(el => (el.innerText || '').trim() === 'Commodity Type:' && el.offsetParent !== null);
                    const container = labels.length > 0 ? labels[0].closest('.x-panel, .x-container, fieldset, form') || labels[0].parentElement : document.body;
                    const inputs = Array.from(container.querySelectorAll('input, [role="combobox"], select'))
                        .filter(el => el.offsetParent !== null)
                        .map(el => ({
                            tag: el.tagName.toLowerCase(),
                            type: el.getAttribute('type') || '',
                            role: el.getAttribute('role') || '',
                            placeholder: el.getAttribute('placeholder') || '',
                            ariaLabel: el.getAttribute('aria-label') || '',
                            ariaLabelledby: el.getAttribute('aria-labelledby') || '',
                            name: el.getAttribute('name') || '',
                            id: el.id || '',
                            className: el.className || '',
                            value: (el.value || '').slice(0, 40),
                        }));
                    const visibleTexts = Array.from(container.querySelectorAll('label, span, div'))
                        .filter(el => el.offsetParent !== null && el.children.length === 0)
                        .map(el => (el.innerText || '').trim())
                        .filter(t => t.length > 0 && t.length < 60)
                        .slice(0, 30);
                    return {inputs, visibleTexts};
                }"""
            )
            print(f"    [Progressive] {label} INPUTS:")
            for inp in info.get("inputs", [])[:15]:
                print(f"    [Progressive]   {inp}")
            print(f"    [Progressive] {label} VISIBLE TEXTS: {info.get('visibleTexts', [])}")
        except Exception as e:
            print(f"    [Progressive] {label} dump failed: {e}")

    async def _configure_trailer_interchange(self, limit: str) -> None:
        """Fill the Trailer Interchange subform.

        First live mapping 2026-06-11 (BQ field 159: LEZAMA '$20.000',
        WHITE CASTLE '$50.000'). The subform shape is still being learned —
        dump it on every run until the limit control is confirmed; if its
        options use the '$Xk with a $Y Deductible' tier format, snap UP to
        the covering tier like the MTC limit.
        """
        print(f"    [Progressive] Configuring Trailer Interchange: {limit}")
        expanded = await self._expand_coverage("Trailer Interchange")
        if not expanded:
            msg = "could not expand Trailer Interchange section"
            print(f"    [Progressive] WARN: {msg}")
            self.warnings.append(f"rates: {msg}")
            return

        # Cascading gate questions (live LEZAMA 2026-06-11): Yes on 'Does the
        # customer have an interchange agreement…' reveals 'Does the customer
        # agree to furnish a copy…', which reveals the trailer count. EACH
        # reveal is a DCT SERVER round-trip that settle_extjs cannot see —
        # poll for the next control instead of checking once (the furnish
        # gate was missed by a single check on the 4th LEZAMA run).
        group = await self.find_radiogroup(
            "interchange agreement requiring", exact=False
        )
        if await group.count() > 0:
            try:
                await self.safe_radio(group, "Yes")
                print("    [Progressive] Trailer Interchange agreement: Yes")
                decision_ledger.record(
                    "Trailer Interchange: interchange agreement", "Yes",
                    page="Coverages/RATES", source="DEFAULT", rule_id="R-037")
            except Exception as e:
                msg = f"Trailer Interchange agreement radio failed: {e}"
                print(f"    [Progressive] WARN: {msg}")
                self.warnings.append(f"rates: {msg}")
                return

        furnish = await self._poll_until_found(
            lambda: self.find_radiogroup("furnish a copy", exact=False)
        )
        if furnish is not None:
            try:
                await self.safe_radio(furnish, "Yes")
                print("    [Progressive] Trailer Interchange furnish copy: Yes")
                decision_ledger.record(
                    "Trailer Interchange: furnish copy of agreement", "Yes",
                    page="Coverages/RATES", source="DEFAULT", rule_id="R-037")
            except Exception as e:
                msg = f"Trailer Interchange 'furnish copy' radio failed: {e}"
                print(f"    [Progressive] WARN: {msg}")
                self.warnings.append(f"rates: {msg}")
                return
        else:
            print(
                "    [Progressive] Trailer Interchange: 'furnish copy' gate "
                "did not appear within poll window — continuing"
            )

        # Post-gates the section asks 'Number of Non-Owned Trailers' (how
        # many non-owned trailers are interchanged — live LEZAMA 2026-06-11).
        # The Blue Quote only carries the TI LIMIT, not this count: default
        # to 1 (the minimum that activates the coverage) and surface it for
        # human review. NOTE: the Non-Owned Trailer Phys Damage section has
        # an identically-labeled field; TI renders EARLIER in the DOM, and
        # that section is configured while TI is still collapsed, so .first
        # resolves correctly in both directions.
        count_combo = await self._poll_until_found(
            lambda: self.find_combo("Number of Non-Owned Trailers", exact=False)
        )
        if count_combo is not None:
            try:
                await self.safe_select_combo(count_combo.first, "1")
                decision_ledger.record(
                    "Trailer Interchange: number of interchanged trailers",
                    "1", page="Coverages/RATES", source="DEFAULT",
                    rule_id="R-038", note="no viene en el BlueQuote")
                msg = (
                    "Trailer Interchange: number of interchanged trailers "
                    "defaulted to 1 (not in the Blue Quote) — review if the "
                    "customer interchanges more"
                )
                print(f"    [Progressive] {msg}")
                self.warnings.append(f"rates: {msg}")
            except Exception as e:
                msg = f"Trailer Interchange trailer count failed: {e}"
                print(f"    [Progressive] WARN: {msg}")
                self.warnings.append(f"rates: {msg}")
                return
            await self.settle_extjs()

        # Learning dump: capture what the section contains at this point.
        await self._dump_section_labels("Trailer Interchange")

        # The limit combo is revealed by the count's own DCT round-trip.
        combo = await self._poll_until_found(
            lambda: self.find_combo("Trailer Interchange", exact=False)
        )
        if combo is None:
            msg = "Trailer Interchange limit control not found (see DIAG labels)"
            print(f"    [Progressive] WARN: {msg}")
            self.warnings.append(f"rates: {msg}")
            await self.screenshot("trailer_interchange_section")
            return

        try:
            await combo.first.click(timeout=3_000)
        except Exception as e:
            print(f"    [Progressive] WARN: Trailer Interchange combo click failed: {e}")
            return
        await self.wait_for_options_open()
        opts = await self._visible_boundlist_options()
        print(f"    [Progressive] Trailer Interchange options visible: {opts[:30]}")

        amount = self._parse_dollar_amount(limit)
        chosen = self._choose_mtc_limit_option(opts, amount) if amount else None
        if not chosen:
            await self._close_open_boundlist()
            msg = (
                f"Trailer Interchange limit {limit!r} could not be matched "
                f"against the live options (logged above)"
            )
            print(f"    [Progressive] WARN: {msg}")
            self.warnings.append(f"rates: {msg}")
            return

        chosen_text, chosen_value = chosen
        if amount and chosen_value != amount:
            msg = (
                f"Trailer Interchange limit ${amount:,} not offered — "
                f"snapped to {chosen_text!r}"
            )
            print(f"    [Progressive] {msg}")
            self.warnings.append(f"rates: {msg}")
        try:
            opt = self.page.locator(
                f"li.x-boundlist-item:has-text({chosen_text!r})"
            ).first
            await opt.click(timeout=3_000)
            print(f"    [Progressive] Trailer Interchange limit selected: {chosen_text!r}")
        except Exception as e:
            print(f"    [Progressive] WARN: Trailer Interchange option click failed: {e}")
            return
        await self.settle_extjs()

        done = self.page.get_by_role("button", name="Done with this coverage")
        if await done.count() > 0:
            await done.first.click(timeout=5_000)
            await self.wait_for_extjs_idle()

    async def _poll_until_found(self, finder, *, timeout_ms: int = 8_000):
        """Poll an async locator finder until it has matches, else None.

        Duck Creek reveals follow-up controls via SERVER round-trips that
        Ext.Ajax-based waits cannot observe — a single existence check after
        settle_extjs races the reveal (live TI 'furnish copy' gate,
        2026-06-11). 500ms cadence, same budget shape as _expand_coverage.
        """
        elapsed = 0
        while True:
            loc = await finder()
            if await loc.count() > 0:
                return loc
            if elapsed >= timeout_ms:
                return None
            await self.page.wait_for_timeout(500)
            elapsed += 500

    async def _dump_section_labels(self, fragment: str) -> None:
        """DIAG: print visible form labels + texts containing `fragment`.

        Used when an expected control is missing so the run log captures the
        REAL labels/structure of the section (instead of a blind WARN).
        """
        try:
            info = await self.page.evaluate(
                """(frag) => {
                    const vis = el => el.offsetParent !== null;
                    const labels = Array.from(document.querySelectorAll(
                        'label, .x-form-item-label'
                    )).filter(vis)
                      .map(el => (el.innerText || '').trim())
                      .filter(t => t.length > 0);
                    const matches = Array.from(document.querySelectorAll(
                        'span, div, label, legend'
                    )).filter(el => vis(el)
                          && (el.innerText || '').includes(frag)
                          && el.innerText.trim().length < 120)
                      .map(el => el.innerText.trim());
                    return {
                        labels: [...new Set(labels)].slice(0, 40),
                        matches: [...new Set(matches)].slice(0, 20),
                    };
                }""",
                fragment,
            )
            print(f"    [Progressive] DIAG visible form labels: {info.get('labels')}")
            print(f"    [Progressive] DIAG texts containing '{fragment}': {info.get('matches')}")
        except Exception as e:
            print(f"    [Progressive] DIAG label dump failed: {e}")

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

    async def _configure_non_owned_trailer_phys_damage(
        self, limit: str, count: int = 1
    ) -> None:
        """Fill Non-Owned Trailer Physical Damage subform.

        The expanded section asks for 'Number of Non-Owned Trailers' (live
        DOM 2026-06-11) — there is NO standalone 'coverage limit' combobox
        at this level. Fill the count, then configure whatever control the
        count reveals (dumped to the log while we learn this subform).
        """
        print(
            f"    [Progressive] Configuring Non-Owned Trailer Physical Damage: "
            f"{limit} ({count} trailer(s))"
        )
        expanded = await self._expand_coverage("Non-Owned Trailer Physical Damage")
        if not expanded:
            msg = "could not expand Non-Owned Trailer Physical Damage section"
            print(f"    [Progressive] WARN: {msg}")
            self.warnings.append(f"rates: {msg}")
            return

        count_combo = await self.find_combo(
            "Number of Non-Owned Trailers", exact=False
        )
        if await count_combo.count() > 0:
            try:
                await self.safe_select_combo(count_combo.first, str(count))
                print(
                    f"    [Progressive] Number of Non-Owned Trailers = {count}"
                )
            except Exception as e:
                msg = f"Number of Non-Owned Trailers = {count} failed: {e}"
                print(f"    [Progressive] WARN: {msg}")
                self.warnings.append(f"rates: {msg}")
        else:
            field = await self.find_by_label_text("Number of Non-Owned Trailers")
            if await self.field_exists(field, wait_ms=1_500):
                await self.safe_fill(field, str(count))
                print(
                    f"    [Progressive] Number of Non-Owned Trailers = {count} "
                    f"(textbox)"
                )
            else:
                msg = "'Number of Non-Owned Trailers' control not found"
                print(f"    [Progressive] WARN: {msg}")
                self.warnings.append(f"rates: {msg}")
                await self._dump_section_labels("Non-Owned")
                await self.screenshot("non_owned_trailer_section")
                return
        await self.settle_extjs()

        # Learning dump: see what the count reveals (a limit control? a
        # per-trailer value?) so the next iteration can configure it.
        await self._dump_section_labels("Non-Owned")

        done = self.page.get_by_role("button", name="Done with this coverage")
        if await done.count() > 0:
            await done.first.click(timeout=5_000)
            print("    [Progressive] Non-Owned Trailer: 'Done with this coverage' clicked")
            # Wait for ExtJS to collapse the subform after Done
            await self.wait_for_extjs_idle()
        else:
            print(
                "    [Progressive] Non-Owned Trailer: no 'Done with this "
                "coverage' button (value commits on select)"
            )

        # Log the section row as displayed — shows whether Progressive
        # actually CHARGES for this coverage (premium did not move when the
        # count was first filled on WHITE CASTLE 2026-06-11).
        try:
            row_text = await self.page.evaluate(
                """() => {
                    const els = Array.from(document.querySelectorAll('div, span'))
                        .filter(el => el.offsetParent !== null);
                    const el = els.find(el => {
                        const t = (el.innerText || '').trim();
                        return t.startsWith('-\\nNon-Owned Trailer Physical Damage')
                            || t.startsWith('+\\nNon-Owned Trailer Physical Damage');
                    });
                    return el ? el.innerText.trim().slice(0, 200) : null;
                }"""
            )
            print(f"    [Progressive] Non-Owned Trailer section row: {row_text!r}")
        except Exception:
            pass
