"""More About Business page (BUSINESS step).

URL: pageName=MoreAboutBusiness

REQUIRED fields:
  - currently_insured (Yes/No radio)
  - other_coverages (checkbox group: None of the above by default)

CONDITIONAL fields (may not render for some commodities — soft-skipped):
  - eld_required          (NOT rendered for Beverage Distributor)
  - federal_filings_required
  - snapshot_proview      (renders for Beverage Distributor, NOT for Trucker)

OPTIONAL fields:
  - customer_email
"""

from __future__ import annotations

from typing import List, Optional

from modules import decision_ledger
from modules.progressive.pages.base_page import BasePage

_PAGE = "More About Business"


class MoreBusinessPage(BasePage):
    """Progressive wizard - MoreAboutBusiness page (BUSINESS step)."""

    REQUIRED_FIELDS = ("currently_insured", "other_coverages")
    CONDITIONAL_FIELDS = ("eld_required", "federal_filings_required", "snapshot_proview")
    OPTIONAL_FIELDS = ("customer_email",)

    def __init__(self, page):
        super().__init__(page)
        self.warnings: List[str] = []

    async def fill_and_submit(
        self,
        currently_insured: bool = False,
        other_coverages: str = "None",
        eld_required: bool = False,
        customer_email: Optional[str] = None,
        federal_filings_required: bool = False,
        snapshot_proview: bool = False,
        has_general_liability: bool = False,
    ) -> None:
        await self.wait_for_extjs_idle()
        await self.remove_overlays()

        if customer_email:
            await self._fill_email(customer_email)

        await self._answer_currently_insured(currently_insured)
        await self._answer_other_coverages(other_coverages, has_general_liability)
        await self._answer_federal_filings_conditional(federal_filings_required)
        await self._answer_eld_required_conditional(eld_required)
        await self._answer_snapshot_proview_conditional(snapshot_proview)
        await self.safe_click_continue(expect_url_changes_from="MoreAboutBusiness")

    async def _fill_email(self, email: str) -> None:
        print(f"    [Progressive] Customer email: {email}")
        box = self.page.get_by_role("textbox", name="Customer Email Address")
        if await box.count() > 0:
            await self.safe_fill(box.first, email)
            decision_ledger.record("Customer Email Address", email,
                                   page=_PAGE, source="RULE",
                                   rule_id="R-003",
                                   note="owner_email del BlueQuote")

    async def _answer_currently_insured(self, is_insured: bool) -> None:
        answer = "Yes" if is_insured else "No"
        group = await self.find_radiogroup("Is the customer currently insured?")
        # Progressive sometimes RESOLVES this from the customer's prior-policy
        # records and renders it as static text (no interactive radio) — e.g.
        # JOSE DELGADO showed 'Yes' locked. Accept Progressive's value instead
        # of forcing our default and HALTing (its records are authoritative).
        if not await self.field_exists(group, wait_ms=2000):
            self._log_skipped("currently_insured", "pre-resolved by Progressive (static)")
            return
        print(f"    [Progressive] Currently insured: {answer}")
        decision_ledger.record("Is the customer currently insured?", answer,
                               page=_PAGE, options=["Yes", "No"],
                               source="DEFAULT", rule_id="R-040")
        try:
            await self.safe_radio(group, answer)
        except Exception as e:
            self._log_skipped(
                "currently_insured",
                f"radio locked to resolved value ({e.__class__.__name__})",
            )

    async def _answer_other_coverages(
        self, choice: str, has_general_liability: bool = False
    ) -> None:
        """Contesta la sección "Other Business Insurance" (descuentos).

        Estructura verificada live 2026-06-25 — DOS preguntas, cada una con sus
        propios checkboxes (Business Owners Policy / General Liability /
        [Workers' Compensation] / None of the above):
          Q1 = "Does the customer CURRENTLY HAVE any of the following...?"
          Q2 = "...purchase within 45 days WITH PROGRESSIVE...?"
        Los checkboxes están en orden de DOM (Q1 antes que Q2), así que para un
        label dado nth(0)=Q1 y nth(1)=Q2.

        Diana 2026-06-25 (#3/#9): si el cliente tiene GL → tildar
        "General Liability" en Q1 (descuento por cobertura vigente) y dejar
        "None of the above" en Q2 (no le vendemos pólizas extra por Progressive).
        Sin GL → "None of the above" en ambas (comportamiento previo).
        """
        async def _tick(label: str, which) -> None:
            cbs = self.page.get_by_role("checkbox", name=label, exact=True)
            n = await cbs.count()
            idxs = range(n) if which == "all" else [which] if which < n else []
            for i in idxs:
                try:
                    await self.safe_checkbox(cbs.nth(i), check=True)
                    print(f"    [Progressive] Other coverages: ticked '{label}' [q{i + 1}]")
                except Exception as e:
                    print(f"    [Progressive] WARN: checkbox '{label}'[{i}]: {e}")

        if has_general_liability and choice in ("None", None, ""):
            print("    [Progressive] Other coverages: GL solicitado → 'General "
                  "Liability' en Q1, 'None of the above' en Q2")
            await _tick("General Liability", 0)        # Q1: tiene GL vigente
            decision_ledger.record(
                "Other Business Insurance Q1 (coberturas vigentes)",
                "General Liability", page="Other Business Insurance",
                source="RULE", rule_id="R-007")
            await _tick("None of the above", 1)        # Q2: nada por Progressive
            decision_ledger.record(
                "Other Business Insurance Q2 (comprar con Progressive)",
                "None of the above", page="Other Business Insurance",
                source="RULE", rule_id="R-042")
            return

        # Sin GL (o un coverage explícito): comportamiento previo.
        label = "None of the above" if choice in ("None", None, "") else choice
        print(f"    [Progressive] Other coverages: {choice} → '{label}' (todas)")
        await _tick(label, "all")
        decision_ledger.record(
            "Other Business Insurance Q1+Q2 (sin GL en el BlueQuote)", label,
            page="Other Business Insurance", source="RULE", rule_id="R-042")

    async def _answer_federal_filings_conditional(self, required: bool) -> None:
        answer = "Yes" if required else "No"
        group = await self.find_radiogroup("Are state or federal filings required?", timeout_ms=2000)
        if not await self.field_exists(group, wait_ms=1000):
            self._log_skipped("federal_filings_required", "field_not_rendered")
            return
        print(f"    [Progressive] Federal/state filings required: {answer}")
        decision_ledger.record("Are state or federal filings required?",
                               answer, page=_PAGE, options=["Yes", "No"],
                               source="RULE", rule_id="R-002")
        await self.safe_radio(group, answer)

    async def _answer_eld_required_conditional(self, required: bool) -> None:
        answer = "Yes" if required else "No"
        group = await self.find_radiogroup(
            "Is an Electronic Logging Device (ELD) required",
            timeout_ms=2000,
        )
        if not await self.field_exists(group, wait_ms=1000):
            self._log_skipped("eld_required", "field_not_rendered_for_this_commodity")
            return
        print(f"    [Progressive] ELD required: {answer}")
        decision_ledger.record(
            "Is an Electronic Logging Device (ELD) required?", answer,
            page=_PAGE, options=["Yes", "No"], source="DEFAULT",
            rule_id="R-041")
        await self.safe_radio(group, answer)

    async def _answer_snapshot_proview_conditional(self, accept: bool = False) -> None:
        """Answer the Snapshot ProView enrollment radio — defaults to No.

        This question ("The customer is eligible for additional savings of 20%...")
        renders for Beverage Distributor commodities but NOT for Trucker.
        The bot declines by default: enrolling the customer in a telematics
        hardware programme requires explicit customer consent.
        """
        answer = "Yes" if accept else "No"
        group = await self.find_radiogroup(
            "The customer is eligible for additional savings",
            timeout_ms=2000,
        )
        if not await self.field_exists(group, wait_ms=1000):
            self._log_skipped("snapshot_proview", "field_not_rendered_for_this_commodity")
            return
        print(f"    [Progressive] Snapshot ProView (accept): {answer}")
        decision_ledger.record("Snapshot ProView (telemática, -20%)", answer,
                               page=_PAGE, options=["Yes", "No"],
                               source="RULE", rule_id="R-046",
                               note="enrolar requiere consentimiento del cliente")
        await self.safe_radio(group, answer)

    def _log_skipped(self, field: str, reason: str) -> None:
        msg = f"more_business: skipped '{field}' — {reason}"
        print(f"    [Progressive] {msg}")
        self.warnings.append(msg)
