from modules.quote_profile import QuoteProfile
from modules.analysis_email_builder import build_analysis_email


def _email(**kw):
    return build_analysis_email(
        profile=QuoteProfile(),
        commodity="N/A",
        tipo_negocio="N/A",
        evaluations=[],
        mga_list=[],
        original_subject="Submission // TEST",
        **kw,
    )


def test_default_has_no_rpa_section():
    out = _email()
    assert "<!--RPA_QUOTES_SECTION-->" not in out["body"]


def test_passed_rpa_section_is_embedded():
    out = _email(rpa_quotes_section="<!--RPA_QUOTES_SECTION-->")
    assert "<!--RPA_QUOTES_SECTION-->" in out["body"]


def test_passed_html_block_is_embedded():
    out = _email(rpa_quotes_section="<tr><td>HOLA_RPA</td></tr>")
    assert "HOLA_RPA" in out["body"]
