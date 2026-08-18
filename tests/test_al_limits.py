"""Vocabulario de limites de Auto Liability (R-097).

Cuando el agente pide DOS limites (T&S Logistics: $1M CSL en la Blue Quote y
$750K en el cuerpo del correo), el bot cotiza los dos — un job por MGA y
limite. Eso necesita dos cosas que antes no existian:

1. una ETIQUETA corta y estable para nombrar el PDF ('AL 1M', 'AL 750K'),
   porque hoy dos indicaciones del mismo carrier el mismo dia colisionan;
2. saber si el MGA ofrece ese limite. GEICO no tiene $750K: su mapper
   (_bi_limits_to_geico) cae al default de $1M, asi que un job de 750K
   cotizaria un millon y saldria etiquetado '750K'. Eso es peor que no
   cotizar — hay que no encolarlo y decirlo.
"""
from __future__ import annotations

import pytest

from modules.al_limits import al_label, mga_supports, supported_by


# ---------------------------------------------------------------------------
# Etiqueta para nombres de archivo
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("limite,esperado", [
    ("$1M CSL", "AL 1M"),
    ("$750K CSL", "AL 750K"),
    ("$500K CSL", "AL 500K"),
])
def test_etiqueta_de_los_limites_usuales(limite, esperado):
    assert al_label(limite) == esperado


def test_la_forma_larga_da_la_misma_etiqueta_que_la_corta():
    """La Blue Quote escribe '$1,000,000 CSL' y el cuerpo del correo '$1M CSL';
    si dieran etiquetas distintas, el mismo limite generaria dos nombres de
    archivo y el dedup de Drive dejaria de servir."""
    assert al_label("$1,000,000 CSL") == al_label("$1M CSL")
    assert al_label("$750,000 CSL") == al_label("$750K CSL")


def test_un_limite_desconocido_no_rompe_el_nombre_del_archivo():
    """Preferimos una etiqueta fea a una excepcion que tumbe la subida."""
    etiqueta = al_label("$1.5M CSL")
    assert etiqueta.startswith("AL ")
    assert "/" not in etiqueta and "\\" not in etiqueta and ":" not in etiqueta


def test_sin_limite_no_hay_etiqueta():
    assert al_label(None) == ""
    assert al_label("") == ""


# ---------------------------------------------------------------------------
# Que ofrece cada MGA
# ---------------------------------------------------------------------------

def test_progressive_ofrece_750k():
    assert mga_supports("PROGRESSIVE", "$750K CSL") is True


def test_geico_no_ofrece_750k():
    """El caso que motivo la regla: sin esto, GEICO cotiza $1M y lo etiqueta
    '750K'."""
    assert mga_supports("GEICO", "$750K CSL") is False


@pytest.mark.parametrize("mga", ["PROGRESSIVE", "GEICO"])
def test_los_dos_ofrecen_1m_y_500k(mga):
    assert mga_supports(mga, "$1M CSL") is True
    assert mga_supports(mga, "$500K CSL") is True


def test_la_forma_larga_se_reconoce_igual():
    assert mga_supports("GEICO", "$1,000,000 CSL") is True


def test_mga_desconocido_no_bloquea():
    """Las MGAs por correo no cotizan solas: no nos toca filtrarles nada."""
    assert mga_supports("AMWINS", "$750K CSL") is True


def test_sin_limite_no_se_filtra_nada():
    assert mga_supports("GEICO", None) is True


def test_supported_by_lista_lo_que_el_mga_cotiza():
    assert "$750K CSL" in supported_by("PROGRESSIVE")
    assert "$750K CSL" not in supported_by("GEICO")


# ---------------------------------------------------------------------------
# Anti-deriva: este modulo dice que se puede cotizar, los mappers dicen COMO.
# Si alguien agrega una opcion en un lado y no en el otro, el bot encola un
# job que despues cotiza el limite equivocado en silencio.
# ---------------------------------------------------------------------------

def test_progressive_no_promete_limites_que_su_mapper_no_sabe_traducir():
    from modules.progressive.pages.coverages_rates_page import CoveragesRatesPage
    traducibles = set(CoveragesRatesPage._BI_LIMIT_PROGRESSIVE_LABEL)
    assert supported_by("PROGRESSIVE") <= traducibles


def test_geico_no_promete_limites_que_caen_al_default_de_su_mapper():
    from modules.geico.field_mapper import _bi_limits_to_geico
    default = _bi_limits_to_geico(None)
    for limite in supported_by("GEICO"):
        traducido = _bi_limits_to_geico(limite)
        if "1,000,000" in limite or "1M" in limite:
            continue  # el default ES $1M; no distingue caida de acierto
        assert traducido != default, (
            f"GEICO dice ofrecer {limite} pero su mapper lo manda al default")
