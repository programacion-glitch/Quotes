"""
Base Page Object for GEICO portal.

Provides shared helpers for all page objects. Uses label-based selectors
because GEICO (like Progressive) generates dynamic IDs on every page load.

Note: GEICO uses both native `<select>` and Sencha/custom comboboxes —
`select_by_js` and `select_by_options_signature` are the proven fallbacks
from the live-mapping session. Some radio inputs live inside shadow DOM,
which is handled by `click_shadow_radio`.
"""

import re
from pathlib import Path
from typing import Optional
from playwright.async_api import Page, Locator


def _flex_text_regex(substring: str) -> "re.Pattern":
    """Build a case-insensitive regex from `substring` that treats ASCII (')
    and typographic (’ U+2019) apostrophes as interchangeable, and collapses
    runs of whitespace. GEICO renders apostrophes as U+2019 in question text
    (e.g. "Is this the customer’s business?"), so a literal ASCII-apostrophe
    substring never matches via has_text. This regex bridges that gap."""
    # Swap apostrophes for a private-use placeholder BEFORE re.escape (which
    # would turn ' into \' and break a naive post-escape replace), then
    # substitute the apostrophe character class back in.
    _APOS = ""
    norm = substring.strip().replace("'", _APOS).replace("’", _APOS)
    parts = re.split(r"\s+", norm)
    escaped = r"\s+".join(re.escape(p) for p in parts)
    escaped = escaped.replace(_APOS, "['’]")
    return re.compile(escaped, re.IGNORECASE)


class BasePage:
    """Base class for all GEICO page objects."""

    def __init__(self, page: Page):
        self.page = page

    # ---- Selectors ----

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

    # ---- Actions ----

    async def fill_by_label(self, label_text: str, value: str) -> None:
        """Fill an input field identified by its label."""
        loc = self.by_label(label_text)
        await loc.wait_for(state="visible", timeout=10_000)
        await loc.fill(value)

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

    async def select_by_label(self, label_text: str, value: str) -> None:
        """Select a dropdown option by label. Falls back to JS if needed."""
        loc = self.by_label(label_text)
        await loc.wait_for(state="visible", timeout=10_000)
        try:
            await loc.select_option(value=value, timeout=5_000)
        except Exception:
            # Fallback: set value via JS and dispatch change event
            await loc.evaluate(
                f"(el) => {{ el.value = '{value}'; el.dispatchEvent(new Event('change', {{bubbles: true}})); }}"
            )

    async def select_option_by_text(self, label_text: str, option_text: str) -> None:
        """Select a dropdown option by visible option text."""
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

    # ---- GEICO-specific helpers ----

    # JS helper shared by both select helpers: try matching `desired` against
    # option.value first, then against option.text (visible label). The latter
    # is critical because many <option> use a non-label `value` attribute
    # (e.g. <option value="1">Single</option>) — setting select.value="Single"
    # would silently no-op without this fallback.
    _JS_SET_OPTION_BY_VALUE_OR_TEXT = """
        function setOption(select, desired) {
            const norm = (s) => (s || '').trim();
            // Try value attribute first
            for (const opt of select.options) {
                if (opt.value === desired) {
                    select.value = desired;
                    select.dispatchEvent(new Event('change', {bubbles: true}));
                    return true;
                }
            }
            // Fall back to visible text
            for (const opt of select.options) {
                if (norm(opt.text) === norm(desired)) {
                    select.value = opt.value;
                    select.dispatchEvent(new Event('change', {bubbles: true}));
                    return true;
                }
            }
            return false;
        }
    """

    async def select_by_js(self, select_id_pattern: str, value: str) -> str:
        """
        Find first non-disabled <select> whose id matches the substring
        (case-insensitive), select an option whose value OR visible text
        matches `value`, dispatch change event. Returns element id.

        Raises if no <select> matches the id pattern, or if no option
        matched `value` by either attribute.
        """
        js = self._JS_SET_OPTION_BY_VALUE_OR_TEXT + """
            const pattern = args.pattern.toLowerCase();
            const value = args.value;
            const selects = Array.from(document.querySelectorAll('select'));
            const match = selects.find(s =>
                !s.disabled && s.id && s.id.toLowerCase().includes(pattern)
            );
            if (!match) return JSON.stringify({error: 'no-match'});
            const ok = setOption(match, value);
            if (!ok) return JSON.stringify({error: 'option-not-found', id: match.id});
            return JSON.stringify({id: match.id});
        """
        raw = await self.page.evaluate(
            "(args) => { " + js + " }",
            {"pattern": select_id_pattern, "value": value},
        )
        import json as _json
        result = _json.loads(raw)
        if result.get("error") == "no-match":
            raise RuntimeError(
                f"No non-disabled <select> matching id pattern '{select_id_pattern}'"
            )
        if result.get("error") == "option-not-found":
            raise RuntimeError(
                f"<select id={result.get('id')!r}> has no option with value or text {value!r}"
            )
        return result["id"]

    async def select_by_options_signature(
        self, options_signature: list[str], value: str
    ) -> str:
        """
        Find first non-disabled <select> whose options array CONTAINS all
        the given option texts (useful when id varies but options are stable;
        e.g. for the "Years operating" combobox we use ["Less than 1", "7+"]
        as signature). Selects an option whose value OR visible text matches
        `value`. Returns element id (may be empty string if the element has
        no id attribute).

        Raises if no <select> matches the signature, or if no option matches
        `value`.
        """
        js = self._JS_SET_OPTION_BY_VALUE_OR_TEXT + """
            const signature = args.signature;
            const value = args.value;
            const selects = Array.from(document.querySelectorAll('select'));
            const match = selects.find(s => {
                if (s.disabled) return false;
                const texts = Array.from(s.options).map(o => (o.text || '').trim());
                return signature.every(sig => texts.some(t => t.includes(sig)));
            });
            if (!match) return JSON.stringify({error: 'no-match'});
            const ok = setOption(match, value);
            if (!ok) return JSON.stringify({error: 'option-not-found', id: match.id});
            return JSON.stringify({id: match.id || ''});
        """
        raw = await self.page.evaluate(
            "(args) => { " + js + " }",
            {"signature": options_signature, "value": value},
        )
        import json as _json
        result = _json.loads(raw)
        if result.get("error") == "no-match":
            raise RuntimeError(
                f"No non-disabled <select> matching options signature {options_signature}"
            )
        if result.get("error") == "option-not-found":
            raise RuntimeError(
                f"<select id={result.get('id')!r} matched by signature {options_signature}> "
                f"has no option with value or text {value!r}"
            )
        return result["id"]

    async def click_shadow_radio(self, shadow_id: str) -> None:
        """
        Click a custom radio whose real input lives in shadow DOM
        (selector `#{shadow_id}`). Encountered for MFA radios and form radios.
        """
        await self.page.locator(f"#{shadow_id}").click(timeout=10_000)

    async def click_question_radio(
        self, question_substring: str, answer: str, timeout: int = 10_000
    ) -> None:
        """Click the radio labeled `answer` (e.g. "Yes"/"No"/"Employee") for
        the question whose visible text contains `question_substring`.

        GEICO uses its own design system: each question is a custom element
        `<gds-radio-button-group>` (light-DOM children `<gds-radio-button
        value="Yes">` / `value="No">`, exposed to the a11y tree as role=radio).
        The actual <input>s live in shadow DOM, so a light-DOM `[role=radio]`
        query finds NOTHING — the radio MUST be reached via the custom element.
        There are many such groups on a page (14+ on Step 1), so the radio is
        scoped to its question's group. Verified live 2026-05-28.

        Strategies, in order:
          1. <gds-radio-button-group>:has(question) -> gds-radio-button[value=answer]
          2. same group -> gds-radio-button whose visible text == answer
             (covers cases where value is a code, not the label)
          3. same group -> role=radio by accessible name
          4. same group -> exact answer label text
        Raises RuntimeError if none work.
        """
        answer = answer.strip()
        # Apostrophe-flexible, whitespace-flexible matcher for the question.
        q_re = _flex_text_regex(question_substring)
        attempts = []

        # GEICO design-system group scoped to the question.
        gds_group = self.page.locator("gds-radio-button-group").filter(has_text=q_re)

        # Wait for the question group to render before probing (the SPA may not
        # have painted it yet right after a step transition — an immediate
        # count()==0 caused flaky "Could not click radio ... : None" failures).
        try:
            await gds_group.first.wait_for(state="visible", timeout=timeout)
        except Exception:
            # Fall through; the strategies below may still find it via the
            # generic role=group path, or raise a clear error.
            pass
        # 1. value attribute match (Yes/No and most labels).
        attempts.append(gds_group.locator(f'gds-radio-button[value="{answer}"]'))
        # 2. gds-radio-button whose trimmed text is exactly the answer.
        answer_re = re.compile(rf"^\s*{re.escape(answer)}\s*$")
        attempts.append(
            gds_group.locator("gds-radio-button").filter(has_text=answer_re)
        )
        # 3. accessible radio role within the group.
        attempts.append(gds_group.get_by_role("radio", name=answer, exact=True))
        # 4. exact answer label text within the group.
        attempts.append(gds_group.get_by_text(answer, exact=True))

        # Generic fallbacks (non-gds pages, if any): role=group + text-anchor.
        grp = self.page.get_by_role("group").filter(has_text=q_re)
        attempts.append(grp.get_by_role("radio", name=answer, exact=True))

        last_err = None
        for loc in attempts:
            try:
                if await loc.count() == 0:
                    continue
                el = loc.first
                try:
                    await el.scroll_into_view_if_needed(timeout=3_000)
                except Exception:
                    pass
                await el.click(timeout=timeout)
                await self.page.wait_for_timeout(300)
                return
            except Exception as e:  # noqa: PERF203
                last_err = e
                continue

        raise RuntimeError(
            f"Could not click {answer!r} radio for question "
            f"{question_substring!r}: {last_err}"
        )

    # ---- Overlay handling ----

    async def remove_overlays(self) -> None:
        """Remove invisible modal overlays that intercept clicks."""
        await self.page.evaluate("""
            () => {
                document.querySelectorAll('.modalOverlay, .modal-backdrop, [class*="overlay"]')
                    .forEach(el => el.remove());
            }
        """)

    # ---- Waits ----

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

    async def wait_for_navigation(self, timeout: int = 30_000) -> None:
        """Wait for page navigation to complete."""
        await self.page.wait_for_load_state("networkidle", timeout=timeout)

    # ---- Error handling ----

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
