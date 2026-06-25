from types import SimpleNamespace

from modules.quote_queue.worker import classify_result


def _price(premium=None, quote_number=None):
    return SimpleNamespace(annual_premium=premium, quote_number=quote_number)


def test_success_with_pdf_is_quoted_ok():
    r = SimpleNamespace(success=True, price=_price("$44,621", "CA1"), pdf_path="x.pdf", error=None)
    status, reason, premium, quote_number, pdf_path = classify_result(r)
    assert (status, reason) == ("quoted", "ok")
    assert premium == "$44,621" and quote_number == "CA1" and pdf_path == "x.pdf"


def test_success_without_pdf_is_quoted_no_pdf():
    r = SimpleNamespace(success=True, price=_price("$15,512"), pdf_path=None, error=None)
    status, reason, *_ = classify_result(r)
    assert (status, reason) == ("quoted", "ok_no_pdf")


def test_needs_manual_review_is_needs_ssn():
    r = SimpleNamespace(success=False, needs_manual_review=True, error="owner SSN required")
    status, reason, *_ = classify_result(r)
    assert (status, reason) == ("halted", "needs_ssn")


def test_halted_is_not_eligible():
    r = SimpleNamespace(success=False, halted=True, error="FMCSA reject")
    status, reason, *_ = classify_result(r)
    assert (status, reason) == ("halted", "not_eligible")


def test_session_expired_is_deferred():
    r = SimpleNamespace(success=False, session_expired=True, error="zombie session")
    status, reason, *_ = classify_result(r)
    assert (status, reason) == ("deferred", "pending_retry")


def test_progressive_ssn_via_error_text():
    r = SimpleNamespace(success=False, error="HALT: Progressive pide SSN del driver")
    status, reason, *_ = classify_result(r)
    assert (status, reason) == ("halted", "needs_ssn")


def test_progressive_decline_is_not_eligible():
    # Mensaje real de _check_declined (live ALMA FORCE 2026-06-25): un decline
    # de underwriting de Progressive debe clasificar como halted/not_eligible,
    # NO como 'failed' (no es un bug, el riesgo no es cotizable).
    r = SimpleNamespace(
        success=False,
        error=(
            "Progressive DECLINED this risk: 'We are Unable to Provide a Quote "
            "For This Risk'. This is a carrier underwriting decline, not a bot "
            "error. Reason: ... does not meet Progressive's acceptability criteria."
        ),
    )
    status, reason, *_ = classify_result(r)
    assert (status, reason) == ("halted", "not_eligible")


def test_unknown_failure_is_error():
    r = SimpleNamespace(success=False, error="boom at line 42")
    status, reason, *_ = classify_result(r)
    assert (status, reason) == ("failed", "error")
