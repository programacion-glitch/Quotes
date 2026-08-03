"""Correcciones de Diana 2026-08-03 (PANTHER) al correo de análisis:

C3: un MGA con varios paths (filas del Excel) no puede salir en elegibles Y
    no elegibles a la vez (Great West).
C2: las notas por compañía van completas como comentario en cada fila.
C1/pt.9: los desbloqueables (falta app NV / cuestionario) van a la sección
    de desbloqueo con sus requisitos.
"""
from modules.analysis_email_builder import build_analysis_email
from modules.rule_engine import MGAEvaluation, FailedRule
from modules.quote_profile import QuoteProfile


def _profile():
    p = QuoteProfile()
    p.applicant.business_name = "PANTHER EXPRESS TRUCKING LLC"
    p.applicant.usdot = "4514637"
    p.documents_present = ["CDL"]
    return p


def _build(evaluations, mga_list):
    return build_analysis_email(
        profile=_profile(), commodity="PIPES", tipo_negocio="DRY VAN / REEFER",
        evaluations=evaluations, mga_list=mga_list,
        original_subject="Submission New Venture // PANTHER",
    )


def test_mga_con_dos_paths_sale_una_sola_vez():
    """Great West: path NV elegible + path establecidos no elegible ->
    una sola aparición, como elegible."""
    nv_path = MGAEvaluation(mga_name="GREAT WEST", eligible=True,
                            passed_rules=["IS_NEW_VENTURE"])
    est_path = MGAEvaluation(
        mga_name="GREAT WEST", eligible=False,
        failed_rules=[FailedRule(
            "IS_NEW_VENTURE",
            "Requiere minimo 2 ano(s) en el negocio, este es New Venture")],
    )
    out = _build([nv_path, est_path], [{"mga": "GREAT WEST"}])
    body = out["body"]
    assert body.count("GREAT WEST") == 1
    assert "Requiere minimo 2 ano(s)" not in body


def test_mga_sin_path_elegible_muestra_el_mas_cercano():
    """Si ningún path pasa, se muestra una vez con el path de menos fallas."""
    peor = MGAEvaluation(
        mga_name="GREAT WEST", eligible=False,
        failed_rules=[FailedRule("A", "Requiere minimo 2 ano(s) en el negocio"),
                      FailedRule("B", "Requiere minimo de unidades")],
    )
    mejor = MGAEvaluation(
        mga_name="GREAT WEST", eligible=False,
        failed_rules=[FailedRule("A", "Requiere minimo 2 ano(s) en el negocio")],
    )
    out = _build([peor, mejor], [{"mga": "GREAT WEST"}])
    body = out["body"]
    assert body.count("GREAT WEST") == 1
    assert "Requiere minimo de unidades" not in body


def test_notas_completas_en_fila_no_elegible():
    """Diana: 'las notas que puse en cada compañía es requisito que estén
    como comentario' — completas, sin truncar a 100 chars."""
    nota = ("Para new venture es necesario cotizar las 3 coberturas, único "
            "driver en la póliza con su camión + trailer y solo Dry van, "
            "flatbed o reefer; cualquier otro tipo de operación exige 2 años.")
    assert len(nota) > 100
    ev = MGAEvaluation(
        mga_name="GREAT WEST", eligible=False,
        failed_rules=[FailedRule("MIN_BUSINESS_YEARS", "Requiere minimo 2 ano(s)")],
        informational={"notas_extra": nota},
    )
    out = _build([ev], [{"mga": "GREAT WEST"}])
    assert nota in out["body"]


def test_notas_completas_en_fila_elegible():
    nota = "N" * 150 + " FIN"
    ev = MGAEvaluation(mga_name="ROCKLAKE", eligible=True,
                       informational={"notas_extra": nota})
    out = _build([ev], [{"mga": "ROCKLAKE"}])
    assert nota in out["body"]


def test_cuestionario_pendiente_es_desbloqueable():
    """Paramount/Novatae fallan por app+cuestionario -> sección de desbloqueo
    (no la lista roja), con sus requisitos (notas del Excel)."""
    nota = "Camiones máx. 15 años. Requiere formulario + preguntas + excel."
    ev = MGAEvaluation(
        mga_name="PARAMOUNT", eligible=False,
        failed_rules=[
            FailedRule("REQUIRES_APP", "Falta documento: APP"),
            FailedRule("REQUIRES_QUESTIONS",
                       "Faltan: respuestas del cuestionario (preguntas de appointments)"),
        ],
        informational={"notas_extra": nota},
    )
    out = _build([ev], [{"mga": "PARAMOUNT"}])
    body = out["body"]
    assert "Desbloquea: PARAMOUNT" in body
    assert "Requisitos por MGA" in body
    assert nota in body


def test_app_nv_desbloquea_xpt_y_county_hall():
    """REQUIRES_APP_NV ('Falta documento: APP (new venture)') agrupa a
    XPT y County Hall en la sección de desbloqueo (Diana pt. XPT/CH)."""
    fr = FailedRule("REQUIRES_APP_NV", "Falta documento: APP (new venture)")
    evs = [
        MGAEvaluation(mga_name="XPT", eligible=False, failed_rules=[fr]),
        MGAEvaluation(mga_name="COUNTY HALL", eligible=False, failed_rules=[fr]),
    ]
    out = _build(evs, [{"mga": "XPT"}, {"mga": "COUNTY HALL"}])
    body = out["body"]
    assert "APP (new venture)" in body
    assert "XPT, COUNTY HALL" in body or "COUNTY HALL, XPT" in body
