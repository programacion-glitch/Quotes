"""Dashboard NUEVO de GEICO (rediseño mapeado live 2026-08-06).

El widget de productos desapareció: ahora es "+ New Quote" → ZIP →
"Search Products" → checkbox "Commercial Auto/Trucking" → USDOT +
"Check USDOT" → "Start Quote" (pestaña nueva). El gate de elegibilidad NO
se perdió: se mudó al modal y sigue produciendo EligibilityHaltError.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.geico.pages.dashboard_page import (
    DashboardPage,
    EligibilityHaltError,
)


def _loc(*, count=1, visible=True, enabled=True, text=""):
    loc = MagicMock()
    loc.count = AsyncMock(return_value=count)
    loc.first = loc
    loc.nth = MagicMock(return_value=loc)
    loc.click = AsyncMock()
    loc.fill = AsyncMock()
    loc.wait_for = AsyncMock()
    loc.is_visible = AsyncMock(return_value=visible)
    loc.is_enabled = AsyncMock(return_value=enabled)
    loc.inner_text = AsyncMock(return_value=text)
    loc.scroll_into_view_if_needed = AsyncMock()
    return loc


def _page(*, not_eligible=None, buttons=None):
    """Página falsa: `not_eligible` es el locator del texto de rechazo y
    `buttons` el que devuelve get_by_role('button', ...)."""
    page = MagicMock()
    page.wait_for_timeout = AsyncMock()
    page.locator = MagicMock(return_value=_loc())
    page.get_by_role = MagicMock(return_value=buttons or _loc())
    page.get_by_text = MagicMock(
        return_value=not_eligible or _loc(count=0, visible=False))
    return page


def _dashboard(page):
    dp = DashboardPage.__new__(DashboardPage)
    dp.page = page
    dp.warnings = []
    dp.screenshot = AsyncMock(return_value=None)
    return dp


class TestCheckUsdotEnElModal:
    async def test_not_eligible_levanta_halt(self):
        """Respuesta real live: 'Not Eligible — Eligibility for USDOT:… was
        not found'. Debe ser HALT (sin retry), como en el dashboard viejo."""
        dp = _dashboard(_page(not_eligible=_loc(
            text="Not Eligible Eligibility for USDOT:9731476 in state:TX "
                 "with effectiveDate:08/06/2026 was not found")))

        with pytest.raises(EligibilityHaltError) as exc:
            await dp._check_usdot_in_modal("9731476")

        assert "9731476" in str(exc.value)
        assert "was not found" in str(exc.value)
        dp.screenshot.assert_awaited()

    async def test_elegible_cuando_start_quote_se_habilita(self):
        dp = _dashboard(_page(buttons=_loc(enabled=True)))
        await dp._check_usdot_in_modal("1234567")  # no levanta
        assert dp.warnings == []

    async def test_sin_veredicto_advierte_pero_no_frena(self):
        """El wizard revalida el USDOT en Step 1: no inventamos elegibilidad
        ni abortamos la cotización."""
        botones = _loc(enabled=True)
        dp = _dashboard(_page(buttons=botones))
        # El click inicial sí encuentra botón habilitado; el veredicto no llega.
        botones.is_enabled = AsyncMock(side_effect=[True] + [False] * 200)

        await dp._check_usdot_in_modal("7654321")

        assert any("no dio veredicto" in w for w in dp.warnings)

    async def test_sin_usdot_no_toca_el_modal(self):
        dp = _dashboard(_page())
        await dp._check_usdot_in_modal("")
        dp.page.locator.assert_not_called()

    async def test_clickea_el_boton_habilitado_no_el_de_la_tarjeta(self):
        """Hay DOS botones 'Check USDOT': el del modal (habilitado) y el de la
        tarjeta del dashboard (deshabilitado). Acotar por role=dialog NO sirve
        (el modal no siempre expone ese rol) — se elige el habilitado."""
        tarjeta = _loc(enabled=False)   # el de fondo
        modal = _loc(enabled=True)      # el bueno
        botones = MagicMock()
        botones.count = AsyncMock(return_value=2)
        botones.nth = MagicMock(side_effect=lambda i: [tarjeta, modal][i])
        dp = _dashboard(_page(buttons=botones))

        await dp._click_enabled(botones, "Check USDOT")

        tarjeta.click.assert_not_called()
        modal.click.assert_awaited_once()

    async def test_si_ningun_boton_se_habilita_falla_con_contexto(self):
        botones = _loc(enabled=False)
        dp = _dashboard(_page(buttons=botones))
        with pytest.raises(RuntimeError, match="Check USDOT"):
            await dp._click_enabled(botones, "Check USDOT", timeout_ms=600)


class TestDeteccionDeLayout:
    async def test_reconoce_el_dashboard_nuevo(self):
        page = MagicMock()
        page.wait_for_timeout = AsyncMock()

        def _locator(sel):
            # solo el chrome NUEVO está presente
            return _loc(count=1 if sel == DashboardPage._NEW_DASHBOARD else 0,
                        visible=sel == DashboardPage._NEW_DASHBOARD)

        page.locator = MagicMock(side_effect=_locator)
        dp = _dashboard(page)
        assert await dp._detect_layout(timeout_ms=1_000) == "new"

    async def test_reconoce_el_dashboard_viejo(self):
        page = MagicMock()
        page.wait_for_timeout = AsyncMock()

        def _locator(sel):
            return _loc(count=1 if sel == DashboardPage._WIDGET else 0,
                        visible=sel == DashboardPage._WIDGET)

        page.locator = MagicMock(side_effect=_locator)
        dp = _dashboard(page)
        assert await dp._detect_layout(timeout_ms=1_000) == "old"

    async def test_ninguno_presente_devuelve_none(self):
        page = MagicMock()
        page.wait_for_timeout = AsyncMock()
        page.locator = MagicMock(return_value=_loc(count=0, visible=False))
        dp = _dashboard(page)
        assert await dp._detect_layout(timeout_ms=600) is None
