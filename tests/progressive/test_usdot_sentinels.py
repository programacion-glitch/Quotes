"""Las Blue Quotes de New Venture traen 'USDOT: N/A'.

Ese centinela viajaba entero hasta el buscador del dashboard de Progressive,
que responde 'This is not a valid USDOT number' y mata el flujo en el step
'dashboard' (no retryable). Live 2026-08-06: DIANA CAROLINA GARCIA OSORIO
quemó 2 jobs seguidos así (logs/progressive_error_dashboard.png).
"""

from __future__ import annotations

import pytest

from modules.quote_profile import QuoteProfile, ApplicantProfile, UnitsProfile
from modules.progressive.field_mapper import map_profile_to_fields
from modules.progressive.pages.home_page import HomePage


def _fields_for_usdot(usdot):
    profile = QuoteProfile(
        applicant=ApplicantProfile(
            business_name="TEST LLC", owner_name="OWNER NAME", usdot=usdot,
        ),
        units=UnitsProfile(count=0, vehicles=[]),
    )
    return map_profile_to_fields(profile, effective_date="08/10/2026")


# --------------------------------------------------------------------------
# field_mapper: el centinela nunca debe salir del mapper
# --------------------------------------------------------------------------

@pytest.mark.parametrize("sentinel", [
    "N/A", "n/a", " N/A ", "NA", "NONE", "none", "No", "-", "TBD",
    "PENDING", "NEW", "NEW VENTURE", "",
])
def test_sentinel_usdot_becomes_none(sentinel):
    assert _fields_for_usdot(sentinel).usdot is None


def test_missing_usdot_stays_none():
    assert _fields_for_usdot(None).usdot is None


def test_real_usdot_survives():
    assert _fields_for_usdot("2998569").usdot == "2998569"


def test_trailing_space_still_stripped():
    """Regresión: '4518340 ' con espacio rompía el lookup (fix previo)."""
    assert _fields_for_usdot("4518340 ").usdot == "4518340"


def test_non_numeric_usdot_is_discarded():
    """Progressive solo acepta dígitos; cualquier otra cosa rompe el widget."""
    assert _fields_for_usdot("PENDIENTE DE ASIGNAR").usdot is None


# --------------------------------------------------------------------------
# home_page: sin USDOT no se busca en SAFER (el widget es OPCIONAL)
# --------------------------------------------------------------------------

def _home_page_with_spies():
    """HomePage sin __init__ (no necesitamos un Page real) + espías."""
    hp = HomePage.__new__(HomePage)
    calls = []

    async def _state(code):
        calls.append(("state", code))

    async def _product(open_usdot_widget=True):
        calls.append(("product", open_usdot_widget))

    async def _search(usdot):
        calls.append(("search", usdot))

    async def _add(context):
        calls.append(("add",))
        return "WIZARD_PAGE"

    hp._select_state = _state
    hp._select_product_commercial_auto = _product
    hp._search_usdot = _search
    hp._add_products_to_quote = _add
    return hp, calls


async def test_start_new_quote_skips_safer_search_without_usdot():
    hp, calls = _home_page_with_spies()
    page = await hp.start_new_quote(None, context=object())
    assert page == "WIZARD_PAGE"
    assert not any(c[0] == "search" for c in calls), \
        "sin USDOT no se debe tocar el buscador de SAFER"
    assert ("add",) in calls, "igual hay que abrir el wizard"


async def test_start_new_quote_does_not_expand_usdot_widget_without_usdot():
    hp, calls = _home_page_with_spies()
    await hp.start_new_quote(None, context=object())
    assert ("product", False) in calls


async def test_start_new_quote_still_searches_with_real_usdot():
    hp, calls = _home_page_with_spies()
    await hp.start_new_quote("2998569", context=object())
    assert ("search", "2998569") in calls
    assert ("product", True) in calls
