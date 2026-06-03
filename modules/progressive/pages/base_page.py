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
