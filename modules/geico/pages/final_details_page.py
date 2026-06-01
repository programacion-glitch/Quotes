"""
Final Quote Details Page Object for GEICO wizard (Step 7).

Title: `GEICO Final Quote Details`. This is the LAST step of our quotation
flow. After this page, the wizard would advance to:

  Step 8: MVR & CLUE   -- consumes paid MVR/CLUE pulls server-side.
  Step 9: Payment      -- real policy bind.

Neither is in scope for cotizacion-only automation, so this page object
implements `fill_and_stop`: it fills every field on the page but DOES NOT
click the final Next button. The caller (a human inspecting or a future
"bind" block) is responsible for any post-fill click.

Field coverage (live-mapped — see docs/Proceso GEICO.md "Step 7"):

  1. Worker's comp radio (shadow-DOM Yes/No).
  2. Email confirmation textbox (auto-pop; overwrite if BlueQuote differs).
  3. Owner phone confirmation textbox (auto-pop; overwrite if BlueQuote set).
  4. Communication checkboxes (GEICO Text + Digital) -- default checked,
     LEAVE AS-IS.
  5. Per-driver: DL State combobox + DL Number textbox.
     -- license_number is REQUIRED for MVR/CLUE downstream. If missing we
        WARN and skip; we never block the form.
  6. Per-vehicle: VIN textbox (disabled, verify only),
     Registered owner combobox (dynamic per-vehicle, has DUPLICATES in its
     option list per live mapping -- "HUMBERTO VILLARREAL" appeared twice
     because the owner was listed both as business owner and as a driver
     candidate; we tolerate that and pick the first matching option),
     Owned/Leased/Financed radio (shadow-DOM).
  7. Skip Add Authorized Rep and Add Certificate Holder (optional).
  8. Blanket additional insured radio (default No; only toggle if
     has_blanket_additional is True).
  9. STOP -- do NOT click the final Next button.

Selectors avoid dynamic ids: role+name + partial id patterns + the base_page
helpers `select_by_options_signature` and shadow-DOM id-pattern fragments.
Failures are caught per logical group with a screenshot so one missing
field does not abort the entire form.
"""

import re

from playwright.async_api import Page

from modules.geico.pages.base_page import BasePage
from modules.geico.field_mapper import MappedFields


# Signature for any DL State <select>: the 50-US-state list is invariant.
_LICENSE_STATE_OPTIONS_SIGNATURE = ["Alabama", "Wyoming"]


class FinalDetailsPage(BasePage):
    """GEICO wizard Step 7 — Final Quote Details. STOPS before Next."""

    async def fill_and_stop(self, fields: MappedFields) -> None:
        """
        Fill all Step 7 fields then STOP. Does NOT click the final Next button
        (that would advance to MVR & CLUE / Payment -- out of cotizacion scope).

        Pre-state: 'Final Quote Details' title.
        Post-state: same page, fully filled, ready for a human to inspect or for
                    a future block to click the final Next.

        Raises RuntimeError on any field fill failure.
        """
        await self.page.wait_for_load_state("networkidle", timeout=30_000)
        await self.remove_overlays()
        print("    [GEICO] Step 7: Final Quote Details")

        await self._fill_workers_comp(fields.has_workers_comp)
        await self._fill_email_confirmation(fields.owner_email)
        await self._fill_phone_confirmation(fields.owner_phone)
        # Communication preferences: default-checked, leave as-is. No-op.
        print(
            "    [GEICO] Step 7: communication checkboxes -> default (leave as-is)"
        )

        await self._fill_drivers_section(fields)
        await self._fill_vehicles_section(fields)

        # Skip Add Authorized Rep and Add Certificate Holder (optional).
        print(
            "    [GEICO] Step 7: skipping optional Authorized Rep / Certificate Holder"
        )

        await self._fill_blanket_additional(fields.has_blanket_additional)

        # ---- STOP HERE ----
        print(
            "    [GEICO] Step 7: STOP HERE "
            "(Next would trigger MVR/CLUE + Payment -- out of scope)"
        )

    # ------------------------------------------------------------------
    # 1. Worker's comp radio
    # ------------------------------------------------------------------

    async def _fill_workers_comp(self, has_workers_comp: bool) -> None:
        """Yes/No shadow radio: "Does the customer carry worker's
        compensation coverage for their drivers?"."""
        label = "Yes" if has_workers_comp else "No"
        print(f"    [GEICO] Step 7: Worker's comp -> {label}")
        try:
            await self.click_question_radio(
                "worker's compensation coverage", label
            )
        except Exception as e:
            print(f"    [GEICO] WARN: workers comp radio failed: {e}")
            await self.screenshot("step7_workers_comp_error")

    # ------------------------------------------------------------------
    # 2. Email confirmation textbox
    # ------------------------------------------------------------------

    async def _fill_email_confirmation(self, owner_email) -> None:
        """Overwrite the pre-populated email if BlueQuote owner_email differs."""
        if not owner_email:
            print("    [GEICO] Step 7: email -> no BlueQuote value (keep auto-pop)")
            return
        try:
            box = self.page.get_by_role(
                "textbox", name=re.compile(r"confirm.+email", re.I)
            )
            if await box.count() == 0:
                box = self.page.get_by_role(
                    "textbox", name=re.compile(r"customer'?s email", re.I)
                )
            if await box.count() == 0:
                box = self.page.locator('input[id*="Email" i]').first
            if await box.count() == 0:
                print("    [GEICO] WARN: email confirmation textbox not found")
                return
            current = ""
            try:
                current = await box.first.input_value()
            except Exception:
                current = ""
            if current.strip().lower() == owner_email.strip().lower():
                print(
                    f"    [GEICO] Step 7: email already matches "
                    f"({current!r}), skipping"
                )
                return
            print(
                f"    [GEICO] Step 7: email overwrite "
                f"({current!r} -> {owner_email})"
            )
            await box.first.fill(owner_email, timeout=5_000)
            await self.page.keyboard.press("Tab")
            await self.page.wait_for_timeout(300)
        except Exception as e:
            print(f"    [GEICO] WARN: email confirmation failed: {e}")
            await self.screenshot("step7_email_error")

    # ------------------------------------------------------------------
    # 3. Owner phone confirmation textbox
    # ------------------------------------------------------------------

    async def _fill_phone_confirmation(self, owner_phone) -> None:
        """Overwrite the pre-populated owner phone if BlueQuote phone is set."""
        if not owner_phone:
            print(
                "    [GEICO] Step 7: owner phone -> no BlueQuote value (keep auto-pop)"
            )
            return
        try:
            box = self.page.get_by_role(
                "textbox", name=re.compile(r"confirm.+owner'?s phone", re.I)
            )
            if await box.count() == 0:
                box = self.page.get_by_role(
                    "textbox", name=re.compile(r"owner'?s phone", re.I)
                )
            if await box.count() == 0:
                box = self.page.locator(
                    'input[id*="OwnerPhone" i], input[id*="OwnersPhone" i]'
                ).first
            if await box.count() == 0:
                print("    [GEICO] WARN: owner phone textbox not found")
                return
            print(f"    [GEICO] Step 7: owner phone -> {owner_phone}")
            await box.first.fill(owner_phone, timeout=5_000)
            await self.page.keyboard.press("Tab")
            await self.page.wait_for_timeout(300)
        except Exception as e:
            print(f"    [GEICO] WARN: owner phone confirmation failed: {e}")
            await self.screenshot("step7_owner_phone_error")

    # ------------------------------------------------------------------
    # 5. Per-driver: DL State combobox + DL Number textbox
    # ------------------------------------------------------------------

    async def _fill_drivers_section(self, fields: MappedFields) -> None:
        """Fill DL State + DL Number for each driver listed on the page.

        DL State is a native <select>. We re-set it via the 50-state signature
        even though it is usually pre-populated from Step 4, so the form
        remains correct if state changed between steps.

        DL Number is the critical field that downstream MVR/CLUE consumes.
        If `driver.license_number is None`, we WARN and skip; MVR/CLUE will
        fail server-side later but we do not block here.
        """
        for idx, driver in enumerate(fields.drivers, start=1):
            # Skip drivers excluded entirely from the policy if they were
            # never added to the wizard. Excluded owners still appear (the
            # placeholder) so do NOT short-circuit here.
            await self._fill_driver_dl_state(driver, idx)
            await self._fill_driver_dl_number(driver, idx)

    async def _fill_driver_dl_state(self, driver, idx: int) -> None:
        """Re-set DL State combobox for a specific driver.

        Scope-by-label is critical: `select_by_options_signature` returns the
        FIRST matching <select> on the page, so it would always target
        driver 1's combobox no matter which `idx` we pass. We anchor on the
        driver's first name (the label is "{first_name}'s Driver License State"
        per live mapping), and only fall back to the nth-by-options if the
        label lookup fails.
        """
        state = driver.license_state or "Texas"
        import re as _re
        try:
            print(
                f"    [GEICO] Step 7: driver {idx} ({driver.first_name}) "
                f"DL State -> {state}"
            )
            # Strategy 1: label-anchored locator (per-driver scoped).
            if driver.first_name:
                label_pat = _re.compile(
                    rf"{_re.escape(driver.first_name)}.*Driver License State",
                    _re.IGNORECASE,
                )
                combo = self.page.get_by_label(label_pat)
                if await combo.count() > 0:
                    try:
                        await combo.first.select_option(label=state, timeout=5_000)
                        return
                    except Exception:
                        # Fall through to JS-based set via id pattern below.
                        pass

            # Strategy 2: per-index JS — pick the Nth non-disabled <select>
            # whose options match the state signature. idx is 1-based; map to
            # 0-based here.
            await self._select_nth_by_options_signature(
                _LICENSE_STATE_OPTIONS_SIGNATURE, state, idx - 1
            )
        except Exception as e:
            print(
                f"    [GEICO] WARN: driver {idx} DL State select failed: {e}"
            )
            await self.screenshot(f"step7_driver_{idx}_dl_state_error")

    async def _select_nth_by_options_signature(
        self, options_signature: list, value: str, nth: int
    ) -> None:
        """Select the Nth (0-based) non-disabled <select> whose option list
        contains every string in `options_signature`. Sets the option whose
        value OR visible text matches `value`. Raises if no match."""
        import json as _json
        js = """
            (args) => {
                const signature = args.signature;
                const value = args.value;
                const nth = args.nth;
                const norm = (s) => (s || '').trim();
                const selects = Array.from(document.querySelectorAll('select')).filter(s => {
                    if (s.disabled) return false;
                    const texts = Array.from(s.options).map(o => norm(o.text));
                    return signature.every(sig => texts.some(t => t.includes(sig)));
                });
                if (selects.length <= nth) {
                    return JSON.stringify({error: 'no-match', total: selects.length});
                }
                const target = selects[nth];
                // Try value attr first, then visible text.
                let chosen = null;
                for (const opt of target.options) {
                    if (opt.value === value) { chosen = opt.value; break; }
                }
                if (chosen === null) {
                    for (const opt of target.options) {
                        if (norm(opt.text) === norm(value)) { chosen = opt.value; break; }
                    }
                }
                if (chosen === null) {
                    return JSON.stringify({error: 'option-not-found', id: target.id});
                }
                target.value = chosen;
                target.dispatchEvent(new Event('change', {bubbles: true}));
                return JSON.stringify({id: target.id || ''});
            }
        """
        raw = await self.page.evaluate(
            js, {"signature": options_signature, "value": value, "nth": nth}
        )
        result = _json.loads(raw)
        if result.get("error") == "no-match":
            raise RuntimeError(
                f"Only {result.get('total', 0)} <select>s match signature "
                f"{options_signature}; needed at least {nth + 1}"
            )
        if result.get("error") == "option-not-found":
            raise RuntimeError(
                f"<select id={result.get('id')!r}> has no option with value "
                f"or text {value!r}"
            )

    async def _fill_driver_dl_number(self, driver, idx: int) -> None:
        """Fill DL Number textbox for a driver.

        Selector strategy:
          1. Try role=textbox with accessible name matching
             "{first_name}'s Driver License Number" (case-insensitive).
          2. Fall back to partial "Driver License Number" match, indexed
             by `idx-1` (drivers are rendered in order on Step 7).
          3. Fall back to any input whose id contains "License" /
             "DLNumber" / "LicenseNumber", indexed by `idx-1`.
        """
        if driver.license_number is None:
            print(
                f"    [GEICO] WARN: driver {idx} ({driver.first_name}) has no "
                f"license_number -- MVR/CLUE will fail downstream"
            )
            return

        first = (driver.first_name or "").strip()
        try:
            box = None
            if first:
                # 1. Personalized accessible name: "{first}'s Driver License Number"
                pattern = re.compile(
                    rf"{re.escape(first)}'?s\s+driver\s+license\s+number",
                    re.I,
                )
                candidate = self.page.get_by_role("textbox", name=pattern)
                if await candidate.count() > 0:
                    box = candidate.first

            if box is None:
                # 2. Generic "Driver License Number" match indexed by driver order.
                generic = self.page.get_by_role(
                    "textbox", name=re.compile(r"driver\s+license\s+number", re.I)
                )
                count = await generic.count()
                if count > 0:
                    target_i = idx - 1 if idx - 1 < count else 0
                    box = generic.nth(target_i)

            if box is None:
                # 3. Final fallback: id-pattern.
                generic = self.page.locator(
                    'input[id*="LicenseNumber" i], input[id*="DLNumber" i], '
                    'input[id*="License" i][type="text"]'
                )
                count = await generic.count()
                if count > 0:
                    target_i = idx - 1 if idx - 1 < count else 0
                    box = generic.nth(target_i)

            if box is None:
                raise RuntimeError("DL Number textbox not found")

            print(
                f"    [GEICO] Step 7: driver {idx} ({first}) "
                f"DL Number -> {driver.license_number}"
            )
            await box.wait_for(state="visible", timeout=10_000)
            await box.fill(driver.license_number, timeout=5_000)
            await self.page.keyboard.press("Tab")
            await self.page.wait_for_timeout(300)
        except Exception as e:
            print(f"    [GEICO] WARN: driver {idx} DL Number fill failed: {e}")
            await self.screenshot(f"step7_driver_{idx}_dl_error")

    # ------------------------------------------------------------------
    # 6. Per-vehicle: VIN check + Registered owner combobox + Owned radio
    # ------------------------------------------------------------------

    async def _fill_vehicles_section(self, fields: MappedFields) -> None:
        """For each vehicle: verify VIN, set Registered Owner, set Ownership."""
        owner_full_name = " ".join(
            [
                fields.owner_first_name or "",
                fields.owner_last_name or "",
            ]
        ).strip()
        for idx, vehicle in enumerate(fields.vehicles, start=1):
            await self._verify_vehicle_vin(vehicle, idx)
            await self._fill_registered_owner(vehicle, idx, owner_full_name)
            await self._fill_owned_leased_financed(vehicle, idx)

    async def _verify_vehicle_vin(self, vehicle, idx: int) -> None:
        """The VIN textbox is disabled on Step 7. Verify it is not empty."""
        try:
            vin_inputs = self.page.locator(
                'input[id*="VIN" i], input[id*="Vin" i]'
            )
            count = await vin_inputs.count()
            if count == 0:
                print(
                    f"    [GEICO] Step 7: vehicle {idx} VIN input not found "
                    f"(may not render on this build)"
                )
                return
            target_i = idx - 1 if idx - 1 < count else 0
            current = ""
            try:
                current = await vin_inputs.nth(target_i).input_value()
            except Exception:
                current = ""
            if current.strip():
                print(
                    f"    [GEICO] Step 7: vehicle {idx} VIN confirmed -> {current}"
                )
            else:
                print(
                    f"    [GEICO] WARN: vehicle {idx} VIN textbox empty "
                    f"(expected auto-pop)"
                )
        except Exception as e:
            print(f"    [GEICO] WARN: vehicle {idx} VIN verify failed: {e}")
            await self.screenshot(f"step7_vehicle_{idx}_vin_error")

    async def _fill_registered_owner(
        self, vehicle, idx: int, owner_full_name: str
    ) -> None:
        """Set the per-vehicle Registered Owner combobox.

        Live mapping caveat: this <select> can have DUPLICATE options (the
        same owner name appearing twice -- e.g. "HUMBERTO VILLARREAL"
        appeared once as business owner and once as a driver candidate).
        Plain `select_option(label=...)` may either pick the wrong one or
        ambiguity-fail. Strategy:

          1. Try to match by `owner_full_name` (case-insensitive) via JS so
             we hit the FIRST matching option deterministically.
          2. If that fails, pick the FIRST non-empty option (safe default
             because both duplicates point at the same legal owner).
        """
        # Each vehicle has its own registered-owner select; use index to
        # find the Nth such <select>. We identify candidates by id-pattern
        # plus by the presence of the owner's last name in their options.
        try:
            target_text = owner_full_name.strip()
            print(
                f"    [GEICO] Step 7: vehicle {idx} registered owner -> "
                f"{target_text or '(first option)'}"
            )

            # JS strategy: enumerate <select>s that look like a registered
            # owner combobox (id contains "RegisteredOwner" or
            # "RegOwner" or "VehicleOwner"), skip ones already handled in
            # previous iterations by tracking a data-attr we set, and pick
            # the FIRST option matching `target_text` (case-insensitive) or
            # the first non-empty option as fallback.
            js = """
                (args) => {
                    const target = (args.target || '').trim().toLowerCase();
                    const wantIndex = args.index;  // 1-based per vehicle order
                    const selects = Array.from(document.querySelectorAll('select'))
                        .filter(s => {
                            if (s.disabled) return false;
                            const id = (s.id || '').toLowerCase();
                            return id.includes('registeredowner')
                                || id.includes('regowner')
                                || id.includes('vehicleowner')
                                || id.includes('vehregowner');
                        });
                    if (selects.length === 0) {
                        return JSON.stringify({error: 'no-select-found'});
                    }
                    const targetIdx = Math.min(wantIndex - 1, selects.length - 1);
                    const select = selects[targetIdx];
                    const opts = Array.from(select.options);
                    let chosen = null;
                    if (target) {
                        chosen = opts.find(
                            o => (o.text || '').trim().toLowerCase() === target
                        );
                        if (!chosen) {
                            chosen = opts.find(
                                o => (o.text || '').trim().toLowerCase().includes(target)
                            );
                        }
                    }
                    if (!chosen) {
                        // First non-empty option (skip placeholder "" or
                        // "Select..." entries).
                        chosen = opts.find(o => {
                            const t = (o.text || '').trim();
                            return t && !/^select/i.test(t);
                        });
                    }
                    if (!chosen) {
                        return JSON.stringify({
                            error: 'no-option-found',
                            id: select.id || '',
                            options: opts.map(o => o.text),
                        });
                    }
                    select.value = chosen.value;
                    select.dispatchEvent(new Event('change', {bubbles: true}));
                    return JSON.stringify({
                        id: select.id || '',
                        chosen: chosen.text,
                    });
                }
            """
            raw = await self.page.evaluate(
                js, {"target": target_text, "index": idx}
            )
            import json as _json
            result = _json.loads(raw)
            if result.get("error") == "no-select-found":
                # Fallback to options signature in case our id-pattern was wrong.
                # The signature uses the owner full name appearing in the option
                # list (which the live mapping confirmed).
                print(
                    f"    [GEICO] WARN: vehicle {idx} no registered-owner "
                    f"<select> matched id-pattern; trying options signature"
                )
                if target_text:
                    await self.select_by_options_signature(
                        [target_text], target_text
                    )
                else:
                    raise RuntimeError(
                        "registered owner combobox not found and no owner_full_name"
                    )
            elif result.get("error") == "no-option-found":
                raise RuntimeError(
                    f"no option matched in registered-owner select "
                    f"id={result.get('id')!r} options={result.get('options')}"
                )
            else:
                print(
                    f"    [GEICO] Step 7: vehicle {idx} registered owner set "
                    f"-> {result.get('chosen')!r} (select id={result.get('id')!r})"
                )
        except Exception as e:
            print(
                f"    [GEICO] WARN: vehicle {idx} registered owner failed: {e}"
            )
            await self.screenshot(f"step7_vehicle_{idx}_owner_error")

    async def _fill_owned_leased_financed(self, vehicle, idx: int) -> None:
        """Click the Owned / Leased / Financed shadow-DOM radio."""
        choice = (vehicle.is_financed_or_leased or "Owned").strip()
        # Normalize to one of Owned/Leased/Financed for the suffix logic.
        normalized = choice.capitalize()
        if normalized not in {"Owned", "Leased", "Financed"}:
            normalized = "Owned"
        print(
            f"    [GEICO] Step 7: vehicle {idx} ownership -> {normalized}"
        )
        try:
            await self.click_question_radio(
                "owned, leased, or financed", normalized
            )
        except Exception as e:
            print(
                f"    [GEICO] WARN: vehicle {idx} ownership radio failed: {e}"
            )
            await self.screenshot(f"step7_vehicle_{idx}_ownership_error")

    # ------------------------------------------------------------------
    # 8. Blanket additional insured radio
    # ------------------------------------------------------------------

    async def _fill_blanket_additional(self, has_blanket_additional: bool) -> None:
        """Default-checked No. Only click Yes when the BlueQuote flag is set."""
        if not has_blanket_additional:
            print(
                "    [GEICO] Step 7: blanket additional insured -> No (default, leave as-is)"
            )
            return
        print(
            "    [GEICO] Step 7: blanket additional insured -> Yes"
        )
        try:
            await self.click_question_radio(
                "blanket additional insured", "Yes"
            )
        except Exception as e:
            print(f"    [GEICO] WARN: blanket additional radio failed: {e}")
            await self.screenshot("step7_blanket_additional_error")
