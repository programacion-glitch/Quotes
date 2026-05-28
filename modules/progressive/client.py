"""
Progressive Client

Top-level API for the Progressive module. Manages browser lifecycle,
retry logic, and provides the create_quote() entry point used by
workflow_orchestrator.
"""

import asyncio
import os
from dataclasses import dataclass
from typing import Optional

from modules.quote_profile import QuoteProfile
from modules.progressive.otp_reader import GmailOTPReader
from modules.progressive.field_mapper import map_profile_to_fields
from modules.progressive.quote_flow import QuoteFlow, QuoteResult


@dataclass
class ProgressiveConfig:
    """Configuration loaded from environment variables."""
    username: str
    password: str
    otp_email: str
    otp_app_password: str
    dry_run: bool = False
    headless: bool = True
    max_retries: int = 1

    @classmethod
    def from_env(cls) -> "ProgressiveConfig":
        """Load configuration from environment variables."""
        return cls(
            username=os.getenv("PROGRESSIVE_USER", ""),
            password=os.getenv("PROGRESSIVE_PASS", ""),
            otp_email=os.getenv("PROGRESSIVE_OTP_EMAIL", ""),
            otp_app_password=os.getenv("PROGRESSIVE_OTP_APP_PASSWORD", ""),
            dry_run=os.getenv("PROGRESSIVE_DRY_RUN", "false").lower()
            in ("true", "1", "yes"),
            headless=os.getenv("PROGRESSIVE_HEADLESS", "true").lower()
            in ("true", "1", "yes"),
            max_retries=int(os.getenv("PROGRESSIVE_MAX_RETRIES", "1")),
        )

    def validate(self) -> Optional[str]:
        """Return error message if config is invalid, None if OK."""
        if not self.username:
            return "PROGRESSIVE_USER not set"
        if not self.password:
            return "PROGRESSIVE_PASS not set"
        if not self.otp_email:
            return "PROGRESSIVE_OTP_EMAIL not set"
        if not self.otp_app_password:
            return "PROGRESSIVE_OTP_APP_PASSWORD not set"
        return None


class ProgressiveClient:
    """
    Entry point for Progressive web automation.

    Usage:
        result = ProgressiveClient.create_quote(profile, effective_date="04/25/2026")
    """

    @staticmethod
    def create_quote(
        profile: QuoteProfile,
        effective_date: Optional[str] = None,
    ) -> QuoteResult:
        """
        Create a Progressive quote synchronously (wraps async internally).

        Args:
            profile: the QuoteProfile with applicant/commodity data.
            effective_date: mm/dd/yyyy string for policy start.

        Returns:
            QuoteResult with success/failure info.
        """
        config = ProgressiveConfig.from_env()
        error = config.validate()
        if error:
            return QuoteResult(success=False, error=f"Config error: {error}")

        # Map profile to form fields
        fields = map_profile_to_fields(profile, effective_date=effective_date)

        # Check critical fields
        missing = fields.missing_critical()
        if missing:
            return QuoteResult(
                success=False,
                error=f"Critical fields missing: {', '.join(missing)}",
                step_reached="field_mapping",
            )

        # Run async flow
        return asyncio.run(_run_with_browser(config, fields))


async def _run_with_browser(config: ProgressiveConfig, fields) -> QuoteResult:
    """Launch browser and run the quote flow with retry logic."""
    from playwright.async_api import async_playwright

    last_result = QuoteResult()

    for attempt in range(1 + config.max_retries):
        if attempt > 0:
            print(f"    [Progressive] Retry {attempt}/{config.max_retries}...")

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

            otp_reader = GmailOTPReader(
                config.otp_email, config.otp_app_password
            )
            flow = QuoteFlow(
                page=page,
                context=context,
                otp_reader=otp_reader,
                username=config.username,
                password=config.password,
                dry_run=config.dry_run,
            )

            last_result = await flow.run(fields)
            await browser.close()

            if last_result.success:
                return last_result

    return last_result
