"""
Login Page Object for Progressive portal.

Handles: navigate to login -> enter credentials -> submit -> enter OTP -> continue.
"""

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

        # Enter credentials (validated label-based selectors)
        print("    [Progressive] Entering credentials...")
        await self.page.get_by_role("textbox", name="User ID").fill(username)
        await self.page.get_by_role("textbox", name="User Password").fill(password)

        # Record time BEFORE clicking login (for OTP timestamp filter)
        login_time = datetime.now(timezone.utc)

        # Submit login form
        await self.page.get_by_role("button", name="Log In").click()
        await self.page.wait_for_load_state("networkidle", timeout=15_000)

        # Check if OTP page appeared
        otp_visible = await self._is_otp_page()
        if not otp_visible:
            if "home" in self.page.url.lower() or "foragentsonly.com" in self.page.url.lower():
                print("    [Progressive] Logged in (no OTP required)")
                return True
            print("    [Progressive] Login failed - unexpected page")
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
        await self.page.wait_for_load_state("networkidle", timeout=15_000)

        # Verify we reached the dashboard
        if "home" in self.page.url.lower() or "foragentsonly" in self.page.url.lower():
            print("    [Progressive] Login successful")
            return True

        print(f"    [Progressive] Unexpected URL after OTP: {self.page.url}")
        return False

    async def _is_otp_page(self) -> bool:
        """Check if the current page is asking for an OTP."""
        try:
            for text in ["passcode", "one-time", "verification code", "OTP"]:
                loc = self.page.get_by_text(text, exact=False)
                if await loc.count() > 0:
                    return True
            return False
        except Exception:
            return False

    async def _enter_otp(self, otp: str) -> None:
        """Enter the 6-digit OTP and submit."""
        selectors = [
            'input[name*="passcode" i]',
            'input[name*="otp" i]',
            'input[name*="code" i]',
            'input[name*="token" i]',
            'input[type="tel"]',
            'input[type="number"]',
        ]
        for sel in selectors:
            loc = self.page.locator(sel)
            if await loc.count() > 0:
                await loc.first.fill(otp)
                break

        # Submit OTP
        await self.remove_overlays()
        for btn_text in ["Continue", "Submit", "Verify", "Log In"]:
            btn = self.page.get_by_role("button", name=btn_text)
            if await btn.count() > 0:
                await btn.first.click()
                return
        # Fallback: press Enter
        await self.page.keyboard.press("Enter")
