"""AMWINS: inelegible segun el condado del zip code PHYSICAL (Diana 2026-08-10).

*"es muy importante revisar en que condado se encuentra mediante el zip code
del physical ya que este programa seria inelegible para los siguientes
condados: Brazoria, Fort Bend, Galveston, Harris, Montgomery, Hidalgo, Starr,
Cameron y Beaumont"*. R-095.

Criterio de diseño: un ZIP que no sabemos mapear NO bloquea — avisa. Rechazar
un riesgo por un dato que no tenemos es peor que revisarlo a mano.
"""
from __future__ import annotations

import pytest

from modules.quote_profile import ApplicantProfile, QuoteProfile
from modules.tx_counties import county_for_zip


# --------------------------------------------------------------------------
# El mapa de ZIPs
# --------------------------------------------------------------------------

@pytest.mark.parametrize("zip_code,expected", [
    ("77002", "Harris"),        # centro de Houston
    ("77449", "Harris"),        # Katy
    ("77479", "Fort Bend"),     # Sugar Land
    ("77584", "Brazoria"),      # Pearland
    ("77550", "Galveston"),     # isla
    ("77301", "Montgomery"),    # Conroe
    ("78501", "Hidalgo"),       # McAllen
    ("78582", "Starr"),         # Rio Grande City
    ("78520", "Cameron"),       # Brownsville
    ("77701", "Beaumont"),      # ciudad de Beaumont
])
def test_zips_bloqueados_se_reconocen(zip_code, expected):
    assert county_for_zip(zip_code) == expected


@pytest.mark.parametrize("zip_code", ["75241", "78045", "79901", "76102"])
def test_zips_lejos_del_area_se_resuelven_solos(zip_code):
    """Dallas, Laredo, El Paso, Fort Worth: no pueden estar en un condado
    bloqueado, asi que no se pide revision manual."""
    from modules.tx_counties import OUTSIDE_RISK_AREA
    assert county_for_zip(zip_code) == OUTSIDE_RISK_AREA


def test_zip_en_zona_de_riesgo_sin_mapear_queda_none():
    """77418 (Bellville) cae en el prefijo del area de Houston pero no esta
    mapeado: eso SI se revisa a mano."""
    assert county_for_zip("77489") == "Fort Bend"      # control: mapeado
    assert county_for_zip("77418") is None              # zona de riesgo, sin mapear


def test_zip_con_sufijo_plus4():
    assert county_for_zip("77002-1234") == "Harris"


@pytest.mark.parametrize("bad", [None, "", "ABC", "123"])
def test_zip_invalido_no_revienta(bad):
    assert county_for_zip(bad) is None


# --------------------------------------------------------------------------
# La regla en el engine
# --------------------------------------------------------------------------

def _profile(physical_zip):
    return QuoteProfile(applicant=ApplicantProfile(
        business_name="TEST LLC", physical_zip=physical_zip,
        zip_code="75241", state="TX"))


def _eval(engine_cls, rule, profile):
    eng = object.__new__(engine_cls)
    return eng._check_blocked_counties(rule, profile)


BLOCKED = "Brazoria,Fort Bend,Galveston,Harris,Montgomery,Hidalgo,Starr,Cameron,Beaumont"


def test_zip_en_condado_bloqueado_falla():
    from modules.rule_engine import RuleEngine
    failure, warning = _eval(RuleEngine, {"BLOCKED_COUNTIES": BLOCKED},
                             _profile("77002"))
    assert failure is not None
    assert "Harris" in failure.reason


def test_zip_fuera_del_area_pasa_sin_ruido():
    """T&S Logistics es de Dallas (75241): AMWINS le sigue aplicando y no
    ensucia el correo con un aviso de revision manual."""
    from modules.rule_engine import RuleEngine
    failure, warning = _eval(RuleEngine, {"BLOCKED_COUNTIES": BLOCKED},
                             _profile("75241"))
    assert failure is None
    assert warning is None


def test_zip_desconocido_en_zona_de_riesgo_avisa_pero_no_bloquea():
    from modules.rule_engine import RuleEngine
    failure, warning = _eval(RuleEngine, {"BLOCKED_COUNTIES": BLOCKED},
                             _profile("77418"))
    assert failure is None
    assert warning is not None
    assert "condado" in warning.lower()


def test_sin_regla_de_condados_no_hace_nada():
    from modules.rule_engine import RuleEngine
    failure, warning = _eval(RuleEngine, {"BLOCKED_COUNTIES": None},
                             _profile("77002"))
    assert failure is None and warning is None


def test_usa_el_zip_physical_no_el_de_correo():
    """R-085: el physical manda. Mailing en Dallas, physical en Houston."""
    from modules.rule_engine import RuleEngine
    p = QuoteProfile(applicant=ApplicantProfile(
        business_name="TEST LLC", zip_code="75241", physical_zip="77002",
        state="TX"))
    failure, _ = _eval(RuleEngine, {"BLOCKED_COUNTIES": BLOCKED}, p)
    assert failure is not None, "debe mirar el physical_zip (77002 = Harris)"
