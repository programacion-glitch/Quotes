"""GEICOConfig + retry policy (Fase 3: OTP Gmail API, sesión, contención).

- OTP via Gmail API: GEICO_OTP_APP_PASSWORD is no longer required (IMAP is
  dead on this host; the API reader authenticates with data/token.json).
- GEICO_LOGIN_URL defaults to the SP-initiated entry point and a captured
  authorize URL (code_challenge: PKCE verifier not reusable) is rejected.
- Retry only what a fresh attempt can change: login flakes and GEICO's
  intermittent owner-identity check. Mid-flow failures reproduce identically
  and just burn OTPs; halts/stubs are definitive.
"""

from __future__ import annotations

import pytest

from modules.geico.client import GEICOConfig, _SESSION_STATE, _should_retry
from modules.geico.quote_result_types import QuoteResult


@pytest.fixture
def clean_env(monkeypatch):
    for var in (
        "GEICO_USER", "GEICO_PASS", "GEICO_LOGIN_URL", "GEICO_OTP_EMAIL",
        "GEICO_OTP_APP_PASSWORD", "GEICO_DRY_RUN", "GEICO_HEADLESS",
        "GEICO_MAX_RETRIES",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GEICO_USER", "I070857")
    monkeypatch.setenv("GEICO_PASS", "secret")
    monkeypatch.setenv("GEICO_OTP_EMAIL", "quotes@h2oins.com")
    return monkeypatch


# ---------- config ----------

def test_login_url_defaults_to_gateway(clean_env):
    config = GEICOConfig.from_env()
    assert config.login_url == "https://gateway.geico.com"
    assert config.validate() is None


def test_captured_authorize_url_rejected(clean_env):
    clean_env.setenv(
        "GEICO_LOGIN_URL",
        "https://geicob2cprod.b2clogin.com/x/oauth2/v2.0/authorize?client_id=1"
        "&code_challenge=abc&code_challenge_method=S256",
    )
    config = GEICOConfig.from_env()
    error = config.validate()
    assert error is not None
    assert "code_challenge" in error


def test_otp_app_password_not_required(clean_env):
    # No GEICO_OTP_APP_PASSWORD in env: config must still validate.
    config = GEICOConfig.from_env()
    assert config.validate() is None


def test_missing_user_still_rejected(clean_env):
    clean_env.delenv("GEICO_USER")
    config = GEICOConfig.from_env()
    assert config.validate() == "GEICO_USER not set"


# ---------- session state ----------

def test_session_state_lives_in_data_dir():
    assert _SESSION_STATE.name == "geico_session.json"
    assert _SESSION_STATE.parent.name == "data"


# ---------- retry policy ----------

def test_retry_login_failure():
    result = QuoteResult(success=False, step_reached="login", error="OTP timeout")
    assert _should_retry(result) is True


def test_retry_hard_budget_blowup():
    # asyncio.wait_for timeout leaves step_reached empty — a wedge; a fresh
    # browser is the only plausible cure.
    result = QuoteResult(success=False, step_reached="", error="budget")
    assert _should_retry(result) is True


def test_retry_intermittent_owner_verification():
    result = QuoteResult(
        success=False, step_reached="business_owner",
        needs_manual_review=True, error="SSN requested",
    )
    assert _should_retry(result) is True


def test_no_retry_midflow_failure():
    result = QuoteResult(success=False, step_reached="vehicles", error="boom")
    assert _should_retry(result) is False


def test_no_retry_eligibility_halt():
    result = QuoteResult(
        success=False, step_reached="dashboard", halted=True,
        error="USDOT not eligible",
    )
    assert _should_retry(result) is False


def test_no_retry_success():
    result = QuoteResult(success=True, step_reached="final_details")
    assert _should_retry(result) is False


def test_no_retry_stub():
    result = QuoteResult(success=False, is_stub=True, step_reached="vehicles")
    assert _should_retry(result) is False
