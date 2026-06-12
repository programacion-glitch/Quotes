"""
GEICO Client

Top-level API for the GEICO module. Manages browser lifecycle, session
persistence, retry policy, and provides the create_quote() entry point used
by workflow_orchestrator.

Mirrors modules/progressive/client.py — same shape so the orchestrator can
dispatch to either MGA with identical call semantics. Containment lessons
inherited from Progressive (2026-06-10/11 live):
  * OTP over the Gmail REST API (HTTPS/443) — this host's mail-scanning
    stack (eScan/Acronis) resets IMAP TLS to Gmail, so imaplib never works.
  * Persistent storage_state: one login/OTP per batch, not per quote.
    GEICO enforces a SINGLE session per agent and Azure B2C throttles OTP —
    hammering fresh logins locks the account.
  * Bounded protocol calls + a hard per-attempt budget: a wedged renderer
    survives even bounded calls, so the whole attempt is wrapped in
    asyncio.wait_for.
  * Retry ONLY what a fresh attempt can plausibly change (login flakes,
    GEICO's intermittent owner-identity check). Mid-flow failures reproduce
    identically and just burn OTPs.
"""

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from modules.quote_profile import QuoteProfile
from modules.gmail_api_otp_reader import GmailAPIOTPReader
from modules.geico import stealth
from modules.geico.field_mapper import map_profile_to_fields
from modules.geico.quote_flow import QuoteFlow, QuoteResult


# SP-initiated entry point. NEVER a captured authorize URL: its PKCE
# code_challenge has the verifier in the browser that generated it, so
# reusing it breaks the token exchange ("Tu sesión ha terminado").
# Validated live 2026-05-28 — see docs/Proceso GEICO.md "Login + MFA".
_DEFAULT_LOGIN_URL = "https://gateway.geico.com"

# Cookies (incl. trusted-device state) persisted across runs so a batch of
# quotes does ONE login/OTP instead of one per quote. GEICO enforces a single
# session per agent (i070857): fresh logins invalidate the previous session
# and too many in a row can lock the account.
_SESSION_STATE = Path(__file__).resolve().parents[2] / "data" / "geico_session.json"

# Hard per-attempt budget. Provisional: copied from Progressive (largest
# legit quote there was 556s; 700 covers it with margin). Recalibrate once
# Fase 4 produces a GEICO end-to-end baseline.
_ATTEMPT_BUDGET_S = 700


@dataclass
class GEICOConfig:
    """Configuration loaded from environment variables."""
    username: str
    password: str
    login_url: str
    otp_email: str
    dry_run: bool = False
    headless: bool = True
    max_retries: int = 1

    @classmethod
    def from_env(cls) -> "GEICOConfig":
        """Load configuration from environment variables.

        Note on int parsing: ``os.getenv(key, default)`` returns the default
        ONLY when the key is missing. If the operator sets ``GEICO_MAX_RETRIES=``
        (empty string) in .env, the default is bypassed and ``int("")`` raises
        ValueError. We use the ``or "1"`` fallback to coerce empty → "1".
        """
        return cls(
            username=os.getenv("GEICO_USER", ""),
            password=os.getenv("GEICO_PASS", ""),
            login_url=os.getenv("GEICO_LOGIN_URL", "") or _DEFAULT_LOGIN_URL,
            otp_email=os.getenv("GEICO_OTP_EMAIL", ""),
            dry_run=os.getenv("GEICO_DRY_RUN", "false").lower()
            in ("true", "1", "yes"),
            headless=os.getenv("GEICO_HEADLESS", "true").lower()
            in ("true", "1", "yes"),
            max_retries=int(os.getenv("GEICO_MAX_RETRIES") or "1"),
        )

    def validate(self) -> Optional[str]:
        """Return error message if config is invalid, None if OK."""
        if not self.username:
            return "GEICO_USER not set"
        if not self.password:
            return "GEICO_PASS not set"
        if not self.otp_email:
            return "GEICO_OTP_EMAIL not set"
        if "code_challenge" in self.login_url:
            return (
                "GEICO_LOGIN_URL is a captured authorize URL (has "
                "code_challenge) — its PKCE verifier lives in the browser "
                "that generated it and the session always dies. Use "
                f"{_DEFAULT_LOGIN_URL} (or unset the variable)."
            )
        return None


def _should_retry(result: QuoteResult) -> bool:
    """Retry only failures a fresh attempt can plausibly change:

      * login flakes (OTP timing, redirect races) — step_reached == 'login';
      * a hard-budget blowup before any step registered (renderer wedge) —
        step_reached '' / None;
      * GEICO's intermittent owner-identity check (needs_manual_review):
        the same owner often verifies on a later attempt; after the retry
        loop exhausts, the caller promotes it to a HALT.

    Everything else either reproduces identically (mid-flow selector/logic
    failures) or is a definitive answer (halted, is_stub, success).
    """
    if result.success or result.halted or result.is_stub:
        return False
    if result.needs_manual_review or result.session_expired:
        return True
    return result.step_reached in ("login", "", None)


class GEICOClient:
    """
    Entry point for GEICO web automation.

    Usage:
        result = GEICOClient.create_quote(profile, effective_date="04/25/2026")
    """

    @staticmethod
    def create_quote(
        profile: QuoteProfile,
        effective_date: Optional[str] = None,
    ) -> QuoteResult:
        """
        Create a GEICO quote synchronously (wraps async internally).

        Args:
            profile: the QuoteProfile with applicant/commodity/vehicles/drivers data.
            effective_date: mm/dd/yyyy string for policy start. If None, GEICO's
                default (tomorrow) is accepted.

        Returns:
            QuoteResult with success/failure info. On success, .price holds the
            captured premium and .pdf_path the path to the saved quote PDF.
        """
        config = GEICOConfig.from_env()
        error = config.validate()
        if error:
            return QuoteResult(success=False, error=f"Config error: {error}")

        # Map profile to form fields
        fields = map_profile_to_fields(profile, effective_date=effective_date)

        # Halt early on missing critical fields
        missing = fields.missing_critical()
        if missing:
            return QuoteResult(
                success=False,
                error=f"Critical fields missing: {', '.join(missing)}",
                step_reached="field_mapping",
            )

        # Run async flow with retry
        return asyncio.run(_run_with_browser(config, fields))


async def _run_with_browser(config: GEICOConfig, fields) -> QuoteResult:
    """Launch browser and run the quote flow with retry logic."""
    from playwright.async_api import async_playwright

    last_result = QuoteResult()

    for attempt in range(1 + config.max_retries):
        if attempt > 0:
            print(f"    [GEICO] Retry {attempt}/{config.max_retries}...")

        async with async_playwright() as pw:
            # Anti-bot hardening (Imperva Incapsula): real Chrome fingerprint
            # + automation tells scrubbed. The TRUNCATED UA we used to send
            # got Incapsula to block step submits ('There was a problem while
            # processing...') while the MCP browser, with a full UA, passed
            # the identical flow (user-diagnosed 2026-06-11). 1920px wide so
            # the right-hand Dashboard drawer docks instead of floating over
            # the form.
            browser = await pw.chromium.launch(
                **stealth.launch_kwargs(headless=config.headless)
            )
            storage_state = (
                str(_SESSION_STATE) if _SESSION_STATE.exists() else None
            )
            context = await browser.new_context(
                **stealth.context_kwargs(storage_state=storage_state)
            )
            await stealth.apply_stealth(context)
            # Bound EVERY protocol call: a wedged renderer makes unbounded
            # calls hang the quote forever (Progressive live 2026-06-10).
            # Explicit per-call timeouts still override this default.
            context.set_default_timeout(30_000)
            page = await context.new_page()

            # OTP over the Gmail REST API (HTTPS/443). IMAP/993 is reset by
            # the host's mail-scanning security stack on this machine.
            otp_reader = GmailAPIOTPReader(config.otp_email, subject="GEICO")
            flow = QuoteFlow(
                page=page,
                context=context,
                otp_reader=otp_reader,
                username=config.username,
                password=config.password,
                login_url=config.login_url,
                dry_run=config.dry_run,
            )

            # Hard per-attempt budget: even bounded protocol calls keep a
            # wedged flow poking a dead page for ages without this.
            try:
                last_result = await asyncio.wait_for(
                    flow.run(fields), timeout=_ATTEMPT_BUDGET_S
                )
            except asyncio.TimeoutError:
                print(
                    f"    [GEICO] HARD BUDGET ({_ATTEMPT_BUDGET_S}s) exceeded "
                    f"— wedge suspected; aborting this attempt"
                )
                last_result = QuoteResult(
                    success=False,
                    error=(
                        f"Attempt exceeded {_ATTEMPT_BUDGET_S}s hard budget "
                        f"(renderer/page wedge suspected)"
                    ),
                    step_reached="",
                )

            # A dead reused session: drop the file so the retry logs in
            # fresh (and don't overwrite it with the zombie state below).
            if getattr(last_result, "session_expired", False):
                try:
                    if _SESSION_STATE.exists():
                        _SESSION_STATE.unlink()
                        print("    [GEICO] dropped expired session — retry will "
                              "log in fresh")
                except Exception as e:
                    print(f"    [GEICO] WARN: could not drop session: {e}")
            # Persist cookies whenever we got past LOGIN, so the next quote
            # reuses the authenticated session instead of burning an OTP.
            elif last_result.step_reached not in ("login", "", None):
                try:
                    await context.storage_state(path=str(_SESSION_STATE))
                except Exception as e:
                    print(f"    [GEICO] WARN: could not save session state: {e}")

            await browser.close()

            if last_result.success:
                return last_result
            if not _should_retry(last_result):
                if not last_result.halted and not last_result.is_stub:
                    print(
                        f"    [GEICO] Failure at step "
                        f"'{last_result.step_reached}' is not retryable; "
                        f"returning original error."
                    )
                return last_result

    # Retries exhausted. If the last failure was GEICO repeatedly asking for the
    # owner's SSN, promote it to a HALT so the caller treats it as a definitive
    # "needs manual intervention" outcome rather than a generic error. The SSN
    # is never auto-filled (sensitive data).
    if last_result.needs_manual_review and not last_result.success:
        last_result.halted = True
        last_result.error = (
            f"GEICO repeatedly could not verify the owner and requested the "
            f"SSN across {1 + config.max_retries} attempt(s). Manual entry of "
            f"the Business Owner SSN is required to proceed. Original detail: "
            f"{last_result.error}"
        )

    return last_result
