"""
Home Page Object for Progressive portal.

Handles: state selection -> product selection -> USDOT search -> "Add Products to Quote".
After this page, a new tab opens with the quote wizard.

All selectors validated live at foragentsonly.com/home on 2026-04-09.
"""

from playwright.async_api import Page, BrowserContext

from modules.progressive.pages.base_page import BasePage


# State code -> option text (for the QuoteStateList dropdown on the dashboard)
STATE_NAMES = {
    "TX": "Texas",
    "OK": "Oklahoma",
    "LA": "Louisiana",
}


class HomePage(BasePage):
    """Progressive dashboard after login."""

    async def start_new_quote(self, usdot: str, context: BrowserContext) -> Page:
        """
        Execute the full dashboard flow: state -> product -> USDOT -> new tab.

        Args:
            usdot: USDOT number to search.
            context: browser context (needed to detect new tab).

        Returns:
            The new Page (tab) that opens with the quote wizard.

        Raises:
            RuntimeError: if USDOT not found or flow fails.
        """
        await self._select_state("TX")
        await self._select_product_commercial_auto()
        await self._search_usdot(usdot)
        new_page = await self._add_products_to_quote(context)
        return new_page

    async def _select_state(self, state_code: str) -> None:
        """Select state from the 'New Quote' dropdown. Always TX."""
        state_name = STATE_NAMES.get(state_code, state_code)
        print(f"    [Progressive] Selecting state: {state_name}")
        # After login Progressive runs a federated-login redirect chain
        # (foragentsonly.com/federatedlogin/signin -> /home). The New Quote
        # panel only exists once that settles, so wait for the home page to
        # finish loading before looking for the dropdown (a short attached-wait
        # raced the redirect and timed out intermittently).
        try:
            await self.page.wait_for_load_state("networkidle", timeout=30_000)
        except Exception:
            pass
        # The state dropdown has a stable id #QuoteStateList.
        dropdown = self.page.locator("#QuoteStateList")
        await dropdown.wait_for(state="visible", timeout=30_000)
        await dropdown.select_option(label=state_name, timeout=10_000)
        # Dropdown has onchange=BuildProductSelector that renders the Select Product button
        await self.page.wait_for_timeout(500)

    async def _select_product_commercial_auto(self) -> None:
        """Click 'Select Product(s)' and choose 'Commercial Auto'."""
        print("    [Progressive] Selecting product: Commercial Auto")
        # Click Select Product(s) - id is stable. The button is rendered by the
        # state dropdown's onchange (BuildProductSelector), so it can resolve in
        # the DOM before it is actually visible — wait for visibility and scroll
        # it into view to avoid a flaky "element is not visible" click timeout.
        select_btn = self.page.locator("#selectProductButton")
        await select_btn.wait_for(state="visible", timeout=15_000)
        try:
            await select_btn.scroll_into_view_if_needed(timeout=3_000)
        except Exception:
            pass
        await select_btn.click(timeout=10_000)
        await self.page.wait_for_timeout(500)

        # Wait for the product flyout popup to appear
        popup = self.page.locator(".pp-popup-box")
        await popup.wait_for(state="visible", timeout=10_000)

        # Click Commercial Auto - data-pp-id="CV" is stable
        await self.page.locator('[data-pp-id="CV"]').first.click(timeout=10_000)
        await self.page.wait_for_timeout(500)

        # After selecting Commercial Auto, a "Check USDOT number?" link appears
        # Click it to open the USDOT widget
        check_usdot = self.page.locator(
            '.pp-popup-box a:has-text("Check USDOT")'
        )
        if await check_usdot.count() > 0:
            await check_usdot.first.click(timeout=5_000)
            await self.page.wait_for_timeout(800)

    async def _search_usdot(self, usdot: str) -> None:
        """Enter USDOT and search. Raises RuntimeError if not found."""
        print(f"    [Progressive] Searching USDOT: {usdot}")

        # Fill USDOT input - id is stable
        usdot_input = self.page.locator("#USDOTNumber")
        await usdot_input.wait_for(state="visible", timeout=10_000)
        await usdot_input.fill(usdot, timeout=5_000)

        # Click Search button inside the widget (class base-btn without --alt modifier)
        search_btn = self.page.locator(
            '.us-dot-cl-widget__btn.base-btn:not(.base-btn--alt)'
        )
        await search_btn.first.click(timeout=5_000)

        # Wait for results table or error to appear
        await self.page.wait_for_timeout(3_000)

        # Check for error message
        err = self.page.locator(
            '.js-us-dot-cl-widget__error-message-placeholder:not(.hidden)'
        )
        if await err.count() > 0:
            err_text = (await err.first.inner_text()).strip()
            if err_text:
                raise RuntimeError(f"USDOT {usdot} lookup failed: {err_text}")

        # Verify the results table has data (SAFER Business Name row)
        results = self.page.locator('.us-dot-cl-widget__results tbody tr')
        if await results.count() == 0:
            raise RuntimeError(f"USDOT {usdot} returned no results")

        print(f"    [Progressive] USDOT {usdot} found")

    async def _add_products_to_quote(self, context: BrowserContext) -> Page:
        """Click 'Add Products to Quote' and return the new tab."""
        print("    [Progressive] Adding products to quote...")

        # Button id is stable: #quoteActionSelectButton
        async with context.expect_page(timeout=20_000) as new_page_info:
            await self.page.locator("#quoteActionSelectButton").first.click(timeout=10_000)

        new_page = await new_page_info.value
        await new_page.wait_for_load_state("networkidle", timeout=60_000)
        print(f"    [Progressive] Wizard opened: {new_page.url[:80]}...")
        return new_page
