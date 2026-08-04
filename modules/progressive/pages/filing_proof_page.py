"""Filing/Proof of Insurance page (interstitial CONDITIONAL).

Aparece entre BUSINESS (MoreAboutBusiness) y RATES cuando la quote requiere
filings — desde que R-002 responde Yes al radio 'Are state or federal
filings required?' (Diana 2026-07-06). Observado live 2026-07-31: PANTHER
CA117638002, ALTIMO CA117637552 y G&E CA117642658 morían esperando el
premium de RATES parados en esta página (progressive_rates_no_premium.png
mostraba este interstitial, no RATES).

Criterio R-002/R-087 (Diana 2026-08-04):
  - Radio "Will this quote include all the customer's commercially owned and
    operated vehicles?" -> Yes. Progressive solo emite filings sobre pólizas
    con TODOS los vehículos comerciales del cliente; con No aparece el
    warning amarillo y el filing no se emite (G&E quedó trabado así).
  - Checkboxes de 'Filings Needed': si los 3 vienen pre-marcados (= ambos
    permisos activos según SAFER) se dejan los 3. Si no: radio ≤500 millas
    -> ESTATAL (solo State); >500 millas -> FEDERAL (Federal Liability +
    MCS-90, "los dos primeros"). Sin dato de radio -> se deja lo pre-marcado.
  - Authority Number NO se llena (no es exigencia en Progressive).
"""

from typing import Dict, List, Optional

from modules import decision_ledger
from modules.progressive.pages.base_page import BasePage

_PAGE = "Filing/Proof of Insurance"

_FEDERAL = ("Federal Liability Filing", "MCS-90")
_STATE = "State"


def filing_selection(premarked, radius_over_500) -> Optional[Dict[str, bool]]:
    """Matriz pura del criterio de Diana (2026-08-04).

    Devuelve None cuando hay que DEJAR los checkboxes como están (los 3
    pre-marcados = ambos permisos activos; o sin dato de radio), o un dict
    label -> estado deseado.
    """
    if set(premarked) >= set(_FEDERAL) | {_STATE}:
        return None  # ambos permisos activos: se dejan los 3
    if radius_over_500 is None:
        return None  # sin dato de radio: no afirmar nada
    want = {label: bool(radius_over_500) for label in _FEDERAL}
    want[_STATE] = not radius_over_500
    return want


class FilingProofPage(BasePage):
    """Interstitial de filings. Uso: `if await p.is_present(): await p.complete()`."""

    _HEADING = "Filing/Proof of Insurance"
    _ALL_VEHICLES_RADIO = "Will this quote include all the customer"
    _KNOWN_FILINGS = ("Federal Liability Filing", "MCS-90", "State")

    def __init__(self, page):
        super().__init__(page)
        self.warnings: List[str] = []

    async def is_present(self, *, wait_ms: int = 4_000) -> bool:
        heading = self.page.get_by_text(self._HEADING, exact=False)
        return await self.field_exists(heading, wait_ms=wait_ms)

    async def complete(self, *, radius_over_500: Optional[bool] = None) -> None:
        token = await self.current_page_token()
        print(
            f"    [Progressive] Filing/Proof of Insurance interstitial "
            f"(pageName={token or '?'})"
        )
        await self.remove_overlays()

        group = await self.find_radiogroup(self._ALL_VEHICLES_RADIO)
        if await self.field_exists(group, wait_ms=2_000):
            decision_ledger.record(
                "Include all commercially owned/operated vehicles?", "Yes",
                page=_PAGE, options=["Yes", "No"], source="RULE",
                rule_id="R-087",
                note="los filings solo se emiten con todos los vehículos "
                     "comerciales en la póliza")
            await self.safe_radio(group, "Yes")
        else:
            self._log_skipped("include_all_vehicles", "radio not rendered")

        premarked = await self._premarked_filings()
        await self._apply_filing_selection(premarked, radius_over_500)

        from modules.progressive.pages._exceptions import ContinueStuckError
        try:
            await self.safe_click_continue(
                expect_url_changes_from=token or "pageName="
            )
        except ContinueStuckError:
            # Si el interstitial comparte pageName con la página siguiente, el
            # token no cambia aunque la página sí avanzó — verificar por heading.
            if await self.is_present(wait_ms=1_000):
                raise
            print(
                "    [Progressive] filing_proof: URL token unchanged but the "
                "page advanced (heading gone)"
            )

    async def _apply_filing_selection(
        self, premarked: List[str], radius_over_500: Optional[bool]
    ) -> None:
        """Aplica el criterio R-002 sobre los checkboxes de Filings Needed."""
        want = filing_selection(premarked, radius_over_500)
        if want is None:
            if set(premarked) >= set(_FEDERAL) | {_STATE}:
                note = ("ambos permisos activos (los 3 pre-marcados por "
                        "SAFER) → se dejan los 3")
                source = "RULE"
            else:
                note = ("sin dato de radio → se dejan como Progressive los "
                        "pre-marca")
                source = "DEFAULT"
            decision_ledger.record(
                "Filings Needed", ", ".join(premarked) or "(ninguno)",
                page=_PAGE, source=source, rule_id="R-002", note=note)
            return

        applied = []
        for label, desired in want.items():
            cb = self.page.get_by_role("checkbox", name=label)
            if await cb.count() == 0:
                if desired:
                    self._log_skipped(f"filing_{label}", "checkbox not found")
                continue
            try:
                await self.safe_checkbox(cb.first, check=desired)
                if desired:
                    applied.append(label)
            except Exception as e:
                self._log_skipped(f"filing_{label}", e.__class__.__name__)
        rango = ">500 millas → federales (los 2 primeros)" if radius_over_500 \
            else "≤500 millas → estatal"
        decision_ledger.record(
            "Filings Needed", ", ".join(applied) or "(ninguno)",
            page=_PAGE, source="RULE", rule_id="R-002",
            note=f"radio {rango}; pre-marcados: "
                 f"{', '.join(premarked) or 'ninguno'}")
        print(f"    [Progressive] Filings Needed = {', '.join(applied) or '(ninguno)'} ({rango})")

    async def _premarked_filings(self) -> List[str]:
        """Solo lectura: qué checkboxes de 'Filings Needed' vienen marcados."""
        out: List[str] = []
        for label in self._KNOWN_FILINGS:
            cb = self.page.get_by_role("checkbox", name=label)
            try:
                if await cb.count() > 0 and await cb.first.is_checked():
                    out.append(label)
            except Exception:
                continue
        return out

    def _log_skipped(self, field: str, reason: str) -> None:
        msg = f"filing_proof: skipped '{field}' — {reason}"
        print(f"    [Progressive] {msg}")
        self.warnings.append(msg)
