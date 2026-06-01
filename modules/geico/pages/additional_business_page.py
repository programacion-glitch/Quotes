"""
Additional Business Info Page Object for GEICO wizard (Step 5).

Title: `GEICO Additional Business Info`. Three logical sections:

  1. "Tell us about the customer's business"
       - Years operating combobox
       - Employees (excl owners) combobox
  2. "Current Auto Insurance"
       - Has current auto insurance? combobox
       - If Yes -> two NEW comboboxes appear (years with insurer + BI limits)
  3. "Some additional info we'll need"
       - Liability type radio group (BOP / GL / None)
       - Need additional insured? radio (Yes/No)
       - Blanket additional insured contract? radio (Yes/No) — defaults No
       - Filings required? radio (Yes/No)

Per docs/Proceso GEICO.md: selecting "Yes" on current insurance triggers an
AJAX render that injects the years-with-insurer + BI-limits comboboxes; a
required-field validation error fires if we click Next before they're filled.
We wait explicitly for those before continuing.

Submit -> waits for Step 5b 'DriveEasy Pro' title.
"""

import re

from playwright.async_api import Page

from modules.geico.pages.base_page import BasePage
from modules.geico.field_mapper import MappedFields


class AdditionalBusinessPage(BasePage):
    """GEICO wizard Step 5 — Additional Business Info."""

    async def fill_and_submit(self, fields: MappedFields) -> None:
        """
        Fill the 'Tell us about the customer's business' + 'Current Auto Insurance'
        + 'Some additional info we'll need' sections. Click Next.

        Pre-state: 'Additional Business Info' title.
        Post-state: 'DriveEasy Pro' title (Step 5b, dynamic).
        """
        await self.page.wait_for_load_state("networkidle", timeout=30_000)
        await self.remove_overlays()
        print("    [GEICO] Step 5: Additional Business Info")

        await self._fill_business_metrics(fields)
        await self._fill_current_insurance(fields)
        await self._fill_additional_info(fields)
        await self._click_next()

    # ------------------------------------------------------------------
    # Section 1: business metrics (years operating + employees)
    # ------------------------------------------------------------------

    async def _fill_business_metrics(self, fields: MappedFields) -> None:
        """Years operating + employee count comboboxes."""
        try:
            print(f"    [GEICO] Step 5: Years operating -> {fields.years_operating}")
            await self.select_by_options_signature(
                ["Less than 1", "7+"], fields.years_operating
            )
            await self.page.wait_for_timeout(500)
        except Exception as e:
            print(f"    [GEICO] WARN: years operating select failed: {e}")
            await self.screenshot("step5_years_operating_error")

        try:
            print(f"    [GEICO] Step 5: Employees -> {fields.employee_count}")
            await self.select_by_options_signature(
                ["None", "21+"], fields.employee_count
            )
            await self.page.wait_for_timeout(500)
        except Exception as e:
            print(f"    [GEICO] WARN: employees select failed: {e}")
            await self.screenshot("step5_employees_error")

    # ------------------------------------------------------------------
    # Section 2: current auto insurance (conditional fields)
    # ------------------------------------------------------------------

    async def _fill_current_insurance(self, fields: MappedFields) -> None:
        """Has current insurance? -> if Yes, fill conditional fields."""
        ins_value = "Yes" if fields.has_current_insurance else "No"
        try:
            print(f"    [GEICO] Step 5: Has current insurance -> {ins_value}")
            await self.select_by_options_signature(
                ["Yes", "No, the customer was deployed"], ins_value
            )
            await self.page.wait_for_timeout(500)
        except Exception as e:
            print(f"    [GEICO] WARN: has-current-insurance select failed: {e}")
            await self.screenshot("step5_has_current_insurance_error")
            return

        if not fields.has_current_insurance:
            return

        # Wait for conditional fields to render. Try a couple of selector
        # strategies because the label wording may vary across builds.
        try:
            await self._wait_for_conditional_insurance_fields()
        except Exception as e:
            print(
                f"    [GEICO] WARN: conditional insurance fields did not "
                f"appear within timeout: {e}"
            )
            await self.screenshot("step5_conditional_fields_missing")

        try:
            print(
                f"    [GEICO] Step 5: Years with insurer -> "
                f"{fields.years_with_insurer}"
            )
            await self.select_by_options_signature(
                ["Less Than 1 Year", "10+ Years"], fields.years_with_insurer
            )
            await self.page.wait_for_timeout(300)
        except Exception as e:
            print(f"    [GEICO] WARN: years-with-insurer select failed: {e}")
            await self.screenshot("step5_years_with_insurer_error")

        try:
            print(
                f"    [GEICO] Step 5: Current BI limits -> "
                f"{fields.current_bi_limits}"
            )
            await self.select_by_options_signature(
                ["State Minimum",
                 "$1,000,000/$1,000,000 or $1,000,000 CSL"],
                fields.current_bi_limits,
            )
            await self.page.wait_for_timeout(300)
        except Exception as e:
            print(f"    [GEICO] WARN: current BI limits select failed: {e}")
            await self.screenshot("step5_current_bi_limits_error")

    async def _wait_for_conditional_insurance_fields(self) -> None:
        """Wait for the years-with-insurer combobox to render after Yes."""
        # Strategy 1: label-anchored wait.
        try:
            label = self.page.get_by_label(
                re.compile(
                    r"how long has the customer been with their current",
                    re.I,
                )
            )
            await label.first.wait_for(state="visible", timeout=10_000)
            return
        except Exception:
            pass

        # Strategy 2: poll for a <select> with the years-with-insurer signature.
        await self.page.wait_for_function(
            """() => {
                const selects = Array.from(document.querySelectorAll('select'));
                return selects.some(s => {
                    if (s.disabled) return false;
                    const texts = Array.from(s.options).map(o => (o.text || '').trim());
                    return texts.some(t => t.includes('Less Than 1 Year'))
                        && texts.some(t => t.includes('10+ Years'));
                });
            }""",
            timeout=10_000,
        )

    # ------------------------------------------------------------------
    # Section 3: liability type + insured/filings radios
    # ------------------------------------------------------------------

    async def _fill_additional_info(self, fields: MappedFields) -> None:
        """Liability type + named-additional-insured + blanket + filings."""
        await self._set_liability_type(fields.current_liability_type)
        await self._set_radio_group(
            question_substring="named additional insured",
            value=fields.needs_additional_insured,
            log_name="Need additional insured",
        )
        # Blanket additional insured contract — default is No, only click on Yes
        # or when explicitly No is requested by upstream config (Default).
        await self._set_radio_group(
            question_substring="blanket additional insured",
            value=fields.has_blanket_additional,
            log_name="Blanket additional insured",
            skip_if_default_no=True,
        )
        await self._set_radio_group(
            question_substring="filings required",
            value=fields.requires_filings,
            log_name="Filings required",
        )

    async def _set_liability_type(self, liability_type: str) -> None:
        """Click the BOP/GL/None radio for the liability-type question."""
        target_label = {
            "BOP": "Business Owners Policy (BOP)",
            "GL": "General Liability Policy (GL)",
            "None": "None",
        }.get(liability_type, "None")
        print(f"    [GEICO] Step 5: Liability type -> {target_label}")
        try:
            await self.click_question_radio(
                "kind of liability insurance", target_label
            )
        except Exception as e:
            print(f"    [GEICO] WARN: liability-type radio failed: {e}")
            await self.screenshot("step5_liability_type_error")

    async def _set_radio_group(
        self,
        question_substring: str,
        value: bool,
        log_name: str,
        skip_if_default_no: bool = False,
    ) -> None:
        """Click Yes/No within a radio group anchored by its question text.

        skip_if_default_no=True means: if value is False, skip the click
        because GEICO pre-checks No (avoids unnecessary AJAX rerenders).
        """
        target_name = "Yes" if value else "No"
        if skip_if_default_no and not value:
            print(
                f"    [GEICO] Step 5: {log_name} -> No (default, skipping)"
            )
            return
        print(f"    [GEICO] Step 5: {log_name} -> {target_name}")
        try:
            await self.click_question_radio(question_substring, target_name)
        except Exception as e:
            print(f"    [GEICO] WARN: {log_name} radio failed: {e}")
            slug = log_name.lower().replace(" ", "_")
            await self.screenshot(f"step5_radio_{slug}_error")

    # ------------------------------------------------------------------
    # Submit
    # ------------------------------------------------------------------

    async def _click_next(self) -> None:
        """Click Next and wait for Step 5b (DriveEasy Pro)."""
        print("    [GEICO] Step 5: Clicking Next...")
        await self.remove_overlays()
        try:
            btn = self.page.get_by_role("button", name="Next")
            await btn.first.click(timeout=10_000)
        except Exception as e:
            await self.screenshot("step5_next_click_error")
            raise RuntimeError(f"Failed to click Next on Step 5: {e}") from e

        try:
            await self.page.wait_for_function(
                "() => document.title.includes('DriveEasy Pro')",
                timeout=20_000,
            )
            print("    [GEICO] Step 5 -> Step 5b (DriveEasy Pro) loaded")
        except Exception as e:
            await self.screenshot("step5_to_step5b_navigation_error")
            raise RuntimeError(
                f"Step 5 submit did not advance to DriveEasy Pro: {e}"
            ) from e
