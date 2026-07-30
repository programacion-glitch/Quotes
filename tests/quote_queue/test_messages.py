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


class TestDecisionsTable:
    def _outcome(self, decisions, reason="ok"):
        return RpaQuoteOutcome(mga="PROGRESSIVE", status="quoted",
                               reason=reason, premium="$1,000",
                               decisions=decisions)

    def test_quoted_muestra_decisiones(self):
        html = render_rpa_section([self._outcome([
            {"field": "Roadside Assistance", "chosen": "Selected w/ $250 Deductible",
             "source": "RULE", "rule_id": "R-001", "page": "Coverages/RATES"},
        ])])
        assert "Decisiones tomadas" in html
        assert "Roadside Assistance" in html
        assert "R-001" in html

    def test_dudosas_van_primero_con_warning(self):
        html = render_rpa_section([self._outcome([
            {"field": "Con-Regla", "chosen": "A", "source": "RULE", "rule_id": "R-001"},
            {"field": "Sin-Regla", "chosen": "B", "source": "DEFAULTED", "rule_id": None},
        ])])
        assert html.index("Sin-Regla") < html.index("Con-Regla")
        assert "&#9888;" in html  # ⚠ en la dudosa

    def test_matched_no_es_dudosa(self):
        """MATCHED = dato del BlueQuote mapeado — no lleva warning."""
        html = render_rpa_section([self._outcome([
            {"field": "Body Type", "chosen": "Dump Truck", "source": "MATCHED",
             "rule_id": None},
        ])])
        assert "&#9888;" not in html

    def test_default_con_rule_id_si_es_dudosa(self):
        """Los defaults técnicos EN-DUDA citan su rule_id (R-0XX) pero NO
        están validados por negocio — deben seguir marcándose con ⚠."""
        html = render_rpa_section([self._outcome([
            {"field": "License state del driver", "chosen": "Texas",
             "source": "DEFAULT", "rule_id": "R-052"},
        ])])
        assert "&#9888;" in html

    def test_rule_con_rule_id_no_es_dudosa(self):
        """source=RULE con rule_id = regla de negocio validada — sin warning."""
        html = render_rpa_section([self._outcome([
            {"field": "Marital Status", "chosen": "Single", "source": "RULE",
             "rule_id": "R-001"},
        ])])
        assert "&#9888;" not in html

    def test_no_quoted_sin_tabla(self):
        out = RpaQuoteOutcome(mga="GEICO", status="halted", reason="not_eligible",
                              decisions=[{"field": "X", "chosen": "Y",
                                          "source": "DEFAULTED", "rule_id": None}])
        html = render_rpa_section([out])
        assert "Decisiones tomadas" not in html

    def test_decisions_none_no_rompe(self):
        html = render_rpa_section([self._outcome(None)])
        assert "PROGRESSIVE" in html
        assert "Decisiones tomadas" not in html
