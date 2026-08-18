"""El límite de AL del job llega hasta la cotización y hasta el nombre del PDF.

Cadena completa (R-097): el worker escribe `job.al_limit` en el perfil → el
field_mapper de cada MGA lo traduce al texto que muestra su UI → el flow lo usa
para nombrar el PDF. Si cualquiera de esos eslabones se corta, el bot cotiza el
límite equivocado y lo etiqueta bien, que es el peor desenlace posible.
"""
from __future__ import annotations

import pytest

from modules.quote_profile import QuoteProfile


def _perfil(limite):
    p = QuoteProfile()
    p.applicant.business_name = "T&S LOGISTICS"
    p.applicant.usdot = "9731476"
    p.coverages_detail.bodily_injury_limit = limite
    return p


# ---------------------------------------------------------------------------
# Progressive
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("limite", ["$1M CSL", "$750K CSL", "$500K CSL"])
def test_progressive_lleva_el_limite_pedido_a_los_campos(limite):
    from modules.progressive.field_mapper import map_profile_to_fields
    fields = map_profile_to_fields(_perfil(limite))
    assert fields.coverages.bodily_injury_limit == limite


@pytest.mark.parametrize("limite,esperado", [
    ("$1M CSL", "$1 million CSL"),
    ("$750K CSL", "$750,000 CSL"),
    ("$500K CSL", "$500,000 CSL"),
])
def test_progressive_traduce_cada_limite_a_una_opcion_distinta(limite, esperado):
    """Si dos límites tradujeran al mismo texto, las dos cotizaciones saldrían
    idénticas con etiquetas distintas."""
    from modules.progressive.pages.coverages_rates_page import CoveragesRatesPage
    assert CoveragesRatesPage._BI_LIMIT_PROGRESSIVE_LABEL[limite] == esperado


# ---------------------------------------------------------------------------
# GEICO
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("limite,esperado", [
    ("$1M CSL", "$1,000,000/$1,000,000 or $1,000,000 CSL"),
    ("$500K CSL", "$500,000/$500,000 or $500,000 CSL"),
])
def test_geico_lleva_el_limite_pedido_a_los_campos(limite, esperado):
    from modules.geico.field_mapper import map_profile_to_fields
    fields = map_profile_to_fields(_perfil(limite))
    assert fields.current_bi_limits == esperado


def test_geico_nunca_recibe_un_job_de_750k():
    """GEICO no ofrece $750K: su mapper lo mandaría al default de $1M y el PDF
    saldría etiquetado '750K'. El guard está en al_limits, antes de encolar."""
    from modules.al_limits import mga_supports
    from modules.geico.field_mapper import _bi_limits_to_geico
    assert mga_supports("GEICO", "$750K CSL") is False
    # y por eso importa: si igual se colara, cotizaría un millón
    assert _bi_limits_to_geico("$750K CSL") == _bi_limits_to_geico(None)
