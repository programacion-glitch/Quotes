"""ProductUnavailableError: GEICO withdrew Commercial Auto from the dashboard
(FMCSA banner, live 2026-06-11 night). It's a definitive HALT, not retryable.
"""

from __future__ import annotations

from modules.geico.client import _should_retry
from modules.geico.pages.dashboard_page import ProductUnavailableError
from modules.geico.quote_result_types import QuoteResult


def test_product_unavailable_is_runtime_error():
    assert issubclass(ProductUnavailableError, RuntimeError)


def test_product_halt_not_retried():
    result = QuoteResult(success=False, step_reached="dashboard",
                         halted=True, error="GEICO product HALT")
    assert _should_retry(result) is False
