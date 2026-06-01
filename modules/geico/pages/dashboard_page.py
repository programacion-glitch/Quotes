"""
Dashboard Page Object for GEICO Gateway portal.

This is the page at `gateway.geico.com/quote` that loads AFTER login. It performs
server-side eligibility checks for USDOT and ZIP before letting the user open
the quote wizard. Flow:

    1. Select "Commercial Auto" product (label click — the real checkbox is hidden).
    2. Fill USDOT and press "Check USDOT" — GEICO calls back with Eligible / Not Eligible.
    3. Fill ZIP code — GEICO auto-checks (no submit button) and autopopulates State.
    4. Click "Start New Quote" — opens the wizard in a NEW TAB.

See `docs/Proceso GEICO.md` for the full screen-by-screen flow.

Important: GEICO's server-side criteria differ from Progressive's. For example,
USDOT 2998569 (M&D CUSTOM FREIGHT LLC) is eligible at Progressive but rejected
by GEICO at this dashboard. When that happens we raise `EligibilityHaltError`
and the orchestrator should fall back to another MGA rather than retry.

All selectors validated live during the GEICO mapping session.
"""

from playwright.async_api import Page, BrowserContext

from modules.geico.pages.base_page import BasePage


class EligibilityHaltError(RuntimeError):
    """Raised when GEICO server-side eligibility check rejects USDOT or ZIP."""


class DashboardPage(BasePage):
    """GEICO Gateway dashboard — eligibility gate before the quote wizard."""

    async def start_new_quote(
        self, usdot: str, zip_code: str, context: BrowserContext
    ) -> Page:
        """
        Execute dashboard flow: select Commercial Auto -> check USDOT eligibility ->
        check ZIP eligibility -> Start New Quote -> new tab opens.

        Returns the new Page (wizard tab).

        Raises:
            EligibilityHaltError: USDOT or ZIP rejected by GEICO server-side.
            RuntimeError: any other failure.
        """
        await self._ensure_on_quote_dashboard()
        await self._select_commercial_auto()
        await self._check_usdot_eligibility(usdot)
        await self._check_zip_eligibility(zip_code)
        new_page = await self._click_start_new_quote(context)
        return new_page

    async def _ensure_on_quote_dashboard(self) -> None:
        """Make sure we're on the dashboard page that exposes the
        'Commercial Auto' eligibility widget (#labelForCommercialAuto).

        After login GEICO may land on gateway.geico.com/dashboard, but the
        eligibility widget lives on /quote. If the label isn't present
        quickly, navigate to /quote explicitly.
        """
        label = self.page.locator("#labelForCommercialAuto")
        try:
            if await label.count() > 0 and await label.first.is_visible():
                return
        except Exception:
            pass
        target = "https://gateway.geico.com/quote"
        print(f"    [GEICO] Commercial Auto widget not here; navigating to {target}")
        try:
            await self.page.goto(target, wait_until="networkidle", timeout=30_000)
            await label.first.wait_for(state="visible", timeout=15_000)
        except Exception as e:
            await self.screenshot("dashboard_quote_nav_failed")
            raise RuntimeError(
                f"Could not reach the Commercial Auto dashboard at {target}: {e}"
            ) from e

    async def _select_commercial_auto(self) -> None:
        """
        Click the Commercial Auto label (real checkbox input is hidden).
        After click, the other product checkboxes become `disabled` because
        they are mutually exclusive with Commercial Auto.
        """
        print("    [GEICO] Selecting product: Commercial Auto")
        try:
            label = self.page.locator("#labelForCommercialAuto")
            await label.wait_for(state="visible", timeout=10_000)
            await label.click(timeout=10_000)
            # Give the ZIP/USDOT input section a moment to render.
            await self.page.wait_for_timeout(500)
        except Exception as e:
            raise RuntimeError(
                f"Failed to select Commercial Auto product: {e}"
            ) from e

    async def _check_usdot_eligibility(self, usdot: str) -> None:
        """
        Fill USDOT, press 'Check USDOT', wait for server response, then assert
        the 'Eligible' confirmation appeared. If 'Not Eligible' shows up, halt.
        """
        print(f"    [GEICO] Checking USDOT eligibility: {usdot}")
        try:
            # Prefer id-pattern match (case-insensitive); fall back to label.
            usdot_input = self.page.locator('[id*="UsDotNumber" i]').first
            if await usdot_input.count() == 0:
                usdot_input = self.page.get_by_label("USDOT Number", exact=False)
            await usdot_input.wait_for(state="visible", timeout=10_000)
            await usdot_input.fill(usdot, timeout=5_000)

            check_btn = self.page.get_by_role("button", name="Check USDOT")
            await check_btn.first.click(timeout=10_000)
        except EligibilityHaltError:
            raise
        except Exception as e:
            raise RuntimeError(
                f"Failed to submit USDOT {usdot} for eligibility check: {e}"
            ) from e

        # The server-side check is async with no spinner. Poll for a clear
        # result (eligible OR not-eligible) instead of a fixed sleep — GEICO's
        # latency varies and a fixed 3s sometimes returned "no clear result".
        success_text = "This USDOT number is eligible for insurance coverage at this time"
        not_eligible = self.page.get_by_text("Not Eligible", exact=False)
        success_msg = self.page.get_by_text(success_text, exact=False)
        for _ in range(30):  # up to ~15s (30 * 500ms)
            try:
                if await not_eligible.count() > 0 and await not_eligible.first.is_visible():
                    print(f"    [GEICO] USDOT {usdot} REJECTED by server-side check")
                    raise EligibilityHaltError(
                        f"USDOT {usdot} not eligible per GEICO criteria"
                    )
                if await success_msg.count() > 0 and await success_msg.first.is_visible():
                    print(f"    [GEICO] USDOT {usdot} eligible")
                    return
            except EligibilityHaltError:
                raise
            except Exception:
                pass
            await self.page.wait_for_timeout(500)

        raise RuntimeError(
            f"USDOT {usdot} eligibility check returned no clear result "
            f"(timed out waiting for eligible/not-eligible)"
        )

    async def _check_zip_eligibility(self, zip_code: str) -> None:
        """
        Fill ZIP code. GEICO triggers the eligibility check automatically on
        blur/input — there is NO submit button. The State combobox autopopulates
        (disabled) and the Start New Quote button morphs from <button disabled>
        into an <a target="_blank"> link.
        """
        print(f"    [GEICO] Checking ZIP eligibility: {zip_code}")
        try:
            zip_input = self.page.get_by_role("searchbox", name="ZIP Code")
            if await zip_input.count() == 0:
                zip_input = self.page.locator('[id*="ZipCode" i]').first
            await zip_input.wait_for(state="visible", timeout=10_000)
            await zip_input.fill(zip_code, timeout=5_000)
            # Blur to trigger the server-side check (Locator has no .blur(),
            # so we evaluate on the underlying element).
            await zip_input.evaluate("el => el.blur()")
        except EligibilityHaltError:
            raise
        except Exception as e:
            raise RuntimeError(
                f"Failed to submit ZIP {zip_code} for eligibility check: {e}"
            ) from e

        # Poll for a clear ZIP result instead of a fixed sleep.
        zip_success = self.page.get_by_text(
            "This ZIP Code is eligible for insurance coverage at this time",
            exact=False,
        )
        not_eligible = self.page.get_by_text("Not Eligible", exact=False)
        for _ in range(30):  # up to ~15s
            try:
                if await zip_success.count() > 0 and await zip_success.first.is_visible():
                    print(f"    [GEICO] ZIP {zip_code} eligible")
                    return
                # Any visible "Not Eligible" while the ZIP success hasn't shown
                # is treated as a ZIP rejection.
                ne = await not_eligible.count()
                for i in range(ne):
                    if await not_eligible.nth(i).is_visible():
                        print(f"    [GEICO] ZIP {zip_code} REJECTED by server-side check")
                        raise EligibilityHaltError(f"ZIP {zip_code} not eligible")
            except EligibilityHaltError:
                raise
            except Exception:
                pass
            await self.page.wait_for_timeout(500)

        raise RuntimeError(
            f"ZIP {zip_code} eligibility check returned no clear result "
            f"(timed out)"
        )

    async def _click_start_new_quote(self, context: BrowserContext) -> Page:
        """
        Click the Start New Quote link (it's an <a target="_blank"> after the
        eligibility checks pass) and capture the new tab via expect_page.
        """
        print("    [GEICO] Clicking Start New Quote (expecting new tab)...")
        try:
            async with context.expect_page(timeout=20_000) as new_page_info:
                await self.page.get_by_role(
                    "link", name="Start New Quote"
                ).first.click(timeout=10_000)
            new_page = await new_page_info.value
            await new_page.wait_for_load_state("networkidle", timeout=60_000)
            print(f"    [GEICO] Wizard opened: {new_page.url[:80]}...")
            return new_page
        except Exception as e:
            raise RuntimeError(
                f"Failed to open the GEICO quote wizard in a new tab: {e}"
            ) from e
