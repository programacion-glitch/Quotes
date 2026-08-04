"""
Business Info Page Object for Progressive wizard.

First page of the quote wizard after "Add Products to Quote".
URL: clpolicy.foragentsonly.com/Express/Default.aspx?pageName=BusinessOwnerInfo

All selectors VALIDATED LIVE on 2026-04-09 using USDOT 2998569 (M&D CUSTOM FREIGHT LLC).
"""

from typing import Optional

from modules import decision_ledger
from modules.progressive.pages.base_page import BasePage
from modules.progressive.field_mapper import MappedFields
from modules.progressive.choice_resolver import resolve_choice, Resolution
from modules.progressive.mappings import map_commodity, subtype_from_unit_hints
from modules.progressive.business_type_classifier import (
    resolve_commodity_to_business_type,
    unit_type_hints,
)
from modules.progressive.catalogs import load_catalog
from modules.progressive.pages._exceptions import (
    UnmappableValueError,
    FieldNotFoundError,
)



# Quick-access business type buttons that appear on the page
_PAGE = "START (BusinessOwnerInfo)"

QUICK_TYPE_BUTTONS = [
    "Contractor",
    "Dirt, Sand and Gravel",
    "Landscaper",
    "Towing",
    "Trucker",
]

# Sub-type options that appear when "Trucker" is selected
# (Values confirmed from the combobox "Type of Trucker")
TRUCKER_SUBTYPES = [
    "Agricultural",
    "Auto Hauler",
    "Coal",
    "Containers",
    "Debris Removal",
    "Dirt, Sand and Gravel",
    "Escort Vehicles",
    "Expediters",
    "Fracking, Sand or Water",
    "Freight Forwarder",
    "Garbage & Trash",
    "General Freight / Other",
    "Hazardous Materials / Placards",
    "Hotshot Transport",
    "Household Goods Mover",
    "Livestock",
    "Logging / Wood Chips",
    "Machinery & Heavy Equipment",
    "Mobile Home Toter",
    "Oilfield Materials",
    "Refrigerated Goods",
]


class BusinessInfoPage(BasePage):
    """Progressive wizard - BusinessOwnerInfo page.

    Flow:
      1. Currently insured with Progressive? -> No
      2. USDOT Yes/No/NotYet -> Yes
      3. Fill USDOT Number
      4. Click "Verify" (required before submit)
      5. "Does this USDOT belong to customer?" -> Yes
      6. Entity type (Individual / Partnership / Corporation or LLC)
      7. Business Name (and DBA if Individual)
      8. Business Type (quick button or combobox) -> may open sub-type dropdown
      9. Hazmat placard Yes/No (appears for Trucker)
     10. Owner First/Last/Address/ZIP/City/DOB
     11. Click "Ok, start quote."
    """

    REQUIRED_FIELDS = (
        "business_name",
        "address_line1", "city", "state", "zip",
        "phone",
        "owner_first_name", "owner_last_name", "owner_dob",
        "commodity", "radius",
    )
    CONDITIONAL_FIELDS = (
        "owns_goods",               # only renders for some commodities (distributors)
        "different_business_name",  # only when user picks "Enter a different" radio
        "owner_phone",              # may be marked required by commodity
    )
    OPTIONAL_FIELDS = ("customer_email",)

    def __init__(self, page):
        super().__init__(page)
        self.warnings: list[str] = []

    def _log_skipped(self, field: str, reason: str) -> None:
        msg = f"business_info: skipped '{field}' — {reason}"
        print(f"    [Progressive] {msg}")
        self.warnings.append(msg)

    async def fill_and_submit(self, fields: MappedFields) -> None:
        """Fill the entire BusinessOwnerInfo page and submit.

        If `fields.effective_date` is supplied, sets the policy start date.
        """
        await self.page.wait_for_load_state("networkidle", timeout=30_000)
        await self.remove_overlays()

        # Unit types (e.g. 'Refrigerated Trailer') enrich the commodity -> Business
        # Type classification so the chosen business type yields a tile set that
        # actually contains the quote's trailers (see resolve_business_type).
        self._unit_hints = unit_type_hints(fields.vehicles)

        if fields.effective_date:
            await self._set_effective_date(fields.effective_date)

        await self._answer_currently_insured(False)
        await self._answer_has_usdot(bool(fields.usdot))

        if fields.usdot:
            await self._fill_usdot_number(fields.usdot)
            await self._click_verify_usdot()
            await self._confirm_usdot_belongs_to_customer(True)
            # If SAFER returned 'USDOT information was not found', Progressive
            # reveals a follow-up Y/N: "Did the customer obtain their USDOT
            # Number within the last 60 days?". Soft-skipped when not shown.
            # Diana 2026-07-06: este radio SOLO aparece cuando el USDOT no se
            # encontró en SAFER — o sea es un DOT nuevo/reciente → la respuesta
            # correcta es Yes (obtenido en los últimos 60 días). Con No se cotiza
            # mal y afecta el filing de la prueba de seguro.
            await self._answer_usdot_recently_obtained(recently_obtained=True)

        await self._select_entity_type(fields.entity_type)
        await self._fill_business_name(fields.business_name, fields.dba_name)
        await self._select_business_type(fields.commodity)
        await self._answer_type_of_trucker(fields.commodity)  # conditional: revealed when business=Trucker
        await self._answer_hazmat_placard(False)  # default No
        await self._fill_owner_info(
            fields.owner_name,
            street=fields.owner_street,
            zip_code=fields.owner_zip,
            city=fields.owner_city,
            dob=fields.owner_dob,
        )
        # Phone: marked "Optional" on the form but improves rating accuracy.
        # owner_phone may not be on MappedFields yet — use getattr fallback.
        await self._fill_primary_phone(getattr(fields, "owner_phone", None))
        # Conditional required question for trucking/dirt-sand-gravel classes.
        await self._answer_oil_gas_fields(False)
        # "Does the customer own the goods he or she is transporting?" —
        # appears for distributor-type commodities (Beverage, Food, etc.).
        # Default Yes (most owner-operated trucking owns its cargo).
        await self._answer_owns_goods(True)
        await self._click_start_quote()

    async def _set_effective_date(self, date_str: str) -> None:
        """Set the policy effective date (mm/dd/yyyy)."""
        print(f"    [Progressive] Effective date: {date_str}")
        combo = await self.find_combo(
            "When should this Progressive Commercial Auto policy start?"
        )
        if await combo.count() > 0:
            # verify=False: date field reformats (e.g. "6/1/2026" -> "06/01/2026")
            await self.safe_fill(combo.first, date_str, verify=False)

    # ---- Individual step helpers ----

    async def _answer_currently_insured(self, is_insured: bool) -> None:
        """Answer 'Is the customer currently insured with Progressive Commercial Auto?'"""
        answer = "Yes" if is_insured else "No"
        print(f"    [Progressive] Currently insured with Progressive: {answer}")
        decision_ledger.record(
            "Is the customer currently insured with Progressive Commercial Auto?",
            answer, page=_PAGE, options=["Yes", "No"], source="DEFAULT",
            rule_id="R-008")
        group = await self.find_radiogroup(
            "Is the customer currently insured with Progressive Commercial Auto?"
        )
        await self.safe_radio(group, answer)

    async def _answer_has_usdot(self, has_usdot: bool) -> None:
        """
        Answer 'Does the customer have a USDOT Number?'
        Three options validated:
          - "Yes - the customer has a USDOT number"
          - "No - and the customer will not have a USDOT number"
          - "Not Yet - but the customer has applied/will apply for a USDOT number within 60 days"
        """
        if has_usdot:
            label = "Yes - the customer has a USDOT number"
        else:
            label = "No - and the customer will not have a USDOT number"
        print(f"    [Progressive] Has USDOT: {'Yes' if has_usdot else 'No'}")
        group = await self.find_radiogroup("Does the customer have a USDOT Number?")
        # safe_radio uses exact=True; the option labels are long strings so pass the full label
        radio = group.get_by_role("radio", name=label)
        await radio.click(timeout=5_000)
        await self.settle_extjs()

    async def _fill_usdot_number(self, usdot: str) -> None:
        """Fill the USDOT Number input that appears after choosing Yes."""
        print(f"    [Progressive] Filling USDOT: {usdot}")
        # Label: "USDOT Number associated with the customer's business:"
        box = self.page.get_by_role(
            "textbox",
            name="USDOT Number associated with the customer's business:",
        )
        await box.wait_for(state="visible", timeout=10_000)
        # verify=False: USDOT is a numeric field that triggers SAFER lookup on
        # Tab; input_value after Tab may show lookup state, not the typed value.
        await self.safe_fill(box, usdot, verify=False)

    async def _click_verify_usdot(self) -> None:
        """
        Click the 'Verify' button next to USDOT.
        CRITICAL: without this click, the page will reject submission with
        'Please use the Verify USDOT button to verify your USDOT Number.'
        """
        print("    [Progressive] Clicking Verify USDOT...")
        btn = self.page.get_by_role("button", name="Verify USDOT")
        if await btn.count() == 0:
            # Fallback: label may just be "Verify"
            btn = self.page.locator("span.g-btn-text", has_text="Verify").first
        await btn.click(timeout=10_000, force=True)
        # SAFER lookup: wait for a POST-VERIFY signal in the DOM rather than
        # a flat sleep or ajax-idle — the response lands OUTSIDE Ext.Ajax
        # (live DIBOLL 2026-06-10: an idle-based wait under-waited, the
        # 'belongs to customer' radio appeared late and was skipped as
        # auto-confirmed). Signals cover found / not-found / invalid.
        try:
            await self.page.wait_for_function(
                """() => {
                    const t = document.body.innerText || '';
                    return t.includes('USDOT Assigned to') ||
                           t.includes('belong to the customer') ||
                           t.includes('obtain their USDOT Number') ||
                           t.includes('USDOT information was not found') ||
                           t.includes('not a valid USDOT');
                }""",
                timeout=12_000,
            )
        except Exception:
            pass
        await self.page.wait_for_timeout(300)

    async def _answer_usdot_recently_obtained(self, recently_obtained: bool = False) -> None:
        """
        Handles the conditional radio that appears ONLY when Progressive's
        SAFER lookup says 'USDOT information was not found' (typical for
        DOTs registered very recently or in a state SAFER hasn't synced):

          'Did the customer obtain their USDOT Number within the last 60 days?'

        Este radio SOLO se renderiza cuando SAFER NO encontró el USDOT (típico de
        DOTs registrados hace muy poco). Por eso el caller pasa Yes: si el campo
        aparece, el DOT es nuevo/reciente → se obtuvo en los últimos 60 días
        (Diana 2026-07-06; antes iba No y cotizaba mal). Soft-skips si el radio no
        se renderiza (USDOT encontrado en SAFER).
        """
        try:
            await self.wait_for_extjs_idle(timeout_ms=3_000)
        except Exception:
            pass
        group = await self.find_radiogroup(
            "Did the customer obtain their USDOT Number within the last 60 days",
            timeout_ms=2_000,
        )
        if not await self.field_exists(group, wait_ms=1_500):
            # USDOT was found in SAFER — this conditional doesn't apply
            return
        answer = "Yes" if recently_obtained else "No"
        print(f"    [Progressive] USDOT obtained in last 60 days: {answer}")
        decision_ledger.record(
            "Did the customer obtain their USDOT within the last 60 days?",
            answer, page=_PAGE, options=["Yes", "No"], source="RULE",
            rule_id="R-009",
            note="el radio solo aparece si SAFER no encontró el USDOT")
        await self.safe_radio(group, answer)

    async def _confirm_usdot_belongs_to_customer(self, confirm: bool) -> None:
        """
        After Verify, Progressive USUALLY asks: 'Does this USDOT Number
        belong to the customer's business?' — answer Yes to continue.

        CONDITIONAL: Progressive sometimes auto-confirms (when the USDOT is
        already trusted from prior quotes by the same agent / recently
        verified) and skips this question entirely. Use field_exists to
        soft-skip with a log instead of raising RadioStuckError.

        Also waits a bit longer for the SAFER lookup + render — the 3s wait
        in _click_verify_usdot is not always enough on slow connections.
        """
        # Give SAFER + ExtJS more time to render the follow-up radio
        try:
            await self.wait_for_extjs_idle(timeout_ms=5_000)
        except Exception:
            pass

        answer = "Yes" if confirm else "No"
        group = await self.find_radiogroup(
            "Does this USDOT Number belong to the customer's business?",
            timeout_ms=3_000,
        )
        if not await self.field_exists(group, wait_ms=1_500):
            print(
                "    [Progressive] USDOT 'belongs to customer' radio not shown "
                "(likely auto-confirmed by Progressive); skipped"
            )
            self._log_skipped(
                "usdot_belongs_to_customer",
                "field_not_rendered_likely_auto_confirmed",
            )
            return
        print(f"    [Progressive] USDOT belongs to customer: {answer}")
        decision_ledger.record(
            "Does this USDOT Number belong to the customer's business?",
            answer, page=_PAGE, options=["Yes", "No"], source="RULE",
            rule_id="R-010")
        await self.safe_radio(group, answer)

    async def _select_entity_type(self, entity_type: str) -> None:
        """
        Select business structure. Three radio options:
          - "Individual / Sole Proprietor"
          - "Partnership"
          - "Corporation or LLC / Non-Profit"
        """
        et_upper = (entity_type or "").upper()
        if "LLC" in et_upper or "CORP" in et_upper:
            label = "Corporation or LLC / Non-Profit"
        elif "PARTNER" in et_upper:
            label = "Partnership"
        else:
            label = "Individual / Sole Proprietor"

        print(f"    [Progressive] Selecting entity type: {label}")
        group = await self.find_radiogroup(
            "How is the customer's business structured?"
        )
        await self.safe_radio(group, label)

    async def _fill_business_name(
        self, name: Optional[str], dba: Optional[str] = None
    ) -> None:
        """Fill Business Name (LLC/Corp) and DBA (Individual).

        Progressive renders Business Name as a RADIO with two options:
          1. The SAFER-resolved name (from USDOT lookup) — preferred when present
          2. "Enter a different Business Name" → reveals a textbox

        Robustness (live 2026-06-01 with RYD LLC):
          - exact match first; fall through to non-exact only if not found
          - verify the radio actually became checked; if not, force the
            "Enter a different Business Name" path so the textbox gets filled
          - always check the textbox at the end: even after a successful
            SAFER radio click, if the page also still expects the textbox
            (some flows do), fill it as a belt-and-suspenders
        """
        if not name:
            return
        print(f"    [Progressive] Setting business name: {name}")
        await self.page.wait_for_timeout(200)

        # SAFER's pre-suggested radio is unreliable: even when its accessible
        # name matches the blue-quote name exactly, the click sometimes does
        # not stick, and partial-match attempts can pick the wrong radio.
        # Always use the "Enter a different Business Name" path — we have the
        # name from the blue quote, so it's deterministic and bypasses SAFER's
        # variability entirely.
        # Strategy: try SAFER's pre-suggested radio first. Its accessible name
        # is usually the business name (e.g. "RYD LLC"), but Progressive's
        # ExtJS sometimes prepends extra characters or wraps it in a way that
        # breaks exact match — so try exact, then non-exact filtered to
        # exclude the "Enter a different" radio.
        safer_radio = None
        exact = self.page.get_by_role("radio", name=name, exact=True)
        if await exact.count() > 0:
            safer_radio = exact.first
        else:
            non_exact = self.page.get_by_role("radio", name=name, exact=False)
            total = await non_exact.count()
            for i in range(total):
                cand = non_exact.nth(i)
                try:
                    accessible = await cand.get_attribute("aria-label") or ""
                except Exception:
                    accessible = ""
                if "different" in accessible.lower():
                    continue
                safer_radio = cand
                break

        if safer_radio is not None:
            click_strategies = [
                ("normal click", lambda r=safer_radio: r.click(timeout=3_000)),
                ("force click",  lambda r=safer_radio: r.click(force=True, timeout=3_000)),
                ("check()",      lambda r=safer_radio: r.check(timeout=3_000, force=True)),
            ]
            for label, do_click in click_strategies:
                try:
                    await do_click()
                    await self.settle_extjs()
                    if await safer_radio.is_checked():
                        print(f"    [Progressive] Selected SAFER radio ({label}): {name!r}")
                        if dba:
                            await self._fill_placeholder("DBA Name", dba)
                        return
                    print(f"    [Progressive] SAFER {label} did not stick, trying next")
                except Exception as e:
                    print(f"    [Progressive] SAFER {label} failed: {e}")
                    continue
        else:
            print(f"    [Progressive] No SAFER radio matched name={name!r}")

        # Fallback: 'Enter a different Business Name' radio reveals a textbox.
        print(f"    [Progressive] SAFER radio not usable; using 'Enter a different Business Name'")
        diff_radio = self.page.get_by_role(
            "radio", name="Enter a different Business Name"
        )
        # NOTE: try natural click first (auto-scrolls + verifies actionability).
        # force=True paradoxically bypasses auto-scroll and fails with
        # "outside viewport" on long START forms. Fall back to scroll+force
        # only if natural click rejects.
        try:
            await diff_radio.first.scroll_into_view_if_needed(timeout=2_000)
            await diff_radio.first.click(timeout=5_000)
        except Exception as e:
            print(f"    [Progressive] 'Enter a different' natural click rejected: {e}; retrying with force=True")
            try:
                await diff_radio.first.click(timeout=3_000, force=True)
            except Exception as e2:
                print(f"    [Progressive] WARN: 'Enter a different' radio click failed: {e2}")
        # The revealed textbox renders after the radio's ajax commit.
        await self.settle_extjs(start_ms=300)

        # The textbox is the next <input type="text"> in DOM order AFTER the
        # 'Enter a different Business Name' radio. XPath traversal from the
        # radio locator is the most robust — independent of placeholder
        # rendering or aria attributes. Fall back to role/label/placeholder.
        candidates = [
            diff_radio.locator("xpath=following::input[@type='text'][1]"),
            self.page.locator(
                'input[aria-required="true"][placeholder="Business Name"]'
            ),
            self.page.get_by_role("textbox", name="Business Name", exact=True),
            self.page.get_by_label("Business Name", exact=True),
            self.page.get_by_placeholder("Business Name", exact=True),
        ]
        filled = False
        for loc in candidates:
            try:
                await loc.first.wait_for(state="visible", timeout=3_000)
                # Use safe_fill with verify=False: the field value is
                # uppercased by ExtJS after blur, so exact case match would
                # fail.  We check manually below to preserve the existing
                # uppercased comparison.
                await self.safe_fill(loc.first, name, verify=False)
                actual = ""
                try:
                    actual = (await loc.first.input_value()).strip()
                except Exception:
                    pass
                if actual.upper() == name.strip().upper():
                    print(f"    [Progressive] Business Name = {actual!r}")
                    filled = True
                    break
            except Exception:
                continue

        if not filled:
            self._log_skipped(
                "different_business_name",
                "no selector matched for the revealed textbox",
            )

        if dba:
            dba_box = self.page.get_by_role(
                "textbox", name="DBA Name (Optional)"
            )
            if await dba_box.count() > 0:
                await self.safe_fill(dba_box.first, dba, verify=False)

    def resolve_business_type(self, commodity: Optional[str]) -> Resolution:
        """Resolve commodity -> Business type option, or HALT (no silent Trucker).

        table hit -> MATCHED ('mapping'/'generic'). table miss -> AI classifier
        against Progressive's live trucking taxonomy ('ai'), enriched with the
        quote's unit types. still nothing -> UnmappableValueError (fail-loud).
        See business_type_classifier.
        """
        label, note = resolve_commodity_to_business_type(
            commodity, unit_hints=getattr(self, "_unit_hints", None)
        )
        if label is not None:
            return Resolution("Business type", label, "MATCHED", commodity, note)
        cat = load_catalog("business_type")
        raise UnmappableValueError(
            field="Business type",
            source_value=commodity,
            available_options=list(cat.options),
        )

    async def _select_business_type(self, commodity: Optional[str]) -> None:
        """Select the business type via the 'Business type list' combobox.

        Resolves the commodity up front — raises UnmappableValueError (HALT) for
        a present-but-unmappable commodity instead of silently selecting 'Trucker'.
        """
        if not commodity:
            print("    [Progressive] WARN: no commodity provided, skipping")
            return
        res = self.resolve_business_type(commodity)
        print(f"    [Progressive] Business type: '{commodity}' -> '{res.value}' ({res.note})")
        # resolve_business_type NO pasa por resolve_choice (arma la Resolution
        # a mano), así que el ledger se alimenta acá. El fallback por trailer
        # es regla de negocio validada (Diana 2026-08-04), no un default.
        src = "RULE" if res.note.startswith("trailer-fallback") else res.kind
        decision_ledger.record("Business type", res.value, page=_PAGE,
                               source=src, rule_id="R-013",
                               note=f"commodity={commodity!r} ({res.note})")
        combo = await self.find_combo("Business type list")
        await combo.wait_for(state="visible", timeout=15_000)
        await self.safe_select_combo(combo, res.value)

    # Section headers in Progressive's Type-of-Trucker dropdown — render in
    # the options list but are NOT selectable (clicking them does nothing).
    _TYPE_OF_TRUCKER_HEADERS = frozenset({"Most common types", "All types"})

    # Catch-all option for Trucker quotes that arrived here via the unmapped
    # commodity → Trucker fallback (mixed or unclassifiable freight). Sits in
    # Progressive's "Most common types" section; matches the underwriting
    # intent of "any general commercial trucking that doesn't fit a specific
    # specialty category".
    _TYPE_OF_TRUCKER_DEFAULT = "General Freight / Other"

    async def _answer_type_of_trucker(self, commodity: Optional[str]) -> None:
        """Conditional combobox revealed when business type = Trucker. Resolve the
        commodity to a subtype; HALT if present-but-unmatched (was: silently click
        the first non-empty option). 'General Freight / Other' is used only as the
        generic catch-all (commodity absent or generic)."""
        # The "Type of Trucker" subtype combo is revealed (asynchronously, by
        # ExtJS) ONLY when the business type resolved to the generic "Trucker".
        # For that case it is a REQUIRED field, so we must wait for it to render
        # and fail loud if it never does — never silently skip (a 1.5s probe used
        # to return early under live latency, leaving the field unanswered and
        # tripping "Type of Trucker: This field is required" at Continue).
        is_trucker = self.resolve_business_type(commodity).value == "Trucker"

        # Give ExtJS time to render the conditional after Trucker is committed.
        try:
            await self.wait_for_extjs_idle(timeout_ms=4_000)
        except Exception:
            pass
        # let ExtJS finish rendering the conditional dropdown before enumerating options
        await self.page.wait_for_timeout(200)

        combo = await self.find_combo("Type of Trucker")
        # Required-field case (Trucker) polls generously; conditional case
        # (non-Trucker business type) keeps the short probe-and-skip.
        reveal_wait_ms = 12_000 if is_trucker else 1_500
        if not await self.field_exists(combo, wait_ms=reveal_wait_ms):
            if is_trucker:
                screenshot = await self.screenshot("type_of_trucker_missing")
                raise FieldNotFoundError(
                    "Business type resolved to 'Trucker' but the required "
                    "'Type of Trucker' combobox never rendered within "
                    f"{reveal_wait_ms}ms.",
                    primitive="find_combo",
                    field="Type of Trucker",
                    attempts=1,
                    screenshot_path=screenshot,
                )
            return  # Not revealed when business type is not Trucker

        await combo.click(timeout=5_000)
        await self.wait_for_options_open()
        raw = await self.page.get_by_role("option").all_inner_texts()
        options = [o.strip() for o in raw
                   if o.strip() and o.strip() not in self._TYPE_OF_TRUCKER_HEADERS]
        # This conditional only appears when the business type resolved to the
        # generic "Trucker" (commodity absent / mixed / sentinel), so the raw
        # commodity here is NOT a specific freight subtype — a mixed string like
        # "Processed wood 33%, pipes 33%, Building Materials 34%" must NOT be
        # matched against the subtype list. Treat a generic commodity as absent
        # so the catch-all default ("General Freight / Other") is selected
        # instead of HALTing. (Confirmed live: JUAREZ LOGISTICS, mixed load.)
        _, is_generic = map_commodity(commodity)
        source = None if (is_generic or not (commodity or "").strip()) else commodity
        screenshot = await self.screenshot("type_of_trucker_options")

        # R-015 (Diana 2026-08-04, mapping completo): prioridad de resolución
        #   1. commodity específico con match directo contra las opciones
        #   2. señal de la UNIDAD (reefer/dry van/flatbed/auto hauler/tank/
        #      cement -> subtipo; dump -> S&G o Scrap según el commodity)
        #   3. catch-all DEFAULTED 'General Freight / Other'
        # Antes, un commodity específico sin match (PACKED CHARCOAL) moría en
        # HALT aunque el trailer diera la clasificación.
        hint_label, hint_src = subtype_from_unit_hints(
            getattr(self, "_unit_hints", None), commodity=commodity
        )
        value = None
        if source is not None:
            try:
                res = resolve_choice(
                    "Type of Trucker", source, options,
                    generic_aliases=frozenset({"general freight", "mixed", "other", "trucker"}),
                    screenshot_path=screenshot,
                )
                value = res.value
                print(f"    [Progressive] Type of Trucker = {value!r} ({res.note})")
            except UnmappableValueError:
                value = None  # commodity sin match: decide la unidad
        if value is None and hint_label:
            resolved = self._find_option(hint_label, options)
            if resolved:
                value = resolved
                decision_ledger.record(
                    "Type of Trucker", value, page=_PAGE, options=options,
                    source="RULE", rule_id="R-015",
                    note=f"según operación ({hint_src})")
                print(f"    [Progressive] Type of Trucker = {value!r} (operación: {hint_src})")
            else:
                print(f"    [Progressive] WARN: subtipo {hint_label!r} (operación "
                      f"{hint_src}) no está entre las opciones de la página")
        if value is None:
            res = resolve_choice(
                "Type of Trucker", None, options,
                default=self._TYPE_OF_TRUCKER_DEFAULT,
                screenshot_path=screenshot,
            )
            value = res.value
            print(f"    [Progressive] Type of Trucker = {value!r} ({res.note})")
        await self.page.get_by_role("option", name=value, exact=True).first.click(timeout=5_000)
        await self.settle_extjs()

    @staticmethod
    def _find_option(label: str, options) -> Optional[str]:
        """Match tolerante de un subtipo contra las opciones vivas de la
        página: exacto normalizado, o todos los tokens del label presentes
        en la opción ('Other for hire' -> 'Other For-Hire Trucking')."""
        norm = {o.strip().lower(): o for o in options}
        key = label.strip().lower()
        if key in norm:
            return norm[key]
        toks = [t for t in key.replace(",", " ").split() if t]
        for o in options:
            ol = o.lower()
            if all(t in ol for t in toks):
                return o
        return None

    async def _answer_hazmat_placard(self, has_placard: bool) -> None:
        """
        After business type, Progressive asks (for Trucker):
        'Do any listed vehicles or the load require a hazardous material placard?'
        """
        group = await self.find_radiogroup(
            "Do any listed vehicles or the load require a hazardous material placard?"
        )
        # 4s window: the question renders AFTER the Type-of-Trucker repaint and
        # intermittently outlasted the old 1.5s check (live LQZ re-run
        # 2026-06-10: silent skip -> START blocked on the unanswered group).
        if not await self.field_exists(group, wait_ms=4_000):
            return  # Question didn't appear (not all types trigger it)

        answer = "Yes" if has_placard else "No"
        print(f"    [Progressive] Hazmat placard: {answer}")
        decision_ledger.record(
            "Do any listed vehicles or the load require a hazmat placard?",
            answer, page=_PAGE, options=["Yes", "No"], source="DEFAULT",
            rule_id="R-016")
        await self.safe_radio(group, answer)

    async def _fill_owner_info(
        self,
        owner_name: Optional[str],
        street: Optional[str] = None,
        zip_code: Optional[str] = None,
        city: Optional[str] = None,
        dob: Optional[str] = None,
    ) -> None:
        """Fill First/Last name, Street Address, ZIP, City, DOB."""
        if not owner_name:
            print("    [Progressive] WARN: no owner name provided")
            return
        print(f"    [Progressive] Setting owner: {owner_name}")

        parts = owner_name.strip().split()
        # Generational suffixes go in Progressive's separate Suffix combo, and
        # the trailing period in 'SR.' fails the Last Name charset validation
        # (letters/numbers/hyphen/apostrophe only — live ALPHA 2026-06-10).
        # Dropping the suffix is safe: it isn't material to rating.
        _SUFFIXES = {"SR", "JR", "II", "III", "IV", "V"}
        while len(parts) > 2 and parts[-1].rstrip(".").upper() in _SUFFIXES:
            parts = parts[:-1]
        first_name = parts[0] if parts else ""
        last_name = " ".join(parts[1:]) if len(parts) > 1 else ""
        # Progressive's charset validation also rejects stray periods
        # (e.g. middle initials like 'E.').
        last_name = last_name.replace(".", "").strip()

        await self._fill_owner_name_field("First Name", first_name)
        await self._fill_owner_name_field("Last Name", last_name)

        # Home Address: Progressive renders this as a RADIO when SAFER returned
        # an address (e.g. for USDOT-verified businesses).
        # Try SAFER radio first if street is provided AND matches; else click "Enter a different address"
        if street:
            print(f"    [Progressive] Street address: {street}")
            # Prefer the SAFER pre-verified address radio. Its accessible name
            # is the full "STREET CITY STATE ZIP", so we match by the street
            # substring (role+name is stable; the previous has-text filter never
            # matched because radio inputs have no text children, which forced
            # the manual-entry path and triggered an address-validation warning
            # that blocked submission).
            used_radio = False
            safer_addr_radio = self.page.get_by_role(
                "radio", name=street, exact=False
            )
            if await safer_addr_radio.count() > 0:
                try:
                    await safer_addr_radio.first.click(timeout=3_000, force=True)
                    used_radio = True
                    print("    [Progressive] Used SAFER-resolved home address radio")
                    await self.settle_extjs()
                except Exception:
                    pass

            if not used_radio:
                # Fall back to "Enter a different address" + manual fields
                diff_radio = self.page.get_by_role(
                    "radio", name="Enter a different address"
                )
                if await diff_radio.count() > 0:
                    try:
                        await diff_radio.first.click(timeout=2_000, force=True)
                        await self.settle_extjs()
                    except Exception:
                        pass
                box = self.page.get_by_role("textbox", name="Street Address")
                if await box.count() > 0:
                    # verify=False: ExtJS may normalize casing/spacing after blur
                    await self.safe_fill(box.first, street, verify=False)

                if zip_code:
                    print(f"    [Progressive] ZIP: {zip_code}")
                    zb = self.page.get_by_role("textbox", name="ZIP Code")
                    if await zb.count() > 0:
                        # verify=False: ZIP triggers city auto-fill on Tab;
                        # input_value may change before we can read it back.
                        await self.safe_fill(zb.first, zip_code, verify=False)
                        # City auto-fill XHR fires on Tab; condition-based.
                        await self.settle_extjs(start_ms=300)

                if city:
                    print(f"    [Progressive] City: {city}")
                    cb = self.page.get_by_role("textbox", name="City")
                    if await cb.count() > 0:
                        try:
                            current = await cb.first.input_value()
                        except Exception:
                            current = ""
                        if not current:
                            # verify=False: city may be auto-populated from ZIP;
                            # ExtJS value may differ from what we typed.
                            await self.safe_fill(cb.first, city, verify=False)

        if dob:
            print(f"    [Progressive] DOB: {dob}")
            box = self.page.get_by_role("textbox", name="Date of Birth")
            if await box.count() == 0:
                box = self.page.get_by_role("combobox", name="Date of Birth")
            if await box.count() > 0:
                # verify=False: DOB is a date-formatted field; Progressive
                # reformats it after blur so input_value != the typed string.
                await self.safe_fill(box.first, dob, verify=False)

    async def _fill_owner_name_field(self, accessible_name: str, value: str) -> None:
        """Fill First Name / Last Name by accessible name via safe_fill.

        verify=False: ExtJS may uppercase or reformat the value after blur,
        so input_value() != the original typed string.
        """
        if not value:
            return
        box = self.page.get_by_role("textbox", name=accessible_name)
        try:
            await box.first.wait_for(state="visible", timeout=5_000)
        except Exception:
            print(f"    [Progressive] WARN: textbox {accessible_name!r} not visible")
            return
        await self.safe_fill(box.first, value, verify=False)
        print(f"    [Progressive] {accessible_name} = {value!r}")

    async def _fill_placeholder(self, placeholder: str, value: str) -> None:
        """Fill a text input by its HTML5 placeholder via safe_fill.

        ExtJS textfields render the placeholder as a real `placeholder` attribute
        on the underlying `<input>`, so `get_by_placeholder` is the correct
        Playwright API. Delegates click+fill+Tab+verify to safe_fill.
        """
        if not value:
            return
        box = await self.find_by_placeholder(placeholder)
        try:
            await box.first.wait_for(state="visible", timeout=5_000)
        except Exception:
            print(f"    [Progressive] WARN: placeholder {placeholder!r} not visible")
            return
        # verify=False: placeholder fields may be ExtJS-formatted after blur
        await self.safe_fill(box.first, value, verify=False)
        print(f"    [Progressive] {placeholder} = {value!r}")

    async def _answer_oil_gas_fields(self, hauls_oil_gas: bool) -> None:
        """Conditional required question shown for trucking / dirt-sand-gravel
        classes: 'Are any vehicles used to haul to or from oil & gas fields?'

        Default No (most dirt/sand/gravel haulers are not oilfield). The
        radiogroup carries the question as its accessible name (stable), even
        though its DOM id/name are per-session ExtJS hashes. Optional: silently
        skips when the question isn't rendered for this business type.
        """
        group = await self.find_radiogroup(
            "Are any vehicles used to haul to or from oil & gas fields?"
        )
        if not await self.field_exists(group, wait_ms=1_500):
            return
        answer = "Yes" if hauls_oil_gas else "No"
        print(f"    [Progressive] Oil & gas fields hauling: {answer}")
        decision_ledger.record(
            "Are any vehicles used to haul to or from oil & gas fields?",
            answer, page=_PAGE, options=["Yes", "No"], source="DEFAULT",
            rule_id="R-017")
        await self.safe_radio(group, answer)

    async def _fill_primary_phone(self, phone: Optional[str]) -> None:
        """Fill the Primary Phone Number (3 inputs: area-code/prefix/suffix).

        Progressive marks this 'Optional' but actually requires it for
        non-trucking commodities (e.g. Beverage Distributor, Wholesale Trade).
        Phone format from blue quote: '(210) 668-1522' or '210-668-1522'.
        """
        if not phone:
            return
        import re
        digits = re.sub(r"\D", "", phone)
        if len(digits) < 10:
            print(f"    [Progressive] Phone too short to parse: {phone!r}")
            return
        # Take the LAST 10 digits in case there's a leading '1' country code
        digits = digits[-10:]
        area, prefix, suffix = digits[:3], digits[3:6], digits[6:10]
        print(f"    [Progressive] Phone: {area}-{prefix}-{suffix}")

        # Field names per the live snapshot. ExtJS numberfields may reformat
        # after blur; verify=False avoids spurious mismatch errors.
        boxes = [
            ("Three digit area code of phone", area),
            ("Three digit prefix of phone", prefix),
            ("Four digit suffix of phone", suffix),
        ]
        for label, val in boxes:
            box = self.page.get_by_role("textbox", name=label)
            if await box.count() == 0:
                print(f"    [Progressive] WARN phone[{label}]: textbox not found")
                continue
            try:
                await self.safe_fill(box.first, val, verify=False)
            except Exception as e:
                print(f"    [Progressive] WARN phone[{label}]: {e}")

    async def _answer_owns_goods(self, owns: bool) -> None:
        """Answer 'Does the customer own the goods he or she is transporting?'

        Appears for distributor-type commodities (Beverage Distributor, Food
        Distributor, etc.). NOT shown for general Trucker / For-Hire types.
        Safe to call always — no-op if the question isn't present.
        """
        group = await self.find_radiogroup(
            "Does the customer own the goods he or she is transporting?"
        )
        if not await self.field_exists(group, wait_ms=1_500):
            self._log_skipped("owns_goods", "question not rendered for this commodity")
            return
        answer = "Yes" if owns else "No"
        print(f"    [Progressive] Owns the goods being transported: {answer}")
        decision_ledger.record(
            "Does the customer own the goods he or she is transporting?",
            answer, page=_PAGE, options=["Yes", "No"], source="DEFAULT",
            rule_id="R-018")
        await self.safe_radio(group, answer)

    async def _click_start_quote(self) -> None:
        """Click 'Ok, start quote.' and CONFIRM the page actually advances.

        Progressive keeps us on pageName=BusinessOwnerInfo and shows inline
        validation errors when a required field is missing/invalid, so a plain
        networkidle wait would be a false "advanced" signal (this masked the
        owner-DOB / oil&gas gaps). We wait for the URL to leave
        BusinessOwnerInfo; if it doesn't, we collect the validation messages
        and unanswered required questions so the failure is actionable for any
        BlueQuote.
        """
        print("    [Progressive] Clicking 'Ok, start quote.'...")
        await self.remove_overlays()
        # Blur any active field so ExtJS commits pending state before submit.
        await self.blur_active_element()
        # Let ExtJS settle before we submit the form.
        try:
            await self.wait_for_extjs_idle()
        except Exception:
            await self.page.wait_for_timeout(300)

        btn = self.page.get_by_role("button", name="Ok, start quote.")
        await btn.first.scroll_into_view_if_needed(timeout=3_000)
        # NOTE: NO force=True on first attempt — Playwright's natural click
        # auto-scrolls and verifies actionability; force=True paradoxically
        # bypasses the auto-scroll and fails with "outside viewport" on
        # long forms like Beverage Distributor's START page. Retries below
        # use force=True as fallback.
        await btn.first.click(timeout=10_000)

        # Retry the click up to 2 times if the page silently refuses to
        # advance (intermittent Progressive backend issue with non-trucking
        # commodities — same root cause as VehicleSummary Continue flake).
        for attempt in range(3):
            try:
                await self.page.wait_for_function(
                    "() => !location.href.includes('pageName=BusinessOwnerInfo')",
                    timeout=30_000,
                )
                await self.page.wait_for_load_state("networkidle", timeout=30_000)
                print("    [Progressive] Quote started - moved to VehicleSummary")
                return
            except Exception:
                if attempt == 2:
                    break  # give up
                print(f"    [Progressive] Start quote did not advance; retry click {attempt + 1}/2")
                # If the page is complaining the USDOT was never verified, the
                # original Verify click didn't take effect (live CMC
                # 2026-06-10: the 'belongs to customer' skip masked it as
                # auto-confirmed). Redo Verify before retrying the submit.
                try:
                    complaint = self.page.get_by_text(
                        "Verify USDOT button", exact=False
                    )
                    if (
                        await complaint.count() > 0
                        and await complaint.first.is_visible()
                    ):
                        print(
                            "    [Progressive] START page demands USDOT "
                            "verification — re-clicking Verify"
                        )
                        await self._click_verify_usdot()
                except Exception:
                    pass
                # Idempotent: answer the 'belongs to customer' radio if it
                # appeared late (live DIBOLL 2026-06-10 post-optimization).
                try:
                    await self._confirm_usdot_belongs_to_customer(True)
                except Exception:
                    pass
                # Idempotent re-answer of the late-rendering hazmat group —
                # the only required radio we default that can outlast its
                # fill window (live LQZ re-run 2026-06-10).
                try:
                    await self._answer_hazmat_placard(False)
                except Exception:
                    pass
                await self.page.wait_for_timeout(3000)
                try:
                    await btn.first.click(timeout=10_000, force=True)
                except Exception:
                    pass

        # A risk Progressive intends to decline can stall the START submission
        # (no advance) and sometimes renders the decline notice in place rather
        # than navigating. Surface that explicitly so it's reported as a carrier
        # decline (not_eligible), not a generic "required field" error
        # (live ALMA FORCE 2026-06-25: USDOT history failed acceptability).
        try:
            decline = self.page.get_by_text(
                "Unable to Provide a Quote", exact=False
            )
            if await decline.count() > 0 and await decline.first.is_visible():
                await self.screenshot("start_quote_declined")
                raise RuntimeError(
                    "Progressive DECLINED this risk ('We are Unable to Provide a "
                    "Quote For This Risk') — carrier underwriting decline, not a "
                    "bot error."
                )
        except RuntimeError:
            raise
        except Exception:
            pass

        errors = await self._collect_validation_errors()
        await self.screenshot("start_quote_did_not_advance")
        raise RuntimeError(
            "START page did not advance after 'Ok, start quote.' — a "
            f"required field is missing or invalid. Page reported: {errors}"
        )

    async def _collect_validation_errors(self) -> str:
        """Scrape visible inline error messages + unanswered required questions
        from the START page, to make a non-advance failure self-explanatory."""
        try:
            return await self.page.evaluate(
                """() => {
                    const isReallyVisible = (e) => {
                        if (!e.offsetParent && e.tagName !== 'BODY') return false;
                        const r = e.getBoundingClientRect();
                        if (r.width === 0 || r.height === 0) return false;
                        const cs = window.getComputedStyle(e);
                        if (cs.display === 'none' || cs.visibility === 'hidden') return false;
                        if (parseFloat(cs.opacity) === 0) return false;
                        return true;
                    };
                    const msgs = [];
                    // The visible per-field error text on Progressive's START
                    // page is a tiny "This field is required" label that lives
                    // next to the input. Search for that exact phrase among
                    // visible elements — narrow and reliable.
                    document.querySelectorAll('label, span, div').forEach(e => {
                        if (!isReallyVisible(e)) return;
                        const t = (e.textContent || '').trim();
                        if (t === 'This field is required' ||
                            t === 'You must select one item in this group' ||
                            t.startsWith('Please take a look at the')) {
                            // Try to attach the field label sitting next to
                            // the error message for context.
                            const parent = e.closest('tr, fieldset, div.x-form-item') || e.parentElement;
                            const lbl = parent ? parent.querySelector('label, span') : null;
                            const ctx = lbl ? (lbl.textContent || '').replace(/\\s+/g,' ').trim().slice(0,60) : '';
                            msgs.push(ctx ? ctx + ': ' + t.slice(0,80) : t.slice(0,120));
                        }
                    });
                    // Required labels (label.requiredField) whose field group
                    // has no checked/filled control.
                    document.querySelectorAll('label.requiredField').forEach(l => {
                        const grpId = (l.id || '').replace(/^c_/, 'f_');
                        const grp = document.getElementById(grpId);
                        if (!grp) return;
                        const checked = grp.querySelector('input:checked');
                        const filled = Array.from(grp.querySelectorAll('input,select'))
                            .some(i => i.value && i.value.trim());
                        if (!checked && !filled) {
                            const q = (l.textContent || '').replace(/\\s+/g,' ').trim();
                            if (q) msgs.push('UNANSWERED: ' + q.slice(0,70));
                        }
                    });
                    return Array.from(new Set(msgs)).slice(0,10).join(' || ')
                        || '(no visible validation message)';
                }"""
            )
        except Exception:
            return "(could not collect validation errors)"
