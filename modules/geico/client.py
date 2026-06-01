"""
GEICO Client

Top-level API for the GEICO module. Manages browser lifecycle, retry logic,
and provides the create_quote() entry point used by workflow_orchestrator.

Mirrors modules/progressive/client.py — same shape so the orchestrator can
dispatch to either MGA with identical call semantics.
"""

import asyncio
import os
from dataclasses import dataclass
from typing import Optional

from modules.quote_profile import QuoteProfile
from modules.geico.otp_reader import GeicoOTPReader
from modules.geico.field_mapper import map_profile_to_fields
from modules.geico.quote_flow import QuoteFlow, QuoteResult


@dataclass
class GEICOConfig:
    """Configuration loaded from environment variables."""
    username: str
    password: str
    login_url: str
    otp_email: str
    otp_app_password: str
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
            login_url=os.getenv("GEICO_LOGIN_URL", ""),
            otp_email=os.getenv("GEICO_OTP_EMAIL", ""),
            otp_app_password=os.getenv("GEICO_OTP_APP_PASSWORD", ""),
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
        if not self.login_url:
            return "GEICO_LOGIN_URL not set"
        if not self.otp_email:
            return "GEICO_OTP_EMAIL not set"
        if not self.otp_app_password:
            return "GEICO_OTP_APP_PASSWORD not set"
        return None


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
            browser = await pw.chromium.launch(headless=config.headless)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36"
                ),
            )
            page = await context.new_page()

            otp_reader = GeicoOTPReader(
                config.otp_email, config.otp_app_password
            )
            flow = QuoteFlow(
                page=page,
                context=context,
                otp_reader=otp_reader,
                username=config.username,
                password=config.password,
                login_url=config.login_url,
                dry_run=config.dry_run,
            )

            last_result = await flow.run(fields)
            await browser.close()

            if last_result.success:
                return last_result
            # Stubs (Block N checkpoints during development) are NOT real
            # failures — retrying would burn another browser session for the
            # same expected outcome. Bail out immediately.
            if last_result.is_stub:
                return last_result
            # Eligibility halts are a definitive GEICO answer (USDOT/ZIP not
            # eligible). Retrying would hit the identical rejection. Bail.
            if last_result.halted:
                return last_result
            # Owner-verification failures (GEICO asked for SSN) are intermittent,
            # so we fall through and retry. After the loop exhausts, they are
            # promoted to a HALT below.

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
