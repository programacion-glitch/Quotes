"""La sección 'por qué' del rule engine en el correo de análisis."""
from modules.analysis_email_builder import build_analysis_email
from modules.rule_engine import MGAEvaluation, FailedRule
from modules.quote_profile import QuoteProfile


def _profile():
    p = QuoteProfile()
    p.applicant.business_name = "ACME LLC"
    p.applicant.usdot = "123456"
    # NOTE: CDL is added so the baseline-missing-docs safety net
    # (_apply_baseline_to_eligible in analysis_email_builder.py) does not
    # downgrade an eligible non-web MGA to ineligible in these tests — that
    # safety net is orthogonal to what's being tested here (rendering of
    # passed_rules / failed_rules detail). is_new_venture stays True
    # (dataclass default) so MVR/Loss Run remain not-required.
    p.documents_present = ["CDL"]
    return p


def _build(evaluations, mga_list):
    return build_analysis_email(
        profile=_profile(), commodity="SAND", tipo_negocio="DUMP",
        evaluations=evaluations, mga_list=mga_list,
        original_subject="Submission - ACME",
    )


def test_ineligible_muestra_actual_vs_requerido():
    ev = MGAEvaluation(
        mga_name="COVERWHALE", eligible=False,
        failed_rules=[FailedRule("MIN_UNITS", "Requiere minimo de unidades",
                                 current_value=1, required_value=2)],
    )
    out = _build([ev], [{"mga": "COVERWHALE"}])
    assert "actual: 1" in out["body"]
    assert "requerido: 2" in out["body"]


def test_eligible_muestra_reglas_ok():
    ev = MGAEvaluation(mga_name="COVERWHALE", eligible=True,
                       passed_rules=["MIN_UNITS", "MIN_CDL_YEARS"])
    out = _build([ev], [{"mga": "COVERWHALE"}])
    assert "MIN_UNITS" in out["body"]
    assert "MIN_CDL_YEARS" in out["body"]


def test_mga_web_ineligible_aparece_en_bloque_web_con_razon():
    """Progressive no elegible por reglas: Diana debe ver POR QUE no se
    intento la cotizacion automatica (hoy se filtra y desaparece)."""
    ev = MGAEvaluation(
        mga_name="PROGRESSIVE", eligible=False,
        failed_rules=[FailedRule("MIN_UNITS", "Requiere minimo de unidades",
                                 current_value=1, required_value=2)],
    )
    out = _build([ev], [{"mga": "PROGRESSIVE"}])
    body = out["body"]
    assert "PROGRESSIVE" in body
    assert "Requiere minimo de unidades" in body
    # y NO en la lista roja general (siguen excluidos de ahi):
    assert "no se intent" in body.lower()  # "no se intentó cotización automática"


def test_mga_web_eligible_referencia_seccion_rpa():
    ev = MGAEvaluation(mga_name="PROGRESSIVE", eligible=True,
                       passed_rules=["MIN_UNITS"])
    out = _build([ev], [{"mga": "PROGRESSIVE"}])
    assert "Elegible por reglas" in out["body"]


def test_valores_lista_no_muestran_repr_de_python():
    """ALLOWED_COVERAGES / ALLOWED_TRAILER_TYPES ponen listas en
    current_value/required_value (ver rule_engine.py). El correo es para
    Diana (negocio, no tecnica) — no debe mostrar '['AL', 'MTC']'."""
    ev = MGAEvaluation(
        mga_name="COVERWHALE", eligible=False,
        failed_rules=[FailedRule("ALLOWED_COVERAGES", "Cobertura no aceptada",
                                 current_value=["AL", "MTC"], required_value=["AL"])],
    )
    out = _build([ev], [{"mga": "COVERWHALE"}])
    body = out["body"]
    assert "AL, MTC" in body
    assert "['" not in body
