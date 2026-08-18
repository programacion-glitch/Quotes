"""Qué cotizaciones encola una submission cuando se piden varios límites de AL.

R-097. Reglas, en orden de importancia:

1. Nunca cotizar un límite que el MGA no ofrece y etiquetarlo como si sí:
   GEICO no tiene $750K y su mapper cae al default de $1M.
2. Nunca perder una cotización: si NINGÚN límite pedido le sirve al MGA, se
   cotiza igual con su default y se avisa — antes de R-097 eso era lo que
   pasaba (en silencio), y el objetivo del bot es maximizar cotizaciones.
3. Un solo límite pedido = exactamente lo de siempre, un job sin límite fijado.
"""
from __future__ import annotations

from workflow_orchestrator import QuoteWorkflowOrchestrator as O


def _plan(mgas, primary, extras):
    return O._jobs_to_enqueue(mgas, primary, extras)


# ---------------------------------------------------------------------------
# El caso que originó la regla: T&S Logistics pidió $1M y $750K
# ---------------------------------------------------------------------------

def test_progressive_cotiza_los_dos_limites():
    jobs, _ = _plan(["PROGRESSIVE"], "$1M CSL", ["$750K CSL"])
    assert jobs == [("PROGRESSIVE", "$1M CSL"), ("PROGRESSIVE", "$750K CSL")]


def test_geico_cotiza_solo_el_que_ofrece():
    jobs, _ = _plan(["GEICO"], "$1M CSL", ["$750K CSL"])
    assert jobs == [("GEICO", "$1M CSL")]


def test_el_limite_que_geico_no_ofrece_se_reporta():
    _, faltantes = _plan(["GEICO"], "$1M CSL", ["$750K CSL"])
    assert faltantes == [("GEICO", "$750K CSL")]


def test_progressive_no_reporta_faltantes():
    _, faltantes = _plan(["PROGRESSIVE"], "$1M CSL", ["$750K CSL"])
    assert faltantes == []


def test_las_dos_mgas_juntas():
    jobs, faltantes = _plan(["GEICO", "PROGRESSIVE"], "$1M CSL", ["$750K CSL"])
    assert jobs == [("GEICO", "$1M CSL"),
                    ("PROGRESSIVE", "$1M CSL"),
                    ("PROGRESSIVE", "$750K CSL")]
    assert faltantes == [("GEICO", "$750K CSL")]


# ---------------------------------------------------------------------------
# Sin límites extra: nada cambia
# ---------------------------------------------------------------------------

def test_un_solo_limite_encola_un_job_sin_limite_fijado():
    """Retrocompatible: el job no fija límite y el RPA usa el del perfil."""
    jobs, faltantes = _plan(["GEICO", "PROGRESSIVE"], "$1M CSL", [])
    assert jobs == [("GEICO", None), ("PROGRESSIVE", None)]
    assert faltantes == []


def test_sin_limite_en_la_blue_quote_tampoco_cambia_nada():
    jobs, faltantes = _plan(["PROGRESSIVE"], None, [])
    assert jobs == [("PROGRESSIVE", None)]
    assert faltantes == []


def test_el_mismo_limite_escrito_de_dos_formas_sigue_siendo_uno_solo():
    """La Blue Quote dice '$1,000,000 CSL' y el cuerpo del correo '$1M CSL':
    es el mismo pedido. Una sola cotización, y del modo de siempre (el límite
    lo pone el perfil), no dos idénticas con etiquetas distintas."""
    jobs, faltantes = _plan(["PROGRESSIVE"], "$1M CSL",
                            ["$1M CSL", "$1,000,000 CSL"])
    assert jobs == [("PROGRESSIVE", None)]
    assert faltantes == []


# ---------------------------------------------------------------------------
# No perder cotizaciones
# ---------------------------------------------------------------------------

def test_si_ningun_limite_le_sirve_al_mga_igual_se_cotiza_con_su_default():
    """El cliente pidió solo $750K y GEICO no lo tiene: antes GEICO cotizaba
    $1M en silencio. Ahora cotiza igual (no perdemos la cotización) pero
    queda dicho que el límite pedido no lo ofrece."""
    jobs, faltantes = _plan(["GEICO"], "$750K CSL", [])
    assert jobs == [("GEICO", None)]
    assert faltantes == [("GEICO", "$750K CSL")]


def test_el_extra_rescata_al_mga_que_no_ofrece_el_principal():
    jobs, faltantes = _plan(["GEICO"], "$750K CSL", ["$500K CSL"])
    assert jobs == [("GEICO", "$500K CSL")]
    assert faltantes == [("GEICO", "$750K CSL")]


def test_una_mga_por_correo_no_se_filtra():
    """AMWINS no se cotiza con RPA; acá no debería llegar, pero si llega no
    somos nosotros los que decidimos qué límites tiene."""
    jobs, faltantes = _plan(["AMWINS"], "$1M CSL", ["$750K CSL"])
    assert jobs == [("AMWINS", "$1M CSL"), ("AMWINS", "$750K CSL")]
    assert faltantes == []
