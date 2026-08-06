"""
Business Class & USDOT Page Object for GEICO wizard (Step 1).

This module is part of Block 2 of the GEICO automation, which implements
Steps 1-3 of the quote wizard (Business Class & USDOT, Business & Owner
Info, Vehicles). See `docs/Proceso GEICO.md` section "Step 1: Business
Class & USDOT" for the full live field mapping captured during the GEICO
mapping session.

Pre-state: the wizard tab is already loaded and shows the
"Business Class & USDOT" title (the dashboard's Start New Quote opens it
in a new tab and the orchestrator hands that page to this object).
Most identification fields (ZIP, USDOT, "is this the customer's business?")
arrive PRE-POPULATED from the dashboard eligibility check, so this page
mostly confirms them and answers the remaining radios / business-class
combobox.

All selectors validated live during the mapping session against USDOT
2033673 (HUMBERTO).
"""

import json
from pathlib import Path

from playwright.async_api import Page

from modules import decision_ledger
from modules.geico.business_class_resolver import resolve_business_class
from modules.geico.field_mapper import MappedFields
from modules.geico.pages.base_page import BasePage

_PAGE = "Step 1 Business Class & USDOT"


# Catalog of the 1,596 Business Class options, dumped once from the live
# Select2's underlying native <select> and reused offline by the resolver.
_CATALOG_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "geico_business_classes.json"
)

# Read every option text from the page's LARGEST <select> — the business
# class one dwarfs the rest (1,596 options vs <60 anywhere else).
_JS_DUMP_LARGEST_SELECT = """
    () => {
        let best = null;
        for (const s of document.querySelectorAll('select')) {
            if (!best || s.options.length > best.options.length) best = s;
        }
        if (!best) return [];
        return Array.from(best.options)
            .map(o => (o.text || '').trim()).filter(t => t.length > 0);
    }
"""

# Visible radio groups with NO checked option — the business-class-dependent
# conditionals GEICO reveals after the class commits (live NUNEZ 2026-06-11:
# 'Package Delivery' revealed the food-TNC and Amazon questions and Next
# refused to advance).
_JS_UNANSWERED_GROUPS = """
    () => Array.from(document.querySelectorAll('gds-radio-button-group'))
        .filter(g => g.offsetParent !== null)
        .filter(g => !Array.from(g.querySelectorAll('gds-radio-button'))
            .some(b => {
                const i = b.shadowRoot
                    && b.shadowRoot.querySelector('input[type=radio]');
                return i ? i.checked : b.hasAttribute('checked');
            }))
        .map(g => (g.textContent || '').trim()
            .replace(/\\s+/g, ' ').slice(0, 160));
"""

# Defaults for the business-class-dependent conditionals. Keyed by a
# distinctive question substring; value = (answer, soft). `soft=True` marks a
# judgment-call default that must surface as a QuoteResult warning for human
# review (the BlueQuote simply doesn't carry the answer). Catalog of hidden
# groups observed live via MCP, 2026-06-11.
_CONDITIONAL_DEFAULTS = (
    ("food-based transportation network", ("No", False)),
    ("deliver packages for amazon", ("No", True)),
    ("seasonal or temporary workers", ("No", False)),
    ("transport clients for a fee", ("No", False)),
    ("team driving or slip seating", ("No", False)),
    ("children to/from daycare", ("No", False)),
    ("oil and gas fields", ("No", True)),
    ("coiled steel", ("No", True)),
    ("state or federal filing", ("Neither", False)),
    # Aparecida con el rediseño del dashboard (live 2026-08-06, G&E HAULING):
    # el Step 1 ahora la muestra siempre. Va No: ventas manda submissions de
    # negocio NUEVO — si el cliente ya tuviera póliza GEICO vigente sería una
    # renovación, no una cotización. R-091 (EN-DUDA, confirmar con Diana).
    ("current geico commercial auto policy", ("No", False)),
)


def _match_conditional_default(question_text: str):
    """Return (answer, soft) for a known Step-1 conditional question, or
    (None, False) when the question is new — the caller HALTs loudly so the
    unknown gets mapped instead of silently mis-answered."""
    q = " ".join((question_text or "").lower().split())
    for needle, (answer, soft) in _CONDITIONAL_DEFAULTS:
        if needle in q:
            return answer, soft
    return None, False


class BusinessClassPage(BasePage):
    """GEICO wizard - Step 1: Business Class & USDOT."""

    async def fill_and_submit(self, fields: MappedFields) -> None:
        """
        Confirm USDOT pre-pop, answer ELD + hazmat radios, search-select
        business class from the 1,596-option combobox, click Next.

        Pre-state: wizard page already showing 'Business Class & USDOT' title.
        Post-state: 'Business & Owner Info' title (Step 2) loaded.

        Raises RuntimeError on validation or selector failure.
        """
        print("    [GEICO] Step 1: Business Class & USDOT")
        await self.page.wait_for_load_state("networkidle", timeout=30_000)
        # The wizard backend can sit on the 'Please wait...' spinner well past
        # networkidle (live DIBOLL 2026-06-11: title stuck at 'GEICO Gateway'
        # >10s) — gate on the Step 1 title before touching any field.
        try:
            await self.wait_for_any_title(
                ["Business Class & USDOT"], timeout_ms=60_000
            )
        except TimeoutError as e:
            await self.screenshot("step1_never_mounted")
            raise RuntimeError(
                f"Step 1 wizard never mounted (still on spinner/gateway): {e}"
            ) from e
        await self.remove_overlays()
        # The Dashboard drawer auto-opens when the FMCSA data lands and the
        # form reflows under it — collapse it before touching any control.
        await self.collapse_dashboard_drawer()

        try:
            await self._confirm_zip(fields.zip_code)
            await self._confirm_has_usdot()
            await self._confirm_is_customers_business()
            await self._answer_eld(fields.has_eld)
            await self._select_business_class(fields.business_class)
            await self._answer_hazmat_placard(fields.has_hazmat_placard)
            await self._answer_revealed_conditionals()
            await self._click_next()
            await self._wait_for_step2()
        except RuntimeError:
            raise
        except Exception as e:
            await self.screenshot("step1_unexpected_failure")
            raise RuntimeError(
                f"Step 1 (Business Class & USDOT) failed: {e}"
            ) from e

    # ---- Individual step helpers ----

    async def _confirm_zip(self, zip_code) -> None:
        """ZIP is pre-poblated from dashboard. Only fill if empty."""
        try:
            box = self.page.get_by_role("textbox", name="5-Digit ZIP Code")
            await box.first.wait_for(state="visible", timeout=10_000)
            try:
                current = (await box.first.input_value()).strip()
            except Exception:
                current = ""
            if not current and zip_code:
                print(f"    [GEICO] Step 1: ZIP empty, filling {zip_code}")
                await box.first.fill(zip_code, timeout=5_000)
                await self.page.keyboard.press("Tab")
                await self.page.wait_for_timeout(500)
            else:
                print(f"    [GEICO] Step 1: ZIP pre-poblated ({current or zip_code})")
        except Exception as e:
            await self.screenshot("step1_zip")
            raise RuntimeError(f"ZIP confirmation failed: {e}") from e

    async def _confirm_has_usdot(self) -> None:
        """USDOT 'Yes' radio is pre-checked by dashboard eligibility flow."""
        try:
            yes_radio = self.page.get_by_role("radio", name="Yes").first
            await yes_radio.wait_for(state="visible", timeout=10_000)
            try:
                checked = await yes_radio.is_checked()
            except Exception:
                checked = True  # custom radios may not report checked state
            if not checked:
                print("    [GEICO] Step 1: USDOT 'Yes' not checked, clicking")
                await yes_radio.click(timeout=5_000)
                await self.page.wait_for_timeout(300)
            else:
                print("    [GEICO] Step 1: USDOT 'Yes' already checked")
        except Exception as e:
            await self.screenshot("step1_has_usdot")
            raise RuntimeError(f"USDOT 'Yes' confirmation failed: {e}") from e

    async def _confirm_is_customers_business(self) -> None:
        """
        Confirm the 'Is this the customer's business?' radio is 'Yes'.

        GEICO renders this as a custom radio with a shadow input whose id
        follows the pattern `#Id_GiveExtendUsDotVerifyBusinessAddress_<id>-shadow`,
        but the suffix varies per page load. We anchor on the visible
        question text and click the first 'Yes' radio inside that block.
        """
        print("    [GEICO] Step 1: Confirming 'Is this the customer's business?' Yes")
        decision_ledger.record("Is this the customer's business?", "Yes",
                               page=_PAGE, options=["Yes", "No"],
                               source="DEFAULT", rule_id="R-051")
        try:
            await self.click_question_radio(
                "Is this the customer's business", "Yes"
            )
        except Exception as e:
            await self.screenshot("step1_is_customers_business")
            raise RuntimeError(
                f"Could not confirm 'Is this the customer's business?': {e}"
            ) from e

    async def _answer_eld(self, has_eld: bool) -> None:
        """
        Answer 'Does the customer have an electronic logging device (ELD)?'
        Default from field_mapper is False (conservative).
        """
        answer = "Yes" if has_eld else "No"
        print(f"    [GEICO] Step 1: ELD -> {answer}")
        decision_ledger.record(
            "Does the customer have an electronic logging device (ELD)?",
            answer, page=_PAGE, options=["Yes", "No"], source="DEFAULT",
            rule_id="R-052")
        try:
            await self.click_question_radio(
                "Does the customer have an electronic logging device", answer
            )
        except Exception as e:
            await self.screenshot("step1_eld")
            raise RuntimeError(f"ELD radio click failed: {e}") from e

    async def _select_business_class(self, business_class) -> None:
        """
        Pick the business class from the ~1,596-option list.

        The field is a **Select2** widget (jQuery): a hidden native <select>
        plus a `[role=combobox]` overlay. Setting the native <select> via JS
        does NOT satisfy the widget's validation ("Please make a selection"
        persists) — only driving the overlay works. Verified live 2026-05-28.

        When the mapped/raw value matches nothing, the resolver kicks in:
        catalog (dumped once from the native select) -> learned cache -> AI
        over prefiltered candidates (decision remembered in
        data/learned_mappings.xlsx). Only if THAT fails does the quote HALT.
        """
        if not business_class:
            await self.screenshot("step1_business_class_missing")
            raise RuntimeError(
                "Business class is required for GEICO Step 1 but was not "
                "provided by the field_mapper"
            )

        print(f"    [GEICO] Step 1: Selecting business class {business_class!r}")
        try:
            if await self._select2_pick(business_class):
                decision_ledger.record("Business Class", business_class,
                                       page=_PAGE, source="MATCHED",
                                       rule_id="R-054",
                                       note="match directo en el Select2")
                return

            # No match: resolve via catalog + learned cache + AI.
            catalog = await self._ensure_catalog()
            resolved, source = resolve_business_class(business_class, catalog)
            if not resolved:
                await self.screenshot("step1_business_class_no_match")
                raise RuntimeError(
                    f"Business class {business_class!r} produced no matching "
                    f"options in the Select2 list and could not be resolved "
                    f"(catalog={len(catalog)} opts, learned cache + AI miss). "
                    f"Add a correction to data/learned_mappings.xlsx "
                    f"(decision_type=geico_business_class)."
                )
            print(
                f"    [GEICO] Step 1: business class resolved via {source}: "
                f"{business_class!r} -> {resolved!r}"
            )
            decision_ledger.record("Business Class", resolved, page=_PAGE,
                                   source="AI", rule_id="R-054",
                                   note=f"{business_class!r} resuelto vía {source}")
            if not await self._select2_pick(resolved):
                await self.screenshot("step1_business_class_resolved_no_match")
                raise RuntimeError(
                    f"Resolved business class {resolved!r} (via {source}) "
                    f"still produced no Select2 match — catalog may be stale; "
                    f"delete data/geico_business_classes.json to re-dump."
                )
        except RuntimeError:
            raise
        except Exception as e:
            await self.screenshot("step1_business_class")
            raise RuntimeError(
                f"Business class {business_class!r} selection failed: {e}"
            ) from e

    async def _select2_pick(self, label: str) -> bool:
        """Drive the Select2 overlay: open -> type -> click the option.
        Returns False when the filter yields no options (caller resolves)."""
        combo = self.page.locator('[role="combobox"]').first
        await combo.wait_for(state="visible", timeout=10_000)
        await combo.click(timeout=5_000)
        await self.page.wait_for_timeout(400)

        search = self.page.locator('input[role="searchbox"]').first
        await search.wait_for(state="visible", timeout=5_000)
        # Real keystrokes so Select2's keyup filter fires.
        await search.fill(label)
        await self.page.wait_for_timeout(700)

        options = self.page.locator('[role="listbox"] [role="option"]')
        count = await options.count()
        if count == 0:
            # The full string (with "& ( )") may over-filter; retry with a
            # shorter distinctive prefix.
            prefix = label.split("(")[0].strip()[:18]
            await search.fill(prefix)
            await self.page.wait_for_timeout(700)
            options = self.page.locator('[role="listbox"] [role="option"]')
            count = await options.count()

        if count == 0:
            # Close the dropdown so a retry starts clean.
            await self.page.keyboard.press("Escape")
            return False

        # Prefer the exact-text option; else take the first remaining.
        exact = self.page.locator(
            '[role="listbox"] [role="option"]', has_text=label
        )
        target = exact.first if await exact.count() > 0 else options.first
        await target.click(timeout=10_000)
        # The hazmat sub-question may render after this; give it a tick.
        await self.page.wait_for_timeout(800)
        return True

    async def _ensure_catalog(self) -> list:
        """Load the business-class catalog; dump it from the live page's
        largest native <select> on first use (learning instrumentation —
        the next quote resolves offline)."""
        if _CATALOG_PATH.exists():
            try:
                return json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
            except Exception as e:
                self.note_warning(f"business-class catalog unreadable: {e}")
        options = await self.page.evaluate(_JS_DUMP_LARGEST_SELECT)
        if isinstance(options, list) and len(options) > 400:
            try:
                _CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
                _CATALOG_PATH.write_text(
                    json.dumps(options, indent=1, ensure_ascii=False),
                    encoding="utf-8",
                )
                print(
                    f"    [GEICO] Step 1: business-class catalog dumped "
                    f"({len(options)} opts) -> {_CATALOG_PATH.name}"
                )
            except Exception as e:
                self.note_warning(f"business-class catalog write failed: {e}")
        return options if isinstance(options, list) else []

    async def _answer_hazmat_placard(self, has_hazmat: bool) -> None:
        """
        Answer 'Do any of the customer's vehicles or loads require a
        hazardous material placard?'.

        This question is CONDITIONAL: GEICO only shows it for certain business
        classes. For others (e.g. "Dirt Sand & Gravel") it stays hidden in the
        DOM and is not required. So we wait a SHORT time for it to become
        visible; if it doesn't, we skip it (NOT an error).
        """
        answer = "Yes" if has_hazmat else "No"
        question = self.page.get_by_text(
            "require a hazardous material placard"
        ).first
        try:
            await question.wait_for(state="visible", timeout=4_000)
        except Exception:
            print("    [GEICO] Step 1: Hazmat question not shown for this "
                  "business class — skipping")
            return

        print(f"    [GEICO] Step 1: Hazmat placard -> {answer}")
        try:
            await self.click_question_radio(
                "require a hazardous material placard", answer
            )
        except Exception as e:
            await self.screenshot("step1_hazmat")
            raise RuntimeError(f"Hazmat placard radio click failed: {e}") from e

    async def _answer_revealed_conditionals(self) -> None:
        """Answer every business-class-dependent conditional GEICO revealed.

        Cascade-aware: answering one can reveal another (Amazon Yes would
        reveal the app picker), so loop until no unanswered group remains.
        Unknown questions HALT loudly so they get mapped instead of silently
        mis-answered; judgment-call defaults surface as warnings."""
        for _ in range(6):
            try:
                unanswered = await self.page.evaluate(_JS_UNANSWERED_GROUPS)
            except Exception:
                return
            if not isinstance(unanswered, list):
                return
            # Hazmat has its own field-mapped path; skip it here.
            pending = [
                q for q in unanswered
                if "hazardous material" not in q.lower()
            ]
            if not pending:
                return
            for question in pending:
                q_norm = " ".join(question.lower().split())
                matched = next(
                    ((n, a, s) for n, (a, s) in _CONDITIONAL_DEFAULTS
                     if n in q_norm),
                    None,
                )
                if matched is None:
                    await self.screenshot("step1_unknown_conditional")
                    raise RuntimeError(
                        f"Step 1 revealed an UNMAPPED conditional question: "
                        f"{question!r} — map it in _CONDITIONAL_DEFAULTS "
                        f"(business_class_page)."
                    )
                needle, answer, soft = matched
                if soft:
                    self.note_warning(
                        f"Step 1 conditional {needle!r} -> {answer} "
                        f"(defaulted; BlueQuote carries no answer — review)"
                    )
                else:
                    print(f"    [GEICO] Step 1 conditional "
                          f"{needle!r} -> {answer}")
                decision_ledger.record(f"Condicional Step 1: {needle}", answer,
                                       page=_PAGE, source="DEFAULT",
                                       rule_id="R-055",
                                       note="revelada por la clase de negocio")
                await self.click_question_radio(needle, answer)

    async def _click_next(self) -> None:
        """Click the bottom 'Next' button to advance to Step 2."""
        print("    [GEICO] Step 1: Clicking Next")
        try:
            await self.remove_overlays()
            await self.click_button("Next")
        except Exception as e:
            await self.screenshot("step1_next")
            raise RuntimeError(f"Could not click Next on Step 1: {e}") from e

    async def _wait_for_step2(self) -> None:
        """Dynamic outcome wait: Step 2 title (instant on success), visible
        validation (fail fast — the form refused), or GEICO's server-error
        page (fail fast — transient). 60s is only the worst-case cap for
        GEICO's slow backend (live WHITE CASTLE 2026-06-11)."""
        try:
            await self.wait_for_step_outcome(
                ["Business & Owner Info"], budget_ms=60_000
            )
            print("    [GEICO] Step 1 complete -> Step 2 loaded")
        except (RuntimeError, TimeoutError) as e:
            await self.screenshot("step1_post_next")
            raise RuntimeError(
                f"Step 2 (Business & Owner Info) did not load after Next: {e}"
            ) from e
