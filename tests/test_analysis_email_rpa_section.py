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


def _section(body: str, start_marker: str, end_marker: str) -> str:
    """Slice the HTML comment-delimited section for isolated assertions."""
    start = body.index(start_marker) + len(start_marker)
    end = body.index(end_marker, start)
    return body[start:end]


def test_web_automation_mgas_excluded_from_rule_sections():
    """Diana 2026-06-25: Progressive/GEICO NO se categorizan por reglas — su
    veredicto (cotizó/declinó) lo da el RPA. Aunque el rule engine los marque
    elegibles, NO deben aparecer en las listas elegibles/no-elegibles generales
    (si no, un MGA declinado en vivo saldría como 'disponible').

    2026-07-29: Task 4 agrega un bloque nuevo "MGAs Web — Evaluacion de
    Reglas" donde Progressive/GEICO SÍ aparecen (para explicar el filtro
    previo del rule engine) — pero solo ahí, no en las secciones generales
    de Elegibles/No Elegibles."""
    profile = QuoteProfile()
    # CDL presente para que AMWINS (MGA por email) no sea degradado a
    # "falta documento" por el safety net de baseline docs — de lo
    # contrario cae en la sección de fixes en vez de en Elegibles, lo
    # cual es ortogonal a lo que prueba este caso.
    profile.documents_present = ["CDL"]
    out = build_analysis_email(
        profile=profile,
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

    web_section = _section(
        body,
        "<!-- ====== WEB MGAs (rule engine) ====== -->",
        "<!-- ====== ELIGIBLE MGAs ====== -->",
    )
    eligible_section = _section(
        body,
        "<!-- ====== ELIGIBLE MGAs ====== -->",
        "<!-- ====== INELIGIBLE MGAs ====== -->",
    )
    ineligible_section = _section(
        body,
        "<!-- ====== INELIGIBLE MGAs ====== -->",
        "<!-- ====== WHAT'S NEEDED ====== -->",
    )

    assert "GEICO" in web_section, "GEICO debe explicarse en el bloque MGAs Web"
    assert "PROGRESSIVE" in web_section, "PROGRESSIVE debe explicarse en el bloque MGAs Web"

    assert "GEICO" not in eligible_section, "GEICO no debe salir en la lista general de elegibles"
    assert "PROGRESSIVE" not in eligible_section, "PROGRESSIVE no debe salir en la lista general de elegibles"
    assert "GEICO" not in ineligible_section, "GEICO no debe salir en la lista general de no-elegibles"
    assert "PROGRESSIVE" not in ineligible_section, "PROGRESSIVE no debe salir en la lista general de no-elegibles"

    assert "AMWINS" in eligible_section, "un MGA por email sí debe aparecer en Elegibles"
    assert "AMWINS" not in web_section, "un MGA por email no debe aparecer en el bloque MGAs Web"
