from modules.quote_profile import QuoteProfile
from modules.analysis_email_builder import build_analysis_email
from modules.rule_engine import MGAEvaluation


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


def test_web_automation_mgas_excluded_from_rule_sections():
    """Diana 2026-06-25: Progressive/GEICO NO se categorizan por reglas — su
    veredicto (cotizó/declinó) lo da el RPA. Aunque el rule engine los marque
    elegibles, NO deben aparecer en las listas elegibles/no-elegibles (si no,
    un MGA declinado en vivo saldría como 'disponible')."""
    out = build_analysis_email(
        profile=QuoteProfile(),
        commodity="DIRT, SAND & GRAVEL",
        tipo_negocio="DIRT, SAND & GRAVEL",
        evaluations=[
            MGAEvaluation(mga_name="GEICO", eligible=True),
            MGAEvaluation(mga_name="PROGRESSIVE", eligible=True),
            MGAEvaluation(mga_name="AMWINS", eligible=True),
        ],
        mga_list=[],
        original_subject="Submission // TEST",
    )
    body = out["body"]
    assert "GEICO" not in body, "GEICO no debe salir en las secciones de reglas"
    assert "PROGRESSIVE" not in body, "PROGRESSIVE no debe salir en las secciones de reglas"
    assert "AMWINS" in body, "un MGA por email sí debe aparecer"
