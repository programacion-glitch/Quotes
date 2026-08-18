"""Qué dice el correo cuando se pidió más de un límite de AL (R-097).

Antes el aviso decía "hay que hacerla a mano", porque el bot cotizaba uno solo.
Desde que los cotiza los dos, ese texto sería falso: el aviso pasa a decir qué
se está cotizando y, cuando corresponde, qué MGA no ofrece un límite pedido.
"""
from __future__ import annotations

from modules.analysis_email_builder import build_analysis_email
from modules.quote_profile import QuoteProfile


def _perfil(extras=None, principal="$1M CSL"):
    p = QuoteProfile()
    p.applicant.business_name = "T&S LOGISTICS"
    p.applicant.is_new_venture = True
    p.documents_present = ["BLUE QUOTE"]
    p.coverages_detail.bodily_injury_limit = principal
    if extras:
        p.requested_extra_al_limits = list(extras)
    return p


def _correo(profile, sin_oferta=None):
    return build_analysis_email(
        profile=profile, commodity="CANNED GOODS",
        tipo_negocio="DRY VAN / REEFER", evaluations=[], mga_list=[],
        original_subject="Submission New venture /T&S Logistics",
        al_limits_unavailable=sin_oferta or [],
    )["body"]


def test_el_correo_nombra_los_dos_limites():
    body = _correo(_perfil(["$750K CSL"]))
    assert "$1M CSL" in body and "$750K CSL" in body


def test_ya_no_dice_que_hay_que_cotizar_a_mano():
    """El bot los cotiza los dos: repetir el texto viejo mandaría a Diana a
    hacer trabajo que ya está hecho."""
    body = _correo(_perfil(["$750K CSL"]))
    assert "a mano" not in body.lower()


def test_avisa_cuando_un_mga_no_ofrece_el_limite_pedido():
    body = _correo(_perfil(["$750K CSL"]),
                   sin_oferta=[("GEICO", "$750K CSL")])
    assert "GEICO" in body
    assert "no ofrece" in body.lower()


def test_el_mga_que_no_ofrece_el_limite_se_nombra_una_sola_vez_por_limite():
    body = _correo(_perfil(["$750K CSL"]),
                   sin_oferta=[("GEICO", "$750K CSL"), ("GEICO", "$750K CSL")])
    assert body.lower().count("no ofrece") == 1


def test_sin_limites_extra_no_hay_aviso_de_al():
    body = _correo(_perfil())
    assert "750" not in body
    assert "no ofrece" not in body.lower()


def test_sin_limites_extra_pero_con_un_mga_que_no_lo_ofrece_igual_avisa():
    """Caso del cliente que pide SOLO $750K: GEICO cotiza con su límite
    estándar y eso tiene que verse."""
    body = _correo(_perfil(principal="$750K CSL"),
                   sin_oferta=[("GEICO", "$750K CSL")])
    assert "no ofrece" in body.lower() and "GEICO" in body
