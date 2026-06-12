"""Zombie-session recovery: a stale storage_state authenticates the host
but the dashboard widget never loads (live SOLANO 2026-06-11: landed on
gateway.geico.com/.../sessionexpireddashboard). The client must DROP the
session and retry with a fresh login instead of failing at 'dashboard'.
"""

from __future__ import annotations

from modules.geico.client import _should_retry
from modules.geico.pages.dashboard_page import SessionExpiredError
from modules.geico.quote_result_types import QuoteResult


def test_session_expired_is_a_runtime_error():
    assert issubclass(SessionExpiredError, RuntimeError)


def test_retry_on_session_expired_result():
    # quote_flow marks session_expired so the client knows to drop state.
    result = QuoteResult(success=False, step_reached="dashboard",
                         session_expired=True, error="session ended")
    assert _should_retry(result) is True


def test_no_retry_on_plain_dashboard_failure():
    result = QuoteResult(success=False, step_reached="dashboard",
                         error="some other dashboard error")
    assert _should_retry(result) is False
