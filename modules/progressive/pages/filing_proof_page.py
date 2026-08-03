"""Filing/Proof of Insurance page (interstitial CONDITIONAL).

Aparece entre BUSINESS (MoreAboutBusiness) y RATES cuando la quote requiere
filings — desde que R-002 responde Yes al radio 'Are state or federal
filings required?' (Diana 2026-07-06). Observado live 2026-07-31: PANTHER
CA117638002, ALTIMO CA117637552 y G&E CA117642658 morían esperando el
premium de RATES parados en esta página (progressive_rates_no_premium.png
mostraba este interstitial, no RATES).

MVP (R-087, EN-DUDA):
  - Radio "Will this quote include all the customer's commercially owned and
    operated vehicles?" -> Yes. Progressive solo emite filings sobre pólizas
    con TODOS los vehículos comerciales del cliente; con No aparece el
    warning amarillo y el filing no se emite (G&E quedó trabado así).
  - Los checkboxes de 'Filings Needed' y el bloque de state filing se dejan
    COMO PROGRESSIVE LOS PRE-MARCA (según SAFER). La elección State vs
    Federal por radio de operación (Diana 2026-08-03) queda EN-DUDA hasta
    validar el criterio exacto en sesión.
"""

from typing import List

from modules import decision_ledger
from modules.progressive.pages.base_page import BasePage

_PAGE = "Filing/Proof of Insurance"


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

    async def complete(self) -> None:
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
        decision_ledger.record(
            "Filings Needed", ", ".join(premarked) or "(ninguno pre-marcado)",
            page=_PAGE, source="DEFAULT", rule_id="R-087",
            note="se dejan como Progressive los pre-marca (SAFER); State vs "
                 "Federal según radio de operación pendiente con Diana")

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
