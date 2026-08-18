"""El análisis va ARRIBA, los datos de respaldo abajo.

Diana tenía que scrollear todo el correo —cliente, documentos, conductores,
loss run— para llegar al veredicto: qué MGA califica y cuál no. El orden se
invirtió el 2026-08-18: primero lo que hay que decidir, después con qué se
decidió.

Este test fija el orden. Si alguien reordena el template sin querer, salta acá
y no en la bandeja de Diana.
"""
from __future__ import annotations

import pytest

from modules.analysis_email_builder import build_analysis_email
from modules.quote_profile import QuoteProfile


@pytest.fixture()
def body():
    p = QuoteProfile()
    p.applicant.business_name = "T&S LOGISTICS"
    p.applicant.usdot = "9731476"
    p.documents_present = ["BLUE QUOTE"]
    return build_analysis_email(
        profile=p, commodity="CANNED GOODS", tipo_negocio="DRY VAN / REEFER",
        evaluations=[], mga_list=[], original_subject="Submission //T&S",
    )["body"]


def _pos(body, *fragmentos):
    """Posición del primer fragmento que aparezca (los títulos llevan HTML)."""
    for f in fragmentos:
        i = body.find(f)
        if i != -1:
            return i
    pytest.fail(f"no se encontró ninguno de {fragmentos} en el correo")


def test_las_cotizaciones_van_antes_que_el_analisis():
    """Lo ya cotizado manda: es el resultado, no una evaluación."""
    from modules.quote_queue.messages import RpaQuoteOutcome, render_rpa_section
    p = QuoteProfile()
    p.applicant.business_name = "T&S LOGISTICS"
    b = build_analysis_email(
        profile=p, commodity="C", tipo_negocio="T", evaluations=[], mga_list=[],
        original_subject="Submission //T&S",
        rpa_quotes_section=render_rpa_section([RpaQuoteOutcome(
            mga="PROGRESSIVE", status="quoted", reason="ok",
            premium="$44,621", al_limit="$750K CSL")]),
    )["body"]
    assert _pos(b, "Cotizaciones autom") < _pos(b, "MGAs Web")


def test_el_analisis_va_antes_de_los_datos_del_cliente(body):
    assert _pos(body, "MGAs Web") < _pos(body, "Cliente")


def test_las_mgas_elegibles_van_antes_de_documentos(body):
    assert _pos(body, "MGAs Elegibles") < _pos(body, "Documentos Recibidos")


def test_las_no_elegibles_van_antes_de_conductores(body):
    assert _pos(body, "MGAs No Elegibles") < _pos(body, "Conductores")


def test_que_faltaria_va_antes_del_loss_run(body):
    assert _pos(body, "Desbloquear") < _pos(body, "Loss Run")


def test_el_orden_interno_del_analisis_se_conserva(body):
    """Reglas -> elegibles -> no elegibles -> qué faltaría."""
    o = [_pos(body, "MGAs Web"), _pos(body, "MGAs Elegibles"),
         _pos(body, "MGAs No Elegibles"), _pos(body, "Desbloquear")]
    assert o == sorted(o)


def test_el_orden_interno_de_los_datos_se_conserva(body):
    o = [_pos(body, "Cliente"), _pos(body, "Documentos Recibidos"),
         _pos(body, "Conductores"), _pos(body, "Loss Run")]
    assert o == sorted(o)


def test_los_avisos_siguen_siendo_lo_primero(body):
    """El banner de warnings va arriba de todo — incluso de las cotizaciones."""
    p = QuoteProfile()
    p.applicant.business_name = "X"
    p.coverages_detail.bodily_injury_limit = "$1M CSL"
    p.requested_extra_al_limits = ["$750K CSL"]
    b = build_analysis_email(
        profile=p, commodity="C", tipo_negocio="T", evaluations=[],
        mga_list=[], original_subject="Submission //X")["body"]
    assert _pos(b, "mas de un limite de AL") < _pos(b, "MGAs Web")
