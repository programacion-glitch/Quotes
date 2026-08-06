"""Fixes de la primera corrida live post-despliegue (T&S Logistics, 2026-08-06):

1. R-088 — effective date vencida: Progressive rechaza fechas < hoy
   ("The policy effective date cannot be less than ...") → se cotiza con HOY.
2. current_carrier='NEW BUSINESS' es un sentinel de negocio nuevo, NO una
   aseguradora: el bot lo trataba como evidencia de establecido (invertido).
3. Individual / Sole Proprietor no renderiza el radio de Business Name:
   el nombre comercial va en 'DBA Name' (sin quemar timeouts en el radio).
"""
from unittest.mock import AsyncMock, MagicMock

from workflow_orchestrator import QuoteWorkflowOrchestrator
from modules.progressive.pages.business_info_page import BusinessInfoPage


# ---- 1. R-088: clamp de effective date -------------------------------------

from datetime import date

_clamp = QuoteWorkflowOrchestrator._clamp_effective_date


class TestClampEffectiveDate:
    def test_fecha_vencida_se_cotiza_con_hoy(self):
        assert _clamp("08/05/2026", today=date(2026, 8, 6)) == "08/06/2026"

    def test_fecha_de_hoy_pasa_intacta(self):
        assert _clamp("08/06/2026", today=date(2026, 8, 6)) == "08/06/2026"

    def test_fecha_futura_pasa_intacta(self):
        assert _clamp("09/21/2026", today=date(2026, 8, 6)) == "09/21/2026"

    def test_fecha_imparseable_pasa_intacta(self):
        assert _clamp("13/45/2026", today=date(2026, 8, 6)) == "13/45/2026"

    def test_muy_vencida_tambien_clampa(self):
        assert _clamp("1/2/2025", today=date(2026, 8, 6)) == "08/06/2026"


# ---- 2. current_carrier: real vs sentinel NV vs vacío ----------------------

_kind = QuoteWorkflowOrchestrator._carrier_kind


class TestCarrierKind:
    def test_carrier_real_es_establecido(self):
        assert _kind("PROGRESSIVE") == "real"
        assert _kind("Great West Casualty") == "real"

    def test_new_business_es_evidencia_de_new_venture(self):
        assert _kind("NEW BUSINESS") == "nv"
        assert _kind("new business") == "nv"
        assert _kind(" New Venture ") == "nv"
        assert _kind("NEW") == "nv"

    def test_vacio_o_na_no_es_evidencia(self):
        assert _kind("") == "empty"
        assert _kind(None) == "empty"
        assert _kind("N/A") == "empty"
        assert _kind("NONE") == "empty"
        assert _kind("-") == "empty"


# ---- 3. Individual: DBA en vez del radio inexistente -----------------------

def _radio_with_count(n: int):
    loc = MagicMock()
    loc.count = AsyncMock(return_value=n)
    return loc


async def test_individual_sin_radio_llena_dba():
    """Si el radio 'Enter a different Business Name' no existe (layout de
    Individual), el nombre comercial va al DBA y NO se intenta el click."""
    page = MagicMock()
    page.wait_for_timeout = AsyncMock()
    page.get_by_role = MagicMock(return_value=_radio_with_count(0))

    bip = BusinessInfoPage.__new__(BusinessInfoPage)
    bip.page = page
    bip.warnings = []
    bip._fill_placeholder = AsyncMock()

    await bip._fill_business_name("T&S Logistics", None)

    bip._fill_placeholder.assert_awaited_once_with("DBA Name", "T&S Logistics")


async def test_safe_select_combo_reintenta_cuando_el_boundlist_esta_vacio():
    """Live 2026-08-06 (T&S, RATES): el combo de BI/PD abría con el store
    aún cargando (0 opciones) y el required vacío bloqueaba TODAS las
    acciones del server. Con el boundlist vacío se cierra (Escape), se
    asienta ExtJS y se reintenta — sin quemar el timeout del click."""
    from modules.progressive.pages.base_page import BasePage
    from modules.progressive.pages._exceptions import ComboSelectError
    import pytest

    page = MagicMock()
    page.wait_for_timeout = AsyncMock()
    page.wait_for_function = AsyncMock()
    page.evaluate = AsyncMock(return_value=True)   # boundlist siempre vacío
    page.keyboard.press = AsyncMock()
    page.screenshot = AsyncMock()

    combo = MagicMock()
    combo.click = AsyncMock()
    combo.input_value = AsyncMock(return_value="")

    bp = BasePage.__new__(BasePage)
    bp.page = page
    bp.screenshot = AsyncMock(return_value=None)
    bp.dump_debug_context = AsyncMock(return_value={})
    bp._close_open_boundlist = AsyncMock()

    with pytest.raises(ComboSelectError):
        await bp.safe_select_combo(combo, "$1 million CSL", retries=1)

    # Escape presionado en cada intento (2 intentos con retries=1)
    assert page.keyboard.press.await_count == 2
    # nunca se intentó clickear una opción inexistente
    page.get_by_role.assert_not_called()


async def test_individual_con_dba_explicito_prefiere_el_dba():
    page = MagicMock()
    page.wait_for_timeout = AsyncMock()
    page.get_by_role = MagicMock(return_value=_radio_with_count(0))

    bip = BusinessInfoPage.__new__(BusinessInfoPage)
    bip.page = page
    bip.warnings = []
    bip._fill_placeholder = AsyncMock()

    await bip._fill_business_name("STEPHANIE WILLIAMS", "T&S Logistics")

    bip._fill_placeholder.assert_awaited_once_with("DBA Name", "T&S Logistics")
