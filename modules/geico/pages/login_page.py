"""
Login Page Object for GEICO portal (Azure B2C).

Flow (very different from Progressive's ForAgentsOnly):
  1. Navigate to GEICO_LOGIN_URL (long Azure B2C URL with PKCE params).
  2. Fill Username + Password, click "Sign in".
  3. Azure redirects through "Loading..." then a "User details" MFA selector.
  4. Pick the Email radio (custom radio whose real input is `#extension_mfaByPhoneOrEmail_email`).
  5. Click Continue. Page shows masked email + "Send verification code" button.
  6. Click "Send verification code" (record login_time first, for OTP filter).
  7. Wait for "Verification code" textbox, fetch OTP via GeicoOTPReader, fill, click "Verify code".
  8. Click "Continue" -> redirect to gateway.geico.com/quote.
"""

from datetime import datetime, timezone
from urllib.parse import urlparse

from playwright.async_api import Page

from modules.geico.pages.base_page import BasePage
from modules.geico.otp_reader import GeicoOTPReader


def _host_is_gateway(url: str) -> bool:
    """True only when the URL's actual HOST is gateway.geico.com.

    Must parse the host — a plain substring check matches the
    `relayState=https%3A%2F%2Fgateway.geico.com%2FDashboard` query param
    on the b2clogin authorize URL and falsely reports a completed login.
    """
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return host == "gateway.geico.com" or host.endswith(".gateway.geico.com")


class LoginPage(BasePage):
    """GEICO Azure B2C login + email-MFA flow."""

    GATEWAY_HOST = "gateway.geico.com"

    def __init__(self, page: Page, otp_reader: GeicoOTPReader, login_url: str):
        super().__init__(page)
        self.otp_reader = otp_reader
        self.login_url = login_url

    async def login(self, username: str, password: str) -> bool:
        """Full login flow: credentials -> MFA email -> OTP -> gateway.

        Returns True on success, False on any failure (with screenshot).
        """
        try:
            print("    [GEICO] Navigating to login entry point...")
            await self.page.goto(self.login_url, wait_until="networkidle", timeout=45_000)

            # The entry point bounces gateway -> ecams -> b2clogin; the chain
            # may still be settling. Wait for the sign-in form. Do NOT treat a
            # transient gateway URL as "authenticated" — a fresh (cookieless)
            # browser is never pre-authenticated, and an eager host check here
            # produced false positives (landed on a stale gateway URL, then
            # /quote 404'd). A genuinely-authenticated session would skip the
            # username field; we detect that by the wait timing out AND the
            # gateway dashboard being present, handled in the poll below.
            print("    [GEICO] Waiting for the sign-in form...")
            username_box = self.page.get_by_role("textbox", name="Username")
            try:
                await username_box.wait_for(state="visible", timeout=30_000)
            except Exception:
                # No sign-in form. If we're genuinely on the gateway with the
                # dashboard rendered, accept it; otherwise re-raise.
                if _host_is_gateway(self.page.url):
                    print(f"    [GEICO] Already authenticated -> {self.page.url}")
                    return True
                raise

            print("    [GEICO] Entering credentials...")
            await username_box.fill(username)
            await self.page.get_by_role("textbox", name="Password").fill(password)
            await self.page.get_by_role("button", name="Sign in").click()
        except Exception as e:
            print(f"    [GEICO] Credential step failed: {e}")
            await self.screenshot("login_credentials_fail")
            return False

        # After Sign in, GEICO does ONE of two things:
        #   (a) Requires MFA -> shows the Email/Phone method selector.
        #   (b) Logs straight through to the gateway (trusted device/IP, or
        #       MFA only enforced periodically).
        # Poll for whichever happens first instead of assuming MFA always
        # appears (the latter caused false "login failed" when GEICO skipped
        # MFA and went directly to gateway.geico.com/dashboard).
        print("    [GEICO] Waiting for MFA selector or gateway redirect...")
        mfa_radio = self.page.locator("#extension_mfaByPhoneOrEmail_email")
        mfa_needed = False
        for _ in range(60):  # up to ~30s (60 * 500ms)
            if _host_is_gateway(self.page.url):
                print(f"    [GEICO] Logged in without MFA -> {self.page.url}")
                return True
            try:
                if await mfa_radio.count() > 0 and await mfa_radio.first.is_visible():
                    mfa_needed = True
                    break
            except Exception:
                pass
            await self.page.wait_for_timeout(500)

        if not mfa_needed:
            # Neither gateway nor MFA selector within the window. One last
            # gateway check in case the redirect landed during the final tick.
            if _host_is_gateway(self.page.url):
                print(f"    [GEICO] Logged in without MFA -> {self.page.url}")
                return True
            print("    [GEICO] Neither gateway nor MFA selector appeared")
            await self.screenshot("login_no_mfa_no_gateway")
            return False

        # --- MFA path: click Email radio, then Continue. ---
        try:
            print("    [GEICO] MFA required — selecting Email method...")
            await mfa_radio.click(timeout=10_000)
            await self.page.get_by_role("button", name="Continue").click()
        except Exception as e:
            print(f"    [GEICO] MFA method selection failed: {e}")
            await self.screenshot("login_mfa_select_fail")
            return False

        # Transition to masked-email confirmation page.
        await self.page.wait_for_timeout(2_000)

        # Send verification code. Record login_time BEFORE click for OTP filter.
        try:
            print("    [GEICO] Requesting verification code...")
            send_btn = self.page.get_by_role("button", name="Send verification code")
            await send_btn.wait_for(state="visible", timeout=15_000)
            login_time = datetime.now(timezone.utc)
            await send_btn.click()
        except Exception as e:
            print(f"    [GEICO] Could not request verification code: {e}")
            await self.screenshot("login_send_code_fail")
            return False

        # Wait for the OTP textbox before polling Gmail.
        try:
            otp_box = self.page.get_by_role("textbox", name="Verification code")
            await otp_box.wait_for(state="visible", timeout=20_000)
        except Exception as e:
            print(f"    [GEICO] Verification code textbox never appeared: {e}")
            await self.screenshot("login_otp_box_missing")
            return False

        # Poll Gmail for the OTP.
        print("    [GEICO] Waiting for OTP email...")
        otp = self.otp_reader.fetch_otp(sent_after=login_time)
        if not otp:
            print("    [GEICO] OTP not received within timeout")
            await self.screenshot("login_otp_timeout")
            return False
        print(f"    [GEICO] OTP received: {otp[:2]}****")

        # Submit OTP.
        try:
            await otp_box.fill(otp)
            await self.page.get_by_role("button", name="Verify code").click()
            await self.page.wait_for_timeout(2_000)
        except Exception as e:
            print(f"    [GEICO] OTP submission failed: {e}")
            await self.screenshot("login_otp_submit_fail")
            return False

        # Final Continue button is now enabled after verification.
        try:
            print("    [GEICO] Finalizing login...")
            await self.page.get_by_role("button", name="Continue").click(timeout=15_000)
        except Exception as e:
            print(f"    [GEICO] Final Continue failed: {e}")
            await self.screenshot("login_final_continue_fail")
            return False

        # Wait for redirect to GEICO Gateway (host-checked, not substring).
        try:
            await self.page.wait_for_url(
                lambda url: _host_is_gateway(url), timeout=30_000
            )
            print(f"    [GEICO] Login successful -> {self.page.url}")
            return True
        except Exception as e:
            print(f"    [GEICO] Did not reach gateway: {e} (url={self.page.url})")
            await self.screenshot("login_no_gateway_redirect")
            return False
