"""
DriveEasy Pro Page Object for GEICO wizard (Step 5b — dynamic).

Title: `GEICO DriveEasy Pro`. This page is a telematics opt-in that GEICO
shows CONDITIONALLY between Step 5 (Additional Business Info) and Step 6
(Quote & Coverages), depending on the customer's eligibility (vehicle age,
ELD answer in Step 1, fleet size, etc.). The page is NOT guaranteed to
appear on every quote.

Default policy (this block): always SKIP via the
`Continue without driveEasy Pro` button. BlueQuotes do not currently request
telemática enrollment, so we avoid the opt-in extras (per
`docs/Proceso GEICO.md` Step 5b note: "Default field_mapper:
choose_driveeasy_pro = False").

Future hook
-----------
A future block could add an `opt_in(option: str)` method to actually enroll
in OBD / Dashcam / ELD. The radio option labels are exposed as the
module-level `DRIVEEASY_OPTIONS` list so a forward-compatible API can
reference them without re-hardcoding strings:

    page = DriveEasyProPage(page)
    await page.opt_in(DRIVEEASY_OPTIONS[0])  # e.g. "Customer's ELD"

Note: eligibility per option is dynamic (e.g. ELD requires ELD=Yes in
Step 1; Dashcam INELIGIBLE for older vehicles), so the future
implementation would need to detect disabled radios and surface a
fallback.
"""

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from modules.geico.pages.base_page import BasePage


# Module-level constants for forward reference (see "Future hook" above).
# Order matches the visual order of the radios on the page.
DRIVEEASY_OPTIONS: list[str] = [
    "Customer's ELD",
    "Dashcam from GEICO",
    "OBD from GEICO",
]


class DriveEasyProPage(BasePage):
    """GEICO wizard Step 5b — DriveEasy Pro (dynamic telematics opt-in)."""

    # Short wait — this page may not appear at all, don't burn time.
    _DETECT_TIMEOUT_MS = 5_000
    # Generous wait once we've clicked Skip — Step 6 load can vary.
    _NAV_TIMEOUT_MS = 20_000

    async def skip_to_coverages(self) -> None:
        """
        Click 'Continue without driveEasy Pro' button. This page may not
        appear on every quote (dynamic — depends on eligibility). If the
        page is not detected after a brief wait, log a warning and return
        (caller proceeds to Step 6 'Quote & Coverages').

        Pre-state: 'DriveEasy Pro' title OR Step 6 already loaded
                   (page skipped).
        Post-state: 'Quote & Coverages' title.
        """
        # 1. Fast-path: are we already past this page?
        try:
            current_title = await self.page.title()
        except Exception:
            current_title = ""
        if "Quote & Coverages" in current_title:
            print(
                "    [GEICO] Step 5b: Quote & Coverages already loaded "
                "(DriveEasy Pro skipped by server)"
            )
            return

        print("    [GEICO] Step 5b: DriveEasy Pro (detecting...)")

        # 2. Wait for EITHER DriveEasy Pro OR Quote & Coverages title to
        # appear within DETECT_TIMEOUT. If neither, raise — we genuinely
        # don't know which page we're on and Block 4 would interact with
        # the wrong DOM. (Previous behavior — silent return on timeout —
        # caused a race: if DriveEasy renders >5s but eventually shows,
        # the caller would think we'd skipped past it.)
        try:
            await self.page.wait_for_function(
                "() => document.title.includes('DriveEasy Pro') "
                "    || document.title.includes('Quote & Coverages')",
                timeout=self._DETECT_TIMEOUT_MS,
            )
        except PlaywrightTimeoutError as e:
            await self.screenshot("step5b_no_page_detected")
            raise RuntimeError(
                f"Step 5b: neither 'DriveEasy Pro' nor 'Quote & Coverages' "
                f"appeared within {self._DETECT_TIMEOUT_MS}ms; flow is in "
                f"an unknown state."
            ) from e

        # If Quote & Coverages won the race, the page was server-side skipped.
        current_title = await self.page.title()
        if "Quote & Coverages" in current_title and "DriveEasy Pro" not in current_title:
            print(
                "    [GEICO] Step 5b: server-side skip detected "
                "(Quote & Coverages loaded directly)"
            )
            return

        # 3. Page is shown — click the skip button.
        print(
            "    [GEICO] Step 5b: Clicking 'Continue without driveEasy Pro'..."
        )
        await self.remove_overlays()
        try:
            btn = self.page.get_by_role(
                "button", name="Continue without driveEasy Pro"
            )
            await btn.first.click(timeout=10_000)
        except Exception as e:
            await self.screenshot("step5b_skip_click_error")
            raise RuntimeError(
                f"Failed to click 'Continue without driveEasy Pro': {e}"
            ) from e

        # 4. Wait for Step 6 to load.
        try:
            await self.page.wait_for_function(
                "() => document.title.includes('Quote & Coverages')",
                timeout=self._NAV_TIMEOUT_MS,
            )
            print(
                "    [GEICO] Step 5b -> Step 6 (Quote & Coverages) loaded"
            )
        except Exception as e:
            await self.screenshot("step5b_to_step6_navigation_error")
            raise RuntimeError(
                f"DriveEasy Pro skip did not advance to Quote & Coverages: {e}"
            ) from e
