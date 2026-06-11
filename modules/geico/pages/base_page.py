"""
Base Page Object for GEICO portal — hub of shadow-DOM-safe primitives.

Every page object MUST use these primitives instead of calling
page.fill/click/select_option directly (same discipline as the Progressive
BasePage, adapted to GEICO's front end: gds-* custom elements with shadow
DOM, native <select>s with dynamic ids, Select2 for the business class).

Families:
  A. Localización tolerante (by_label, field_exists, _flex_text_regex)
  B. Interacción verificada (safe_fill, select_by_js,
     select_by_options_signature, click_question_radio, click_button)
     — every committed value is read back and verified; retries with
     backoff; structured exceptions (_exceptions.py) carrying screenshot
     + debug context + the visible option catalog on select failures.
  C. Esperas por condición (wait_for_any_title, wait_for_title_change,
     wait_for_text)
  D. Estado de página (remove_overlays)
  E. Diagnóstico y aprendizaje (screenshot, dump_debug_context,
     note_warning/self.warnings — harvested into QuoteResult.warnings)
"""

import json
import re
from pathlib import Path
from typing import Optional, Sequence

from playwright.async_api import Page, Locator

from modules.geico.pages._exceptions import (
    FillVerifyError,
    RadioStuckError,
    SelectNotFoundError,
    SelectVerifyError,
)


def _flex_text_regex(substring: str) -> "re.Pattern":
    """Build a case-insensitive regex from `substring` that treats ASCII (')
    and typographic (’ U+2019) apostrophes as interchangeable, and collapses
    runs of whitespace. GEICO renders apostrophes as U+2019 in question text
    (e.g. "Is this the customer’s business?"), so a literal ASCII-apostrophe
    substring never matches via has_text. This regex bridges that gap."""
    # Swap apostrophes for a private-use placeholder BEFORE re.escape (which
    # would turn ' into \' and break a naive post-escape replace), then
    # substitute the apostrophe character class back in.
    _APOS = ""
    norm = substring.strip().replace("'", _APOS).replace("’", _APOS)
    parts = re.split(r"\s+", norm)
    escaped = r"\s+".join(re.escape(p) for p in parts)
    escaped = escaped.replace(_APOS, "['’]")
    return re.compile(escaped, re.IGNORECASE)


# JS shared by the verified native-select primitives. Two find modes
# (id-pattern / options-signature) × two actions (set / read-back).
# Always returns a JSON string; on failure the payload carries the select's
# visible option texts so the exception can teach the real catalog.
_JS_NATIVE_SELECT = """
    (args) => {
        const norm = (s) => (s || '').trim();
        const findSelect = () => {
            const selects = Array.from(document.querySelectorAll('select'));
            if (args.mode === 'pattern') {
                const p = (args.pattern || '').toLowerCase();
                return selects.find(
                    s => !s.disabled && s.id && s.id.toLowerCase().includes(p)
                ) || null;
            }
            const sig = args.signature || [];
            return selects.find(s => {
                if (s.disabled) return false;
                const texts = Array.from(s.options).map(o => norm(o.text));
                return sig.every(g => texts.some(t => t.includes(g)));
            }) || null;
        };
        const sel = findSelect();
        if (!sel) return JSON.stringify({error: 'no-match'});
        const optionTexts = Array.from(sel.options)
            .map(o => norm(o.text)).slice(0, 60);
        const current = () => {
            const o = sel.selectedOptions && sel.selectedOptions[0];
            return o ? norm(o.text) : '';
        };
        if (args.action === 'read') {
            return JSON.stringify(
                {found: true, value: sel.value, text: current()}
            );
        }
        // action === 'set': match by value attribute first, then by text.
        const desired = args.value;
        let chosen = null;
        for (const opt of sel.options) {
            if (opt.value === desired) { chosen = opt; break; }
        }
        if (!chosen) {
            for (const opt of sel.options) {
                if (norm(opt.text) === norm(desired)) { chosen = opt; break; }
            }
        }
        if (!chosen) {
            return JSON.stringify({
                error: 'option-not-found', id: sel.id || '',
                options: optionTexts,
            });
        }
        sel.value = chosen.value;
        sel.dispatchEvent(new Event('change', {bubbles: true}));
        return JSON.stringify({
            id: sel.id || '', value: sel.value, text: current(),
            options: optionTexts,
        });
    }
"""

# Probe the real checked state of the `answer` radio inside a
# gds-radio-button-group (evaluated ON the group element). aria-checked does
# NOT exist on gds radios — the truth is the shadow input.checked / the
# host's 'checked' attribute (diag live 2026-06-11,
# logs/diag_step1_radios.json). Returns true/false, null when unreadable.
_JS_GROUP_RADIO_STATE = """
    (g, answer) => {
        const want = (answer || '').trim().toLowerCase();
        const btns = Array.from(g.querySelectorAll('gds-radio-button'));
        const b = btns.find(x =>
                ((x.getAttribute('value') || '').trim().toLowerCase() === want))
            || btns.find(x =>
                ((x.innerText || '').trim().toLowerCase() === want));
        if (!b) return null;
        const i = b.shadowRoot
            && b.shadowRoot.querySelector('input[type=radio]');
        if (i) return i.checked;
        if (b.hasAttribute('checked')) return true;
        const aria = b.getAttribute('aria-checked');
        if (aria !== null) return aria === 'true';
        return null;
    }
"""

# True once every gds-radio-button of the question's group is HYDRATED
# (shadowRoot with an input). Groups that mount after a server round-trip
# (e.g. the FMCSA address preview) are visible before their custom elements
# upgrade — a click during that window is a silent no-op (live HUMBERTO
# 2026-06-11: 3 click rounds landed on a pre-hydration host).
_JS_GDS_GROUP_READY = """
    (src) => {
        let re;
        try { re = new RegExp(src, 'i'); } catch (e) { return true; }
        const gs = Array.from(
            document.querySelectorAll('gds-radio-button-group')
        ).filter(g => re.test(g.innerText || ''));
        if (!gs.length) return false;
        const btns = Array.from(gs[0].querySelectorAll('gds-radio-button'));
        return btns.length > 0 && btns.every(
            b => b.shadowRoot && b.shadowRoot.querySelector('input')
        );
    }
"""

# Learning-instrumentation dump: what is actually on screen right now.
_JS_DEBUG_DUMP = """
    () => {
        const vis = el => el.offsetParent !== null;
        const txt = el => (el.innerText || el.textContent || '').trim();
        const visible_buttons = Array.from(
                document.querySelectorAll('gds-button, button')
            ).filter(vis).map(txt).filter(t => t.length > 0).slice(0, 20);
        const visible_questions = Array.from(
                document.querySelectorAll('gds-radio-button-group')
            ).filter(vis).map(el => txt(el).split('\\n')[0])
             .filter(t => t.length > 0).slice(0, 15);
        const visible_selects = Array.from(
                document.querySelectorAll('select')
            ).filter(s => !s.disabled).slice(0, 10)
             .map(s => ({
                 id: s.id || '',
                 value: s.value,
                 first_options: Array.from(s.options).slice(0, 4)
                     .map(o => (o.text || '').trim()),
             }));
        return {visible_buttons, visible_questions, visible_selects};
    }
"""


class BasePage:
    """Base class for all GEICO page objects."""

    def __init__(self, page: Page):
        self.page = page
        # Fail-soft trail: pages call note_warning(); quote_flow harvests
        # this into QuoteResult.warnings so the batch report shows it.
        self.warnings: list[str] = []

    # ============================================================
    # Familia E — Diagnóstico y aprendizaje
    # ============================================================

    def note_warning(self, message: str) -> None:
        """Record a fail-soft warning: printed AND accumulated for the
        QuoteResult so it survives into the batch report."""
        print(f"    [GEICO] WARN: {message}")
        self.warnings.append(message)

    async def dump_debug_context(self, label: str) -> dict:
        """Collect URL, title, and the visible buttons/questions/selects.

        This is the learning instrumentation: when something fails, the log
        must teach the real DOM so the next fix is surgical, not guessed.
        """
        ctx: dict = {
            "label": label,
            "url": self.page.url,
            "title": None,
            "visible_buttons": [],
            "visible_questions": [],
            "visible_selects": [],
        }
        try:
            ctx["title"] = await self.page.title()
        except Exception:
            pass
        try:
            dump = await self.page.evaluate(_JS_DEBUG_DUMP)
            if isinstance(dump, dict):
                ctx.update(dump)
        except Exception:
            pass
        return ctx

    async def screenshot(self, name: str, output_dir: str = "logs") -> Optional[str]:
        """Take a screenshot for error reporting. Returns path or None."""
        try:
            path = Path(output_dir) / f"geico_{name}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            await self.page.screenshot(path=str(path), full_page=True)
            return str(path)
        except Exception as e:
            print(f"    Screenshot failed: {e}")
            return None

    # ============================================================
    # Familia A — Localización tolerante
    # ============================================================

    def by_label(self, label_text: str) -> Locator:
        """Find an input/select associated with a visible label."""
        return self.page.locator(
            f"label:has-text('{label_text}')"
        ).locator("xpath=following::input[1] | following::select[1] | following::textarea[1]")

    def by_text(self, text: str, tag: str = "*") -> Locator:
        """Find element by its visible text content."""
        return self.page.locator(f"{tag}:has-text('{text}')")

    def button(self, text: str) -> Locator:
        """Find a button or input[type=submit] by visible text."""
        return self.page.get_by_role("button", name=text)

    def radio(self, label_text: str) -> Locator:
        """Find a radio button by its label text."""
        return self.page.get_by_label(label_text)

    async def field_exists(self, locator: Locator, *, wait_ms: int = 2_000) -> bool:
        """Short-poll: True if locator has at least one visible match within
        wait_ms. Use for CONDITIONAL fields (hazmat, conditional insurance
        comboboxes, DriveEasy radios) before acting on them.

        Tolerates multi-element locators by probing `.first` (strict mode
        rejects wait_for/is_visible on multi-match locators)."""
        first = locator.first
        try:
            await first.wait_for(state="visible", timeout=wait_ms)
            return (await locator.count()) > 0 and await first.is_visible()
        except Exception:
            try:
                if (await locator.count()) > 0 and await first.is_visible():
                    return True
            except Exception:
                pass
            return False

    # ============================================================
    # Familia B — Interacción verificada
    # ============================================================

    async def safe_fill(
        self,
        locator: Locator,
        value: str,
        *,
        verify: bool = True,
        retries: int = 2,
    ) -> None:
        """Click → fill → Tab → verify input_value(). Retry on mismatch.

        Raises FillVerifyError (screenshot + debug context) after retries."""
        attempts = 0
        last_seen = ""
        for attempt in range(retries + 1):
            attempts = attempt + 1
            try:
                await locator.click(timeout=5_000)
                await locator.fill(value)
                await self.page.keyboard.press("Tab")
            except Exception as e:
                if attempt == retries:
                    debug = await self.dump_debug_context("safe_fill_action")
                    shot = await self.screenshot(f"safe_fill_action_failed_{attempts}")
                    raise FillVerifyError(
                        f"safe_fill action failed after {attempts} attempts: {e}",
                        primitive="safe_fill",
                        field=value,
                        attempts=attempts,
                        screenshot_path=shot,
                        debug_context=debug,
                    ) from e
                await self.page.wait_for_timeout(500 * (attempt + 1))
                continue

            if not verify:
                return

            try:
                last_seen = (await locator.input_value()) or ""
            except Exception:
                last_seen = ""

            if last_seen == value:
                return

            if attempt < retries:
                await self.page.wait_for_timeout(500 * (attempt + 1))

        debug = await self.dump_debug_context("safe_fill_verify")
        shot = await self.screenshot(f"safe_fill_verify_failed_{attempts}")
        raise FillVerifyError(
            f"safe_fill expected '{value}' got '{last_seen}' after {attempts} attempts",
            primitive="safe_fill",
            field=value,
            attempts=attempts,
            screenshot_path=shot,
            debug_context=debug,
        )

    async def fill_by_label(self, label_text: str, value: str) -> None:
        """Fill an input identified by its label — verified via safe_fill."""
        loc = self.by_label(label_text)
        await loc.wait_for(state="visible", timeout=10_000)
        await self.safe_fill(loc, value)

    async def click_by_text(self, text: str, tag: str = "*") -> None:
        """Click an element by visible text, removing overlays first."""
        await self.remove_overlays()
        loc = self.by_text(text, tag)
        await loc.first.click(timeout=10_000)

    async def click_button(self, text: str) -> None:
        """Click a button by visible text. GEICO uses <gds-button> custom
        elements and often renders the same action twice (top + bottom of a
        form), so a plain get_by_role can hit strict-mode or timing flakiness.

        Strategy:
          1. gds-button with the text — click the LAST visible one (the
             primary action is at the bottom of the wizard forms).
          2. role=button by name — last visible.
          3. the gds-button's shadow inner <button>, clicked via JS.

        Effect verification is the CALLER's job (wait_for_any_title /
        wait_for_title_change) — a button's outcome is page-specific.
        """
        await self.remove_overlays()
        text_re = _flex_text_regex(text)

        # 1. gds-button (visible, last).
        gds = self.page.locator("gds-button").filter(has_text=text_re)
        try:
            n = await gds.count()
            for i in range(n - 1, -1, -1):
                el = gds.nth(i)
                if await el.is_visible():
                    await el.scroll_into_view_if_needed(timeout=2_000)
                    await el.click(timeout=8_000)
                    return
        except Exception:
            pass

        # 2. role=button by name (last visible).
        try:
            role_btn = self.page.get_by_role("button", name=text)
            n = await role_btn.count()
            for i in range(n - 1, -1, -1):
                el = role_btn.nth(i)
                if await el.is_visible():
                    await el.click(timeout=8_000)
                    return
        except Exception:
            pass

        # 3. JS click the gds-button's inner shadow <button>.
        clicked = await self.page.evaluate(
            """(label) => {
                const norm = (s) => (s||'').trim().toLowerCase();
                const btns = Array.from(document.querySelectorAll('gds-button'))
                    .filter(b => norm(b.textContent).includes(norm(label)));
                for (let i = btns.length - 1; i >= 0; i--) {
                    const b = btns[i];
                    if (b.offsetParent === null) continue;  // hidden
                    const inner = (b.shadowRoot && b.shadowRoot.querySelector('button'))
                        || b.querySelector('button');
                    (inner || b).click();
                    return true;
                }
                return false;
            }""",
            text,
        )
        if not clicked:
            raise RuntimeError(f"Could not click button {text!r}")

    # ---- Verified native <select> primitives ----

    async def select_by_js(
        self, select_id_pattern: str, value: str, *, retries: int = 2
    ) -> str:
        """Find the first non-disabled <select> whose id contains the pattern
        (case-insensitive), select `value` (by value attr OR visible text),
        VERIFY the value stuck after the framework's change handlers ran,
        retry on reset. Returns the element id.

        Raises SelectNotFoundError / SelectVerifyError (with the visible
        option catalog) after retries."""
        return await self._select_native_verified(
            mode="pattern",
            pattern=select_id_pattern,
            signature=None,
            value=value,
            retries=retries,
            field_label=select_id_pattern,
        )

    async def select_by_options_signature(
        self, options_signature: list, value: str, *, retries: int = 2
    ) -> str:
        """Find the first non-disabled <select> whose options CONTAIN all the
        given texts (ids are dynamic; the option list is the stable
        signature), select `value`, VERIFY it stuck, retry on reset.
        Returns the element id ('' if the element has no id).

        Raises SelectNotFoundError / SelectVerifyError (with the visible
        option catalog) after retries."""
        return await self._select_native_verified(
            mode="signature",
            pattern=None,
            signature=list(options_signature),
            value=value,
            retries=retries,
            field_label=f"signature {options_signature}",
        )

    def _select_value_committed(self, desired: str, payload: dict) -> bool:
        """True when the read-back state matches the desired option."""
        want = (desired or "").strip()
        return (
            (payload.get("text") or "").strip() == want
            or (payload.get("value") or "") == desired
        )

    async def _select_native_verified(
        self,
        *,
        mode: str,
        pattern: Optional[str],
        signature: Optional[list],
        value: str,
        retries: int,
        field_label: str,
    ) -> str:
        """Core of the verified select primitives: set → read back → retry."""
        base_args = {"mode": mode, "pattern": pattern, "signature": signature}
        attempts = 0
        last_failure: tuple = ("unknown", {})

        for attempt in range(retries + 1):
            attempts = attempt + 1
            raw = await self.page.evaluate(
                _JS_NATIVE_SELECT,
                {**base_args, "action": "set", "value": value},
            )
            result = json.loads(raw)

            if result.get("error") == "no-match":
                last_failure = ("no-match", result)
            elif result.get("error") == "option-not-found":
                last_failure = ("option-not-found", result)
            else:
                # Set reported OK. The framework's change handlers may reset
                # the value asynchronously — give them a beat, then read back.
                await self.page.wait_for_timeout(150)
                raw2 = await self.page.evaluate(
                    _JS_NATIVE_SELECT, {**base_args, "action": "read"}
                )
                readback = json.loads(raw2)
                if readback.get("found") and self._select_value_committed(
                    value, readback
                ):
                    return result.get("id", "")
                last_failure = ("reset", {**result, "readback": readback})

            if attempt < retries:
                await self.page.wait_for_timeout(400 * (attempt + 1))

        kind, payload = last_failure
        debug = await self.dump_debug_context(f"select_{mode}")
        shot = await self.screenshot(f"select_failed_{mode}_{attempts}")
        if kind == "no-match":
            raise SelectNotFoundError(
                f"No non-disabled <select> matching {field_label}",
                primitive=f"select_by_{mode}",
                field=field_label,
                attempts=attempts,
                screenshot_path=shot,
                debug_context=debug,
            )
        raise SelectVerifyError(
            f"<select id={payload.get('id')!r}> ({field_label}): value "
            f"{value!r} {'not among options' if kind == 'option-not-found' else 'did not stick (framework reset)'} "
            f"after {attempts} attempts",
            primitive=f"select_by_{mode}",
            field=field_label,
            attempts=attempts,
            available_options=payload.get("options", []),
            screenshot_path=shot,
            debug_context=debug,
        )

    async def click_shadow_radio(self, shadow_id: str) -> None:
        """Click a custom radio whose real input lives in shadow DOM
        (selector `#{shadow_id}`). Encountered for MFA radios and form radios.
        """
        await self.page.locator(f"#{shadow_id}").click(timeout=10_000)

    async def click_question_radio(
        self,
        question_substring: str,
        answer: str,
        timeout: int = 10_000,
        retries: int = 2,
    ) -> None:
        """Click the radio labeled `answer` (e.g. "Yes"/"No"/"Employee") for
        the question whose visible text contains `question_substring`, then
        VERIFY the radio actually became checked.

        GEICO uses its own design system: each question is a custom element
        `<gds-radio-button-group>` (light-DOM children `<gds-radio-button
        value="Yes">` / `value="No">`, exposed to the a11y tree as role=radio).
        The actual <input>s live in shadow DOM, so a light-DOM `[role=radio]`
        query finds NOTHING — the radio MUST be reached via the custom element.
        There are many such groups on a page (14+ on Step 1), so the radio is
        scoped to its question's group. Verified live 2026-05-28.

        Click strategies, in order:
          1. <gds-radio-button-group>:has(question) -> gds-radio-button[value=answer]
          2. same group -> gds-radio-button whose visible text == answer
             (covers cases where value is a code, not the label)
          3. same group -> role=radio by accessible name
          4. same group -> exact answer label text
          5. generic role=group fallback (non-gds pages, if any)

        Verification (shadow-DOM aware): a11y is_checked first, then a JS
        probe of the custom element's shadow input. Three outcomes:
          * checked        -> done.
          * unreadable     -> note_warning('unverified') and continue —
                              never block a quote on unreadable shadow state.
          * unchecked      -> retry the click; after retries raise
                              RadioStuckError (screenshot + debug dump).
        Radio re-clicks are idempotent (unlike toggles), so retrying a click
        that silently landed is safe.
        """
        answer = answer.strip()
        q_re = _flex_text_regex(question_substring)

        gds_group = self.page.locator("gds-radio-button-group").filter(has_text=q_re)

        # Wait for the question group to render before probing (the SPA may
        # not have painted it yet right after a step transition — an immediate
        # count()==0 caused flaky "Could not click radio" failures).
        try:
            await gds_group.first.wait_for(state="visible", timeout=timeout)
        except Exception:
            pass  # strategies below may still find it via role=group

        # Visible != interactive: wait for the group's custom elements to
        # hydrate (soft — non-gds fallback pages have no such elements).
        await self.wait_for_gds_radios_ready(q_re, timeout_ms=8_000)

        # Pre-check: some radios arrive already checked (USDOT 'Yes', the
        # FMCSA-preview 'Yes' on some quotes). Skip the click entirely.
        if await self._radio_checked_state(gds_group, answer) is True:
            return

        attempts_locators = []
        # 1. value attribute match (Yes/No and most labels).
        attempts_locators.append(
            gds_group.locator(f'gds-radio-button[value="{answer}"]')
        )
        # 2. gds-radio-button whose trimmed text is exactly the answer.
        answer_re = re.compile(rf"^\s*{re.escape(answer)}\s*$")
        attempts_locators.append(
            gds_group.locator("gds-radio-button").filter(has_text=answer_re)
        )
        # 3. accessible radio role within the group.
        attempts_locators.append(
            gds_group.get_by_role("radio", name=answer, exact=True)
        )
        # 4. exact answer label text within the group.
        attempts_locators.append(gds_group.get_by_text(answer, exact=True))
        # 5. generic fallback: role=group + text-anchor.
        grp = self.page.get_by_role("group").filter(has_text=q_re)
        attempts_locators.append(grp.get_by_role("radio", name=answer, exact=True))

        last_err = None
        total_rounds = 0
        for round_idx in range(retries + 1):
            total_rounds = round_idx + 1
            clicked = False
            for loc in attempts_locators:
                try:
                    if await loc.count() == 0:
                        continue
                    el = loc.first
                    try:
                        await el.scroll_into_view_if_needed(timeout=3_000)
                    except Exception:
                        pass
                    await el.click(timeout=timeout)
                    clicked = True
                    break
                except Exception as e:  # noqa: PERF203
                    last_err = e
                    continue

            if clicked:
                state = await self._poll_radio_checked(gds_group, answer)
                if state is True:
                    return
                if state is None:
                    self.note_warning(
                        f"radio {answer!r} for {question_substring!r}: "
                        f"checked-state unreadable (shadow DOM) — click unverified"
                    )
                    return
                # state is False -> the click did not commit; retry.

            if round_idx < retries:
                await self.page.wait_for_timeout(400 * (round_idx + 1))

        debug = await self.dump_debug_context("click_question_radio")
        shot = await self.screenshot(f"radio_stuck_{answer}_{total_rounds}")
        raise RadioStuckError(
            f"Could not verify {answer!r} checked for question "
            f"{question_substring!r} after {total_rounds} attempts "
            f"(last error: {last_err})",
            primitive="click_question_radio",
            field=question_substring,
            attempts=total_rounds,
            screenshot_path=shot,
            debug_context=debug,
        )

    async def wait_for_gds_radios_ready(
        self, question_re: "re.Pattern", *, timeout_ms: int = 8_000
    ) -> bool:
        """Wait until every gds-radio-button of the question's group has its
        shadow input (= hydrated and clickable). Soft: returns False on
        timeout instead of raising — generic role=group fallback pages have
        no gds elements at all."""
        try:
            await self.page.wait_for_function(
                _JS_GDS_GROUP_READY,
                arg=question_re.pattern,
                timeout=timeout_ms,
            )
            return True
        except Exception:
            return False

    async def _radio_checked_state(
        self, gds_group: Locator, answer: str
    ) -> Optional[bool]:
        """Read the checked state of the `answer` radio inside the group.

        JS probe first — the truth is the shadow input.checked / host
        'checked' attribute; aria-checked does not exist on gds radios
        (diag live 2026-06-11). a11y is_checked as fallback. Returns None
        when no strategy could read the state.
        """
        try:
            state = await gds_group.first.evaluate(
                _JS_GROUP_RADIO_STATE, answer
            )
            if isinstance(state, bool):
                return state
        except Exception:
            pass
        try:
            radio = gds_group.get_by_role("radio", name=answer, exact=True).first
            return bool(await radio.is_checked())
        except Exception:
            return None

    async def _poll_radio_checked(
        self,
        gds_group: Locator,
        answer: str,
        *,
        attempts: int = 8,
        interval_ms: int = 200,
    ) -> Optional[bool]:
        """Poll the checked state after a click — the design system commits
        a beat later. True as soon as seen; None (unreadable) immediately;
        False after the budget."""
        last: Optional[bool] = None
        for i in range(attempts):
            last = await self._radio_checked_state(gds_group, answer)
            if last is True:
                return True
            if last is None:
                return None
            if i < attempts - 1:
                await self.page.wait_for_timeout(interval_ms)
        return last

    # ============================================================
    # DEPRECATED select helpers — unverified; do not use in new code.
    # Kept only until every caller migrates to the verified primitives.
    # ============================================================

    async def select_by_label(self, label_text: str, value: str) -> None:
        """DEPRECATED — prefer select_by_options_signature / select_by_js."""
        loc = self.by_label(label_text)
        await loc.wait_for(state="visible", timeout=10_000)
        try:
            await loc.select_option(value=value, timeout=5_000)
        except Exception:
            await loc.evaluate(
                f"(el) => {{ el.value = '{value}'; el.dispatchEvent(new Event('change', {{bubbles: true}})); }}"
            )

    async def select_option_by_text(self, label_text: str, option_text: str) -> None:
        """DEPRECATED — prefer select_by_options_signature / select_by_js."""
        loc = self.by_label(label_text)
        await loc.wait_for(state="visible", timeout=10_000)
        try:
            await loc.select_option(label=option_text, timeout=5_000)
        except Exception:
            await loc.evaluate(
                f"""(el) => {{
                    const opt = Array.from(el.options).find(o => o.text.includes('{option_text}'));
                    if (opt) {{ el.value = opt.value; el.dispatchEvent(new Event('change', {{bubbles: true}})); }}
                }}"""
            )

    # ============================================================
    # Familia D — Estado de página
    # ============================================================

    async def remove_overlays(self) -> None:
        """Remove invisible modal overlays that intercept clicks."""
        await self.page.evaluate("""
            () => {
                document.querySelectorAll('.modalOverlay, .modal-backdrop, [class*="overlay"]')
                    .forEach(el => el.remove());
            }
        """)

    # ============================================================
    # Familia C — Esperas por condición
    # ============================================================

    async def wait_for_text(self, text: str, timeout: int = 15_000) -> None:
        """Wait until text appears on page."""
        await self.page.get_by_text(text).wait_for(state="visible", timeout=timeout)

    async def wait_for_title_change(
        self, previous_title: str, timeout: int = 30_000
    ) -> None:
        """Wait until document.title changes away from `previous_title`.

        GEICO is an SPA: `networkidle` resolves before the wizard swaps the
        step content, and step names live in a persistent side-nav, so
        `wait_for_text` matches the next step's breadcrumb prematurely (and
        leaves us interacting with the previous step's DOM). document.title is
        the only signal that reliably flips when the new step actually mounts.
        """
        await self.page.wait_for_function(
            "(prev) => document.title && document.title !== prev",
            arg=previous_title,
            timeout=timeout,
        )

    async def wait_for_any_title(
        self, substrings: Sequence[str], *, timeout_ms: int = 20_000
    ) -> str:
        """Wait until document.title contains ANY of `substrings`; return the
        one that matched. For transitions with more than one legitimate
        destination (e.g. Step 5 -> DriveEasy Pro OR straight to Quote &
        Coverages when the server skips telematics).

        Raises TimeoutError (with the current title) when none appears.
        """
        candidates = list(substrings)
        try:
            await self.page.wait_for_function(
                "(subs) => subs.some(s => document.title && document.title.includes(s))",
                arg=candidates,
                timeout=timeout_ms,
            )
        except Exception as e:
            try:
                current = await self.page.title()
            except Exception:
                current = "?"
            raise TimeoutError(
                f"wait_for_any_title: none of {candidates} appeared within "
                f"{timeout_ms}ms (title={current!r})"
            ) from e
        title = await self.page.title()
        for s in candidates:
            if s in title:
                return s
        return title

    async def wait_for_navigation(self, timeout: int = 30_000) -> None:
        """Wait for page navigation to complete.

        NOTE: networkidle is NOT a step-transition signal on this SPA — use
        wait_for_any_title / wait_for_title_change for that. This helper is
        only for genuine full-page navigations (login redirects, new tabs).
        """
        await self.page.wait_for_load_state("networkidle", timeout=timeout)
