from modules.quote_queue.messages import (
    RpaQuoteOutcome, RPA_SECTION_MARKER, humanize, render_rpa_section,
)


def test_quoted_with_pdf_shows_premium():
    msg = humanize(RpaQuoteOutcome(mga="PROGRESSIVE", status="quoted",
                                   reason="ok", premium="$44,621", pdf_path="x.pdf"))
    assert "PROGRESSIVE" in msg and "$44,621" in msg


def test_quoted_without_pdf_notes_missing_print():
    msg = humanize(RpaQuoteOutcome(mga="GEICO", status="quoted",
                                   reason="ok_no_pdf", premium="$15,512"))
    assert "$15,512" in msg
    assert "impresión" in msg.lower()


def test_needs_ssn_is_actionable_and_not_technical():
    msg = humanize(RpaQuoteOutcome(mga="GEICO", status="halted", reason="needs_ssn"))
    assert "SSN" in msg
    assert "needs_manual_review" not in msg
    assert "Traceback" not in msg


def test_not_eligible_message():
    msg = humanize(RpaQuoteOutcome(mga="PROGRESSIVE", status="halted", reason="not_eligible"))
    assert "elegibilidad" in msg.lower()


def test_pending_retry_message():
    msg = humanize(RpaQuoteOutcome(mga="GEICO", status="deferred", reason="pending_retry"))
    assert "pendiente" in msg.lower()


def test_failed_message_is_clean():
    msg = humanize(RpaQuoteOutcome(mga="PROGRESSIVE", status="failed",
                                   reason="error", detail="KeyError at line 99"))
    assert "manualmente" in msg.lower()
    assert "KeyError" not in msg


def test_render_section_contains_marker_text_and_each_outcome():
    html = render_rpa_section([
        RpaQuoteOutcome(mga="PROGRESSIVE", status="quoted", reason="ok",
                        premium="$44,621", pdf_path="x.pdf"),
        RpaQuoteOutcome(mga="GEICO", status="halted", reason="needs_ssn"),
    ])
    assert "PROGRESSIVE" in html and "$44,621" in html
    assert "GEICO" in html and "SSN" in html


def test_marker_is_html_comment():
    assert RPA_SECTION_MARKER.startswith("<!--") and RPA_SECTION_MARKER.endswith("-->")
