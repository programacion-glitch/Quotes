"""
Base Page Object for Progressive portal.

Provides shared helpers for all page objects. Uses label-based selectors
because Progressive generates dynamic GUID IDs on every page load.
"""

from pathlib import Path
from typing import Optional
from playwright.async_api import Page, Locator


class BasePage:
    """Base class for all Progressive page objects."""

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
        """Click a button by visible text, removing overlays first."""
        await self.remove_overlays()
        btn = self.button(text)
        await btn.click(timeout=10_000)

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

    async def wait_for_navigation(self, timeout: int = 30_000) -> None:
        """Wait for page navigation to complete."""
        await self.page.wait_for_load_state("networkidle", timeout=timeout)

    # ---- Error handling ----

    async def screenshot(self, name: str, output_dir: str = "logs") -> Optional[str]:
        """Take a screenshot for error reporting. Returns path or None."""
        try:
            path = Path(output_dir) / f"progressive_{name}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            await self.page.screenshot(path=str(path), full_page=True)
            return str(path)
        except Exception as e:
            print(f"    Screenshot failed: {e}")
            return None
