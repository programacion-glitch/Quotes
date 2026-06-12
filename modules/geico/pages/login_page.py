"""
Login Page Object for GEICO portal (Azure B2C).

Flow (very different from Progressive's ForAgentsOnly):
  1. Navigate to GEICO_LOGIN_URL (long Azure B2C URL with PKCE params).
  2. Fill Username + Password, click "Sign in".
  3. Azure redirects through "Loading..." then a "User details" MFA selector.
  4. Pick the Email radio (custom radio whose real input is `#extension_mfaByPhoneOrEmail_email`).
  5. Click Continue. Page shows masked email + "Send verification code" button.
  6. Click "Send verification code" (record login_time first, for OTP filter).
  7. Wait for "Verification code" textbox, fetch OTP via the Gmail API
     reader (HTTPS/443 — IMAP is reset by this host's mail-scanning stack),
     fill, click "Verify code".
  8. Click "Continue" -> redirect to gateway.geico.com/quote.
"""

from datetime import datetime, timezone
from urllib.parse import urlparse

from playwright.async_api import Page

from modules.geico.pages.base_page import BasePage
from modules.gmail_api_otp_reader import GmailAPIOTPReader


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


def _is_live_gateway(url: str) -> bool:
    """Authenticated AND alive: gateway host, but NOT the session-expired
    page. GEICO enforces a single session per agent — when another browser
    takes it, the gateway serves /sessionexpireddashboard with no login
    form, which fooled the host-only check (live 2026-06-11)."""
    return _host_is_gateway(url) and "sessionexpired" not in url.lower()


def _is_authenticated_gateway(url: str) -> bool:
    """A POSITIVELY-authenticated gateway page: live gateway host AND a real
    app path (e.g. /Dashboard, /quote) — NOT the bare root.

    Why the path matters: a fresh (cookieless) navigation to the login entry
    point momentarily sits at `https://gateway.geico.com/` BEFORE bouncing to
    the b2clogin sign-in form. The bare root is therefore ambiguous and must
    NOT be read as authenticated (live 2026-06-12: doing so won a race against
    the bounce and skipped credential entry, landing on 'Sign up or sign in'
    at /quote — 'widget never visible'). An authenticated session always
    resolves to an app path like /Dashboard."""
    if not _is_live_gateway(url):
        return False
    try:
        path = (urlparse(url).path or "").strip("/")
    except Exception:
        return False
    return path != ""


def _classify_landing(
    url: str, username_visible: bool, auth_marker_visible: bool = False
) -> str:
    """Classify the page we just landed/navigated to. Pure decision so the
    control flow can RE-CHECK after every navigation instead of assuming a
    login form is present (live 2026-06-12: a re-login navigation actually
    loaded the authenticated dashboard, but the old code waited for Username
    anyway and timed out 156s/quote).

    Returns:
      'login_form'      — the Username box is visible: we are NOT logged in
                          (the b2c sign-in page), enter credentials.
      'authenticated'   — a live gateway APP page (path or dashboard marker):
                          we're in, skip credentials.
      'session_expired' — gateway served a sessionexpired page, no form yet:
                          re-navigate to /dashboard to revive the session.
      'unknown'         — none of the above (still bouncing / loading — keep
                          polling; this covers the transient bare gateway root).

    The Username form WINS: an authenticated dashboard never renders it, so
    its presence means we're on the sign-in page no matter the URL. A bare
    gateway root with neither form nor marker stays 'unknown' so the poller
    waits for the bounce to resolve instead of guessing 'authenticated'."""
    if username_visible:
        return "login_form"
    if _is_authenticated_gateway(url):
        return "authenticated"
    if auth_marker_visible and _is_live_gateway(url):
        # Bare gateway root but the logged-in dashboard chrome is on screen
        # ('Welcome to your dashboard' / Commercial Auto widget): authenticated.
        return "authenticated"
    if "sessionexpired" in (url or "").lower():
        return "session_expired"
    return "unknown"


class LoginPage(BasePage):
    """GEICO Azure B2C login + email-MFA flow."""

    GATEWAY_HOST = "gateway.geico.com"

    def __init__(self, page: Page, otp_reader: GmailAPIOTPReader, login_url: str):
        super().__init__(page)
        self.otp_reader = otp_reader
        self.login_url = login_url

    async def _resolve_landing(
        self, *, timeout_ms: int = 30_000, expired_grace_ms: int = 3_000
    ) -> str:
        """Poll the current page until it resolves to a terminal landing:
        'authenticated' (live gateway) or 'login_form' (Username visible).

        Returns the first of those two seen. A sessionexpired page is a
        DEAD END (it never becomes a form on its own), so once we've seen it
        persistently for `expired_grace_ms` with no form, return early as
        'session_expired' instead of burning the full timeout — the grace
        tolerates a transient sessionexpired URL flashing mid-bounce. If
        nothing resolves before the deadline, returns the best fallback seen
        ('session_expired' or 'unknown'). No blind sleeps."""
        import asyncio
        now = asyncio.get_event_loop().time()
        deadline = now + timeout_ms / 1000
        username_box = self.page.get_by_role("textbox", name="Username")
        # Logged-in dashboard chrome — lets us accept an authenticated bare
        # gateway root (no app path yet) without a false positive.
        auth_marker = self.page.locator(
            "#labelForCommercialAuto, "
            "text=Welcome to your dashboard"
        )
        fallback = "unknown"
        expired_since = None  # time we first saw a sustained sessionexpired
        while asyncio.get_event_loop().time() < deadline:
            url = self.page.url
            username_visible = False
            try:
                if await username_box.count() > 0:
                    username_visible = await username_box.first.is_visible()
            except Exception:
                username_visible = False
            auth_marker_visible = False
            if not username_visible:
                try:
                    if await auth_marker.count() > 0:
                        auth_marker_visible = await auth_marker.first.is_visible()
                except Exception:
                    auth_marker_visible = False
            state = _classify_landing(url, username_visible, auth_marker_visible)
            if state in ("authenticated", "login_form"):
                return state
            if state == "session_expired":
                fallback = "session_expired"
                t = asyncio.get_event_loop().time()
                if expired_since is None:
                    expired_since = t
                elif (t - expired_since) * 1000 >= expired_grace_ms:
                    return "session_expired"
            else:
                expired_since = None  # still bouncing/loading — reset grace
            await self.page.wait_for_timeout(500)
        return fallback

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
            print("    [GEICO] Resolving the landing page...")
            username_box = self.page.get_by_role("textbox", name="Username")
            state = await self._resolve_landing(timeout_ms=30_000)

            if state == "session_expired":
                # Reused cookies hit a sessionexpired page with no form. A
                # re-navigation to /dashboard often REVIVES the authenticated
                # session (live 2026-06-12: the dashboard loaded fully logged
                # in). So re-resolve and accept a live gateway BEFORE demanding
                # credentials — the old code waited for Username here and burned
                # 156s/quote timing out on a page where we were already in.
                print("    [GEICO] Session expired URL — re-navigating to /dashboard...")
                try:
                    await self.page.goto(
                        "https://gateway.geico.com/dashboard",
                        wait_until="networkidle",
                        timeout=45_000,
                    )
                except Exception:
                    pass
                state = await self._resolve_landing(timeout_ms=30_000)

            if state == "authenticated":
                print(f"    [GEICO] Already authenticated -> {self.page.url}")
                return True

            if state != "login_form":
                # Neither authenticated nor a usable sign-in form within the
                # budget — a genuine failure (caught below -> screenshot).
                raise RuntimeError(
                    f"Login landing did not resolve (state={state}, "
                    f"url={self.page.url})"
                )

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
            if _is_live_gateway(self.page.url):
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
            if _is_live_gateway(self.page.url):
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
                lambda url: _is_live_gateway(url), timeout=30_000
            )
            print(f"    [GEICO] Login successful -> {self.page.url}")
            return True
        except Exception as e:
            print(f"    [GEICO] Did not reach gateway: {e} (url={self.page.url})")
            await self.screenshot("login_no_gateway_redirect")
            return False
