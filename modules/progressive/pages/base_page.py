"""Base Page Object for Progressive portal.

Hub of ExtJS-safe primitives. Every page object MUST use these primitives
instead of calling page.fill/click/select_option directly.

5 families of primitives:
  A. Localización tolerante (find_by_label_text, find_radiogroup, ...)
  B. Interacción ExtJS-safe (safe_fill, safe_radio, safe_click_continue, ...)
  C. Esperas dinámicas (wait_for_extjs_idle, wait_for_field_revealed_by, ...)
  D. Estado de página (remove_overlays, blur_active_element, current_page_token)
  E. Diagnóstico (screenshot, dump_debug_context)

DEPRECATED helpers (by_label, fill_by_label, ...) are kept until phase 7
to avoid breaking pages not yet migrated. New code MUST NOT use them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse, parse_qs

from playwright.async_api import Locator, Page


class BasePage:
    """Hub of ExtJS-safe primitives for all Progressive page objects."""

    def __init__(self, page: Page):
        self.page = page

    # ============================================================
    # Familia D — Estado de página
    # ============================================================

    async def remove_overlays(self) -> None:
        """Remove invisible modal overlays that intercept clicks."""
        await self.page.evaluate(
            """() => {
                document.querySelectorAll(
                    '.modalOverlay, .modal-backdrop, [class*="overlay"]'
                ).forEach(el => el.remove());
            }"""
        )

    async def blur_active_element(self) -> None:
        """Blur the active element so ExtJS commits pending state."""
        await self.page.evaluate(
            """() => {
                if (document.activeElement && document.activeElement.blur) {
                    document.activeElement.blur();
                }
            }"""
        )

    async def current_page_token(self) -> str:
        """Extract pageName query param from the current URL."""
        parsed = urlparse(self.page.url)
        qs = parse_qs(parsed.query)
        return qs.get("pageName", [""])[0]

    # ============================================================
    # Familia E — Diagnóstico
    # ============================================================

    async def screenshot(self, name: str, *, output_dir: str = "logs") -> Optional[Path]:
        """Take a screenshot for error reporting. Returns path or None."""
        try:
            path = Path(output_dir) / f"progressive_{name}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            await self.page.screenshot(path=str(path), full_page=True)
            return path
        except Exception as e:
            print(f"    [Progressive] screenshot failed: {e}")
            return None

    async def dump_debug_context(self, label: str) -> dict[str, Any]:
        """Collect URL, pageName, title, visible button labels for error context."""
        try:
            visible_buttons = await self.page.evaluate(
                """() => Array.from(document.querySelectorAll(
                    'button, a.x-btn, .x-btn-inner'
                )).filter(el => el.offsetParent !== null)
                  .map(el => (el.innerText || '').trim())
                  .filter(t => t.length > 0)
                  .slice(0, 20)"""
            )
        except Exception:
            visible_buttons = []
        return {
            "label": label,
            "url": self.page.url,
            "pageName": await self.current_page_token(),
            "visible_buttons": visible_buttons,
        }

    # ============================================================
    # Familia A — Localización tolerante
    # ============================================================

    async def find_by_label_text(
        self, label: str, *, kind: str = "input", timeout_ms: int = 5_000
    ) -> Locator:
        """Find an input by XPath traversal from its visible label text.

        Used for fields where Progressive's ExtJS overlay hides the
        placeholder attribute, so get_by_placeholder fails.
        """
        label_loc = self.page.get_by_text(label, exact=True)
        xpath_target = {
            "input": "xpath=following::input[@type='text'][1]",
            "textarea": "xpath=following::textarea[1]",
        }.get(kind, "xpath=following::input[@type='text'][1]")
        return label_loc.locator(xpath_target)

    async def find_by_placeholder(
        self, placeholder: str, *, timeout_ms: int = 5_000
    ) -> Locator:
        """Find an input by its real placeholder attribute (when ExtJS exposes it)."""
        return self.page.get_by_placeholder(placeholder)

    async def find_radiogroup(
        self, name: str, *, exact: bool = False, timeout_ms: int = 5_000
    ) -> Locator:
        """Find a radiogroup by its accessible name (partial match by default)."""
        return self.page.get_by_role("radiogroup", name=name, exact=exact)

    async def find_combo(
        self, name: str, *, exact: bool = False, timeout_ms: int = 5_000
    ) -> Locator:
        """Find an ExtJS combobox by its accessible name."""
        return self.page.get_by_role("combobox", name=name, exact=exact)

    async def field_exists(self, locator: Locator, *, wait_ms: int = 2_000) -> bool:
        """Short-poll: True if locator has count > 0 AND is visible within wait_ms.

        Used for CONDITIONAL fields that may not render for some
        commodity types (e.g. ELD radio absent for Beverage Distributor).
        """
        try:
            await locator.wait_for(state="visible", timeout=wait_ms)
            return (await locator.count()) > 0 and await locator.is_visible()
        except Exception:
            try:
                if (await locator.count()) > 0 and await locator.is_visible():
                    return True
            except Exception:
                pass
            return False

    # ============================================================
    # Familia B — Interacción ExtJS-safe (obligatorias)
    # ============================================================

    async def safe_fill(
        self,
        locator: Locator,
        value: str,
        *,
        verify: bool = True,
        retries: int = 2,
    ) -> None:
        """Click → fill → Tab → verify input_value(). Retry on mismatch."""
        from modules.progressive.pages._exceptions import FillVerifyError

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
                    screenshot = await self.screenshot(f"safe_fill_action_failed_{attempts}")
                    raise FillVerifyError(
                        f"safe_fill action failed after {attempts} attempts: {e}",
                        primitive="safe_fill",
                        field=value,
                        attempts=attempts,
                        screenshot_path=screenshot,
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
        screenshot = await self.screenshot(f"safe_fill_verify_failed_{attempts}")
        raise FillVerifyError(
            f"safe_fill expected '{value}' got '{last_seen}' after {attempts} attempts",
            primitive="safe_fill",
            field=value,
            attempts=attempts,
            screenshot_path=screenshot,
            debug_context=debug,
        )

    async def safe_radio(
        self,
        group: Locator,
        option: str,
        *,
        retries: int = 3,
    ) -> None:
        """Click radio by visible name within group; verify is_checked. Retry escalating force."""
        from modules.progressive.pages._exceptions import RadioStuckError

        radio = group.get_by_role("radio", name=option, exact=True)
        attempts = 0
        for attempt in range(retries + 1):
            attempts = attempt + 1
            try:
                if attempt == 0:
                    await radio.click(timeout=5_000)
                elif attempt == 1:
                    await radio.click(timeout=5_000, force=True)
                else:
                    await radio.check(force=True, timeout=5_000)
            except Exception:
                pass

            try:
                if await radio.is_checked():
                    return
            except Exception:
                pass

            if attempt < retries:
                await self.page.wait_for_timeout(500 * (attempt + 1))

        debug = await self.dump_debug_context("safe_radio")
        screenshot = await self.screenshot(f"safe_radio_stuck_{option}_{attempts}")
        raise RadioStuckError(
            f"safe_radio could not check '{option}' after {attempts} attempts",
            primitive="safe_radio",
            field=option,
            attempts=attempts,
            screenshot_path=screenshot,
            debug_context=debug,
        )

    async def safe_checkbox(
        self,
        locator: Locator,
        *,
        check: bool = True,
        retries: int = 2,
    ) -> None:
        """Toggle checkbox only if current state differs from desired; verify."""
        from modules.progressive.pages._exceptions import RadioStuckError

        attempts = 0
        for attempt in range(retries + 1):
            attempts = attempt + 1
            try:
                current = await locator.is_checked()
            except Exception:
                current = not check
            if current == check:
                return
            try:
                await locator.click(timeout=5_000, force=(attempt > 0))
            except Exception:
                pass
            try:
                if await locator.is_checked() == check:
                    return
            except Exception:
                pass
            if attempt < retries:
                await self.page.wait_for_timeout(500 * (attempt + 1))

        debug = await self.dump_debug_context("safe_checkbox")
        screenshot = await self.screenshot(f"safe_checkbox_stuck_{attempts}")
        raise RadioStuckError(
            f"safe_checkbox could not set state={check} after {attempts} attempts",
            primitive="safe_checkbox",
            field=None,
            attempts=attempts,
            screenshot_path=screenshot,
            debug_context=debug,
        )

    async def safe_select_combo(
        self,
        combo: Locator,
        option_text: str,
        *,
        retries: int = 2,
    ) -> None:
        """ExtJS combo: click combo → click option by role → verify input_value contains text."""
        from modules.progressive.pages._exceptions import ComboSelectError

        attempts = 0
        last_value = ""
        for attempt in range(retries + 1):
            attempts = attempt + 1
            try:
                await combo.click(timeout=5_000)
                await self.page.wait_for_timeout(300)
                option = self.page.get_by_role("option", name=option_text, exact=True)
                await option.click(timeout=5_000)
                await self.page.keyboard.press("Tab")
            except Exception:
                pass

            try:
                last_value = (await combo.input_value()) or ""
            except Exception:
                last_value = ""

            if option_text.lower() in last_value.lower():
                return

            if attempt < retries:
                await self.page.wait_for_timeout(500 * (attempt + 1))

        debug = await self.dump_debug_context("safe_select_combo")
        screenshot = await self.screenshot(f"safe_combo_failed_{attempts}")
        raise ComboSelectError(
            f"safe_select_combo expected '{option_text}' got '{last_value}' after {attempts} attempts",
            primitive="safe_select_combo",
            field=option_text,
            attempts=attempts,
            screenshot_path=screenshot,
            debug_context=debug,
        )

    async def safe_click_continue(
        self,
        *,
        expect_url_changes_from: str,
        retries: int = 3,
    ) -> None:
        """Click 'Continue' robustly: blur → text-based locator → force=True → JS dispatch fallback.

        Verifies URL no longer contains `expect_url_changes_from` token.
        Raises ContinueStuckError if URL never advances.
        """
        from modules.progressive.pages._exceptions import ContinueStuckError

        await self.blur_active_element()
        await self.page.wait_for_timeout(300)

        attempts = 0
        for attempt in range(retries + 1):
            attempts = attempt + 1
            try:
                btn = self.page.get_by_text("Continue", exact=True).last
                await btn.scroll_into_view_if_needed(timeout=2_000)
                await btn.click(timeout=10_000, force=True)
            except Exception:
                try:
                    btn = self.page.get_by_role("button", name="Continue").last
                    await btn.click(timeout=5_000, force=True)
                except Exception:
                    pass

            try:
                await self.page.wait_for_load_state("networkidle", timeout=30_000)
            except Exception:
                pass

            if expect_url_changes_from not in self.page.url:
                return

            if attempt >= 1:
                try:
                    await self.page.evaluate(
                        """() => {
                            const spans = Array.from(document.querySelectorAll('span'))
                              .filter(s => (s.innerText || '').trim() === 'Continue');
                            for (const span of spans) {
                                let el = span;
                                while (el && !(el.classList && el.classList.contains('x-btn'))) {
                                    el = el.parentElement;
                                }
                                if (el) {
                                    ['mousedown','mouseup','click'].forEach(t =>
                                        el.dispatchEvent(new MouseEvent(t, {bubbles: true}))
                                    );
                                    return;
                                }
                            }
                        }"""
                    )
                    await self.page.wait_for_timeout(1_500)
                    if expect_url_changes_from not in self.page.url:
                        return
                except Exception:
                    pass

            if attempt < retries:
                await self.page.wait_for_timeout(1_000 * (attempt + 1))

        debug = await self.dump_debug_context("safe_click_continue")
        screenshot = await self.screenshot(f"continue_stuck_{expect_url_changes_from}_{attempts}")
        raise ContinueStuckError(
            f"safe_click_continue: URL still contains '{expect_url_changes_from}' after {attempts} attempts",
            primitive="safe_click_continue",
            field=None,
            attempts=attempts,
            screenshot_path=screenshot,
            debug_context=debug,
        )

    # ============================================================
    # Familia C — Esperas dinámicas
    # ============================================================

    async def wait_for_extjs_idle(self, *, timeout_ms: int = 10_000) -> None:
        """Wait until ExtJS finishes: no pending Ajax, no visible masks, document ready."""
        await self.page.wait_for_function(
            """() => {
                const extQuiet = typeof Ext === 'undefined' ||
                                 !Ext.Ajax || !Ext.Ajax.isLoading();
                const noMask = !document.querySelector('.x-mask:not(.x-mask-fixed)');
                const ready = document.readyState === 'complete';
                return extQuiet && noMask && ready;
            }""",
            timeout=timeout_ms,
        )

    async def wait_for_page(self, page_name_token: str, *, timeout_ms: int = 30_000) -> None:
        """Poll until URL contains pageName=<page_name_token>. Raises TimeoutError if not."""
        import asyncio
        deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
        while asyncio.get_event_loop().time() < deadline:
            token = await self.current_page_token()
            if token == page_name_token or page_name_token in self.page.url:
                return
            await self.page.wait_for_timeout(200)
        raise TimeoutError(
            f"wait_for_page: token '{page_name_token}' not seen within {timeout_ms}ms; url={self.page.url}"
        )

    async def wait_for_field_revealed_by(
        self,
        trigger_fn,
        target_finder,
        *,
        timeout_ms: int = 5_000,
    ) -> Locator:
        """Run trigger_fn, then poll target_finder until the returned locator is visible."""
        import asyncio
        import inspect

        if inspect.iscoroutinefunction(trigger_fn):
            await trigger_fn()
        else:
            trigger_fn()

        deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
        while asyncio.get_event_loop().time() < deadline:
            result = target_finder()
            if inspect.iscoroutine(result):
                result = await result
            try:
                if (await result.count()) > 0 and await result.is_visible():
                    return result
            except Exception:
                pass
            await self.page.wait_for_timeout(150)

        result = target_finder()
        if inspect.iscoroutine(result):
            result = await result
        return result

    async def wait_for_currency_formatted(
        self,
        locator: Locator,
        *,
        timeout_ms: int = 3_000,
    ) -> None:
        """Wait until input_value contains '$' (ExtJS finished currency formatting)."""
        import asyncio
        deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
        while asyncio.get_event_loop().time() < deadline:
            try:
                v = await locator.input_value()
                if "$" in (v or ""):
                    return
            except Exception:
                pass
            await self.page.wait_for_timeout(150)

    # ============================================================
    # DEPRECATED helpers — kept until phase 7 cleanup
    # ============================================================

    def by_label(self, label_text: str) -> Locator:
        """DEPRECATED — use find_by_label_text. Kept for un-migrated pages."""
        return self.page.locator(
            f"label:has-text('{label_text}')"
        ).locator("xpath=following::input[1] | following::select[1] | following::textarea[1]")

    async def fill_by_label(self, label_text: str, value: str) -> None:
        """DEPRECATED — use safe_fill. Kept for un-migrated pages."""
        loc = self.by_label(label_text)
        await loc.wait_for(state="visible", timeout=10_000)
        await loc.fill(value)

    async def click_by_text(self, text: str, tag: str = "*") -> None:
        """DEPRECATED — use safe_click_continue or direct get_by_text. Kept."""
        await self.remove_overlays()
        loc = self.page.locator(f"{tag}:has-text('{text}')").first
        await loc.click(timeout=10_000)

    async def click_button(self, text: str) -> None:
        """DEPRECATED — use safe_click_continue. Kept for un-migrated pages."""
        await self.remove_overlays()
        await self.page.get_by_role("button", name=text).click(timeout=10_000)

    async def select_by_label(self, label_text: str, value: str) -> None:
        """DEPRECATED — use safe_select_combo. Kept for un-migrated pages."""
        loc = self.by_label(label_text)
        await loc.wait_for(state="visible", timeout=10_000)
        await loc.select_option(value=value, timeout=5_000)

    async def select_option_by_text(self, label_text: str, option_text: str) -> None:
        """DEPRECATED — use safe_select_combo. Kept for un-migrated pages."""
        loc = self.by_label(label_text)
        await loc.wait_for(state="visible", timeout=10_000)
        await loc.select_option(label=option_text, timeout=5_000)

    async def wait_for_text(self, text: str, timeout: int = 15_000) -> None:
        """DEPRECATED — use wait_for_page. Kept for un-migrated pages."""
        await self.page.get_by_text(text).wait_for(state="visible", timeout=timeout)

    async def wait_for_navigation(self, timeout: int = 30_000) -> None:
        """DEPRECATED. Kept for un-migrated pages."""
        await self.page.wait_for_load_state("networkidle", timeout=timeout)
