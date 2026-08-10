"""Un segundo limite de AL pedido no se puede perder en silencio.

T&S Logistics (2026-08-06): el agente mando DOS Blue Quotes —
'20260805 BLUE QUOTE.pdf' ($1M CSL) y '20260805 BLUE QUOTE 750K AL.pdf'
($750K CSL)— y el cuerpo del correo decia en mayusculas "POR FAVOR SOLICITAR
UNA QUOTE DE $750,000 TAMBIEN". El clasificador se quedo con la primera
("Skipped (duplicate BLUE QUOTE)") y el $750K desaparecio.

Diana: *"veo que en la blue quote y tanto en el cuerpo del correo nos menciona
que limite de AL necesita"*. R-096.

Mientras se define si el bot debe cotizar los dos limites por si mismo, lo que
NO puede seguir pasando es que el pedido se pierda: tiene que salir a la vista
en el analisis.
"""
from __future__ import annotations

from modules.analysis_email_builder import build_analysis_email
from modules.quote_profile import QuoteProfile


def _profile(extra=None):
    p = QuoteProfile()
    p.applicant.business_name = "T&S Logistics"
    p.applicant.is_new_venture = True
    p.documents_present = ["BLUE QUOTE"]
    p.coverages_detail.bodily_injury_limit = "$1M CSL"
    if extra:
        p.requested_extra_al_limits = list(extra)
    return p


def _build(profile):
    return build_analysis_email(
        profile=profile, commodity="CANNED GOODS",
        tipo_negocio="DRY VAN / REEFER", evaluations=[], mga_list=[],
        original_subject="Submission New venture /T&S Logistics",
    )["body"]


def test_el_campo_existe_y_arranca_vacio():
    assert QuoteProfile().requested_extra_al_limits == []


def test_limite_extra_sale_en_el_correo():
    body = _build(_profile(["$750K CSL"]))
    assert "750" in body


def test_el_aviso_nombra_los_dos_limites():
    body = _build(_profile(["$750K CSL"]))
    assert "$1M CSL" in body and "$750K CSL" in body


def test_sin_limite_extra_no_hay_aviso():
    body = _build(_profile())
    assert "750" not in body


# --------------------------------------------------------------------------
# El pedido escrito en el cuerpo del correo
# --------------------------------------------------------------------------

def _from_body(body, primary="$1M CSL"):
    from workflow_orchestrator import QuoteWorkflowOrchestrator as O
    return O._al_limits_from_body(body, primary)


def test_frase_literal_de_jorge():
    assert _from_body("POR FAVOR SOLICITAR UNA QUOTE DE $750,000 TAMBIÉN") \
        == ["$750K CSL"]


def test_funciona_con_html():
    assert _from_body("<p>solicitar una <b>quote</b> de $750,000</p>") \
        == ["$750K CSL"]


def test_no_repite_el_limite_que_ya_se_cotiza():
    assert _from_body("quote de $1,000,000 por favor", primary="$1M CSL") == []


def test_ignora_montos_que_no_son_limites():
    """Un target price o el valor de un camion no son limites de AL."""
    assert _from_body("el camion vale $45,000 y el target price es $8,000") == []


def test_cuerpo_vacio():
    assert _from_body("") == []
    assert _from_body(None) == []


def test_sobrevive_el_viaje_por_la_cola():
    """El perfil se serializa a JSON para encolar el job — si el campo se
    pierde ahi, el worker nunca lo ve."""
    p = _profile(["$750K CSL"])
    volvio = QuoteProfile.from_dict(p.to_dict())
    assert volvio.requested_extra_al_limits == ["$750K CSL"]
