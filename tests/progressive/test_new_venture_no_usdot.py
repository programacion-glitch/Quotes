"""New Venture sin USDOT: Progressive SÍ debe cotizar (Diana, 2026-08-06:
"Solo funciona Progressive y Geico para ese tipo de clientes / no hay necesidad
de verificar el USDOT").

La respuesta al radio 'Does the customer have a USDOT Number?' es 'Not Yet'
(el cliente aplicará dentro de 60 días), NO 'No'. Un New Venture de trucking
va a tener USDOT; decir "no lo va a tener" sería falso ante el carrier.
Regla R-092 — ver config/mga_decision_rules.xlsx.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules import decision_ledger
from modules.progressive.pages.business_info_page import BusinessInfoPage


NOT_YET = ("Not Yet - but the customer has applied/will apply for a "
           "USDOT number within 60 days")
YES = "Yes - the customer has a USDOT number"
NO = "No - and the customer will not have a USDOT number"


def _page_with_radio_spy():
    """BusinessInfoPage sin __init__ + espía del label elegido."""
    bip = BusinessInfoPage.__new__(BusinessInfoPage)
    chosen = {}

    radio = MagicMock()
    radio.click = AsyncMock()
    group = MagicMock()
    group.get_by_role = MagicMock(
        side_effect=lambda role, name: chosen.setdefault("label", name) and radio or radio
    )

    async def _find_radiogroup(label):
        chosen["group"] = label
        return group

    bip.find_radiogroup = _find_radiogroup
    bip.settle_extjs = AsyncMock()
    return bip, chosen


async def test_no_usdot_answers_not_yet():
    bip, chosen = _page_with_radio_spy()
    await bip._answer_has_usdot(False)
    assert chosen["label"] == NOT_YET, \
        "un New Venture de trucking SÍ va a tener USDOT — 'No' sería falso"


async def test_no_usdot_never_answers_plain_no():
    bip, chosen = _page_with_radio_spy()
    await bip._answer_has_usdot(False)
    assert chosen["label"] != NO


async def test_with_usdot_still_answers_yes():
    bip, chosen = _page_with_radio_spy()
    await bip._answer_has_usdot(True)
    assert chosen["label"] == YES


async def test_choice_is_recorded_in_the_decision_ledger():
    """La respuesta es una declaración al carrier: tiene que salir en el
    correo de análisis para que Diana pueda auditarla."""
    decision_ledger.start_run("PROGRESSIVE")
    bip, _ = _page_with_radio_spy()
    await bip._answer_has_usdot(False)
    entries = decision_ledger.entries()
    hit = [e for e in entries
           if "USDOT" in e["field"] and "Not Yet" in e["chosen"]]
    assert hit, f"sin registro en el ledger: {[(e['field'], e['chosen']) for e in entries]}"
    assert hit[0]["rule_id"] == "R-092"


async def test_quote_flow_no_longer_halts_without_usdot():
    """El guard 'USDOT is required' tiene que haber desaparecido del flujo."""
    import inspect
    from modules.progressive import quote_flow
    src = inspect.getsource(quote_flow)
    assert "USDOT is required but missing" not in src
    assert "Sin USDOT: la Blue Quote no trae" not in src
