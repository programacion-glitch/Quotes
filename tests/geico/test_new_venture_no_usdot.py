"""GEICO también cotiza New Ventures sin USDOT (Diana, 2026-08-06).

Mapeado live el mismo día con el MCP (sesión de gateway2, ZIP 77036):
  - En el modal 'Start New Quote', con `#start-quote-usdot` VACÍO el botón
    'Start Quote' queda HABILITADO (`enabled: true`) y el campo no es
    `required` → el gate de 'Check USDOT' es opcional.
  - El wizard abre igual (sales.geico.com/quote, 'GEICO Business Class &
    USDOT') y Step 1 renderiza con el radio de USDOT SIN responder:
        Yes / No / "Not yet, but the customer has applied for one."
    El `value` del custom element ES ese string completo.

Sin mapearla, esa pregunta caía en el HALT de 'UNMAPPED conditional question'.
Regla R-092 (misma que Progressive).
"""

from __future__ import annotations

from modules.geico.field_mapper import MappedFields
from modules.geico.pages.business_class_page import _match_conditional_default


USDOT_Q = ("Does the customer have a USDOT Number registered to themselves "
           "or their business?")
NOT_YET = "Not yet, but the customer has applied for one."


# --------------------------------------------------------------------------
# El USDOT deja de ser crítico: sin él ya no se aborta antes del browser
# --------------------------------------------------------------------------

def _fields(**kw):
    base = dict(business_name="TEST LLC", zip_code="77036",
                effective_date="08/10/2026", owner_first_name="ANA",
                owner_last_name="GARCIA")
    base.update(kw)
    return MappedFields(**base)


def test_missing_usdot_no_longer_blocks_the_quote():
    assert "usdot" not in _fields(usdot=None).missing_critical()


def test_other_critical_fields_still_block():
    """Aflojar el USDOT no puede aflojar el resto."""
    missing = _fields(usdot=None, business_name=None,
                      zip_code=None).missing_critical()
    assert "business_name" in missing
    assert "zip_code" in missing


def test_new_venture_only_misses_what_it_actually_lacks():
    """Sin USDOT, lo único que falta es lo que de verdad no se cargó
    (vehículos/conductores) — el USDOT ya no aparece."""
    missing = _fields(usdot=None).missing_critical()
    assert "usdot" not in missing
    assert all("vehicle" in m or "driver" in m for m in missing), missing


# --------------------------------------------------------------------------
# Step 1: la pregunta de USDOT se responde 'Not yet', no se rompe
# --------------------------------------------------------------------------

def test_usdot_question_is_mapped():
    answer, soft = _match_conditional_default(USDOT_Q)
    assert answer is not None, \
        "sin mapear, Step 1 haría HALT por 'UNMAPPED conditional question'"


def test_usdot_question_answers_not_yet():
    answer, _ = _match_conditional_default(USDOT_Q)
    assert answer == NOT_YET


def test_usdot_answer_is_never_plain_no():
    """'No' declararía que el cliente NUNCA tendrá USDOT — falso en un NV."""
    answer, _ = _match_conditional_default(USDOT_Q)
    assert answer != "No"


def test_unknown_question_still_halts():
    """La red de seguridad de preguntas nuevas sigue intacta."""
    answer, _ = _match_conditional_default(
        "Does the customer transport nuclear waste on weekends?")
    assert answer is None


# --------------------------------------------------------------------------
# Centinelas: mismo criterio estricto que Progressive
# --------------------------------------------------------------------------

def test_geico_sentinels_normalize_to_none():
    from modules.geico.field_mapper import _clean_usdot
    for sentinel in ("N/A", "n/a", " NA ", "NONE", "-", "TBD", "PENDING",
                     "NEW VENTURE", "", "PENDIENTE DE ASIGNAR"):
        assert _clean_usdot(sentinel) is None, sentinel


def test_geico_real_usdot_survives():
    from modules.geico.field_mapper import _clean_usdot
    assert _clean_usdot(" 2033673 ") == "2033673"
