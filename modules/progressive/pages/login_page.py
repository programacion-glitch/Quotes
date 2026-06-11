"""
Login Page Object for Progressive portal.

Handles: navigate to login -> enter credentials -> submit -> enter OTP -> continue.
"""

import time
from datetime import datetime, timezone

from playwright.async_api import Page

from modules.progressive.pages.base_page import BasePage
from modules.progressive.otp_reader import GmailOTPReader


class LoginPage(BasePage):
    """Progressive login + OTP flow."""

    LOGIN_URL = "https://www.foragentsonly.com/home/?Welcome=584"
    # Note: this URL redirects to foragentsonlylogin.progressive.com/Login/ for unauthenticated users.

    def __init__(self, page: Page, otp_reader: GmailOTPReader):
        super().__init__(page)
        self.otp_reader = otp_reader

    async def login(self, username: str, password: str) -> bool:
        """
        Full login flow: credentials -> OTP -> dashboard.

        Returns True if login succeeds, False otherwise.
        """
        print("    [Progressive] Navigating to login page...")
        await self.page.goto(self.LOGIN_URL, wait_until="networkidle", timeout=30_000)

        # With a restored session (client storage_state) the Welcome URL does
        # NOT redirect to foragentsonlylogin — we land authenticated on the
        # agent dashboard and there is no login form to fill.
        if "foragentsonlylogin" not in self.page.url.lower():
            user_field = self.page.get_by_role("textbox", name="User ID")
            if await user_field.count() == 0:
                print(
                    "    [Progressive] Session restored — already "
                    "authenticated (no login/OTP needed)"
                )
                return True

        # Enter credentials (validated label-based selectors)
        print("    [Progressive] Entering credentials...")
        await self.safe_fill(
            self.page.get_by_role("textbox", name="User ID"),
            username,
            verify=False,  # password managers may prevent input_value() read
        )
        await self.safe_fill(
            self.page.get_by_role("textbox", name="User Password"),
            password,
            verify=False,  # password field: input_value() always returns ""
        )

        # Record time BEFORE clicking login (for OTP timestamp filter)
        login_time = datetime.now(timezone.utc)

        # Submit login form — "Log In" is NOT a wizard Continue; keep as direct click.
        await self.page.get_by_role("button", name="Log In").click(force=True, timeout=10_000)

        # The login XHR keeps the button spinning well past networkidle
        # (observed live 2026-06-10: a screenshot caught the spinner while the
        # old load-state wait had already returned). Poll for a definitive
        # outcome instead of trusting load-state timing.
        outcome = await self._wait_login_outcome(timeout_s=45)

        if outcome == "home":
            print("    [Progressive] Logged in (no OTP required)")
            return True
        if outcome == "rejected":
            await self.screenshot("login_rejected")
            print("    [Progressive] Login rejected — invalid credentials")
            return False
        if outcome == "unknown":
            await self.screenshot("login_unknown_state")
            print(
                f"    [Progressive] Login outcome unknown after wait — "
                f"url={self.page.url}"
            )
            return False

        # Fetch OTP from Gmail
        print("    [Progressive] Waiting for OTP...")
        otp = self.otp_reader.fetch_otp(sent_after=login_time)
        if not otp:
            print("    [Progressive] OTP not received within timeout")
            return False

        print(f"    [Progressive] OTP received: {otp[:2]}****")

        # Enter OTP
        await self._enter_otp(otp)
        # Post-OTP redirect settles via networkidle (not ExtJS).
        await self.page.wait_for_load_state("networkidle", timeout=15_000)

        # Verify we reached the dashboard
        if "home" in self.page.url.lower() or "foragentsonly" in self.page.url.lower():
            print("    [Progressive] Login successful")
            return True

        print(f"    [Progressive] Unexpected URL after OTP: {self.page.url}")
        return False

    async def _wait_login_outcome(self, timeout_s: float = 45.0) -> str:
        """Poll until the post-Log-In state is definitive.

        Returns one of:
          "otp"      — the OTP input is actually visible
          "home"     — landed back on foragentsonly.com (no MFA required)
          "rejected" — a credentials error message is visible
          "unknown"  — nothing definitive within timeout_s
        """
        deadline = time.monotonic() + timeout_s
        while True:
            if await self._is_otp_page():
                return "otp"

            url = self.page.url.lower()
            # Authenticated users land on foragentsonly.com; unauthenticated
            # flows live on foragentsonlylogin.progressive.com. The query
            # string is NOT a discriminator: a device-trusted re-login (no
            # OTP) bounces back to the original /home/?Welcome=584 URL
            # (observed live 2026-06-11) — so confirm by the ABSENCE of the
            # login form instead of by URL params.
            if "foragentsonly.com" in url and "foragentsonlylogin" not in url:
                try:
                    form = self.page.get_by_role("textbox", name="User ID")
                    if await form.count() == 0 or not await form.first.is_visible():
                        return "home"
                except Exception:
                    pass

            for phrase in (
                "incorrect", "invalid", "locked", "does not match",
                "unable to log", "try again",
            ):
                try:
                    loc = self.page.get_by_text(phrase, exact=False)
                    if await loc.count() > 0 and await loc.first.is_visible():
                        return "rejected"
                except Exception:
                    pass

            if time.monotonic() >= deadline:
                return "unknown"
            # Poll cadence while the Log In spinner / redirect chain settles.
            await self.page.wait_for_timeout(500)

    async def _is_otp_page(self) -> bool:
        """Check if the current page is REALLY asking for an OTP.

        The login page itself can contain words like "passcode"/"OTP" in
        static text, so text matching alone gives a false positive when the
        login is rejected (observed live 2026-06-10: wrong password reported
        as "OTP not received"). Require an actual visible OTP input instead.
        """
        try:
            primary = self.page.get_by_role("textbox", name="One-time passcode")
            if await primary.count() > 0 and await primary.first.is_visible():
                return True
            # Legacy multi-MfaOtpEntry variant: any visible candidate input.
            legacy = self.page.locator(
                'input[name*="passcode" i], input[name*="otp" i], '
                'input[name*="MfaOtpEntry" i]'
            )
            for i in range(await legacy.count()):
                if await legacy.nth(i).is_visible():
                    return True
            return False
        except Exception:
            return False

    async def _enter_otp(self, otp: str) -> None:
        """Enter the 6-digit OTP and submit.

        Progressive's OTP page renders the input with an accessible label
        "One-time passcode" (validated live 2026-06-01). Older flows used
        name="MfaOtpEntry" with one input per MFA delivery method, only the
        chosen one visible. We try the role/label selector first (most
        robust to internal name changes) and fall back to the name-based
        selectors for the multi-input variant.
        """
        # Primary: accessible role + label (matches current page).
        primary = self.page.get_by_role("textbox", name="One-time passcode")
        if await primary.count() > 0:
            try:
                # verify=False: OTP inputs often block input_value() for security.
                await self.safe_fill(primary.first, otp, verify=False)
            except Exception:
                primary = None  # fall through to legacy selectors
        else:
            primary = None

        if primary is None:
            # Legacy multi-MfaOtpEntry path: find the visible one.
            selectors = [
                'input[name*="passcode" i]',
                'input[name*="otp" i]',
                'input[name*="code" i]',
                'input[name*="token" i]',
                'input[type="tel"]',
                'input[type="number"]',
            ]
            filled = False
            for sel in selectors:
                loc = self.page.locator(sel)
                n = await loc.count()
                for i in range(n):
                    el = loc.nth(i)
                    try:
                        if await el.is_visible():
                            # verify=False: OTP inputs often block input_value() for security.
                            await self.safe_fill(el, otp, verify=False)
                            filled = True
                            break
                    except Exception:
                        continue
                if filled:
                    break
            if not filled:
                await self.screenshot("otp_no_visible_input")
                raise RuntimeError(
                    "Could not find a visible OTP input to fill "
                    "(neither 'One-time passcode' textbox nor legacy MfaOtpEntry inputs)"
                )

        # Submit OTP — these are MFA form buttons, NOT wizard Continue buttons.
        await self.remove_overlays()
        for btn_text in ["Continue", "Submit", "Verify", "Log In"]:
            btn = self.page.get_by_role("button", name=btn_text)
            if await btn.count() > 0:
                await btn.first.click(force=True, timeout=10_000)
                return
        # Fallback: press Enter
        await self.page.keyboard.press("Enter")
