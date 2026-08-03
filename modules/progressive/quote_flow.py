"""
Quote Flow for Progressive (end-to-end orchestrator).

Sequence:
  1. Login + OTP
  2. Dashboard: state + product + USDOT search -> new tab with wizard
  3. BusinessOwnerInfo (START)
  4. VehicleSummary -> AddVehicle (per vehicle in profile.units.vehicles)
  5. AddDriver (Policyholder is auto-populated; we may need to edit each)
  6. DriverSummary -> Continue
  7. NoHit (HALT condition if MVR lookup fails and no SSN available)
  8. MoreAboutBusiness (BUSINESS)
  9. CoveragesRates (RATES) -> capture premium, configure special coverages
 10. AdditionalDetails (FINAL DETAILS) -> screenshot, STOP

Does NOT click Continue on FINAL DETAILS to avoid binding the policy at PAYMENT.
"""

from dataclasses import dataclass, field
from typing import Optional, List

from playwright.async_api import Page, BrowserContext

from modules.progressive.field_mapper import MappedFields
from modules.progressive.otp_reader import GmailOTPReader
from modules.progressive.pages._exceptions import UnmappableValueError
from modules.progressive.preflight import run_preflight, format_report, write_report
from modules.progressive.pages.base_page import BasePage
from modules.progressive.pages.business_info_page import BusinessInfoPage
from modules.progressive.pages.coverages_rates_page import (
    CoveragesRatesPage,
    QuotePrice,
)
from modules.progressive.pages.drivers_page import (
    AddDriverPage,
    DriverSummaryPage,
    NoHitPage,
)
from modules.progressive.pages.final_details_page import FinalDetailsPage
from modules.progressive.pages.home_page import HomePage
from modules.progressive.pages.login_page import LoginPage
from modules.progressive.pages.filing_proof_page import FilingProofPage
from modules.progressive.pages.more_business_page import MoreBusinessPage
from modules.progressive.pages.trailers_page import (
    AddTrailerPage,
    MostCommonTrailersPage,
)
from modules.progressive.pages.vehicles_page import (
    AddVehiclePage,
    MostCommonVehiclesPage,
    VehicleSummaryPage,
)
from modules.progressive.unit_matching import normalize_identifier, diff_unit_vs_pdf


@dataclass
class QuoteResult:
    """Result of a Progressive quote attempt."""
    success: bool = False
    step_reached: str = ""
    error: Optional[str] = None
    screenshot_path: Optional[str] = None
    pdf_path: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)   # offline preflight assumptions (logged for traceability)
    # Quote details (when success)
    price: Optional[QuotePrice] = None


class QuoteFlow:
    """Orchestrates the Progressive quote wizard end-to-end."""

    def __init__(
        self,
        page: Page,
        context: BrowserContext,
        otp_reader: GmailOTPReader,
        username: str,
        password: str,
        dry_run: bool = False,
    ):
        self.page = page
        self.context = context
        self.otp_reader = otp_reader
        self.username = username
        self.password = password
        self.dry_run = dry_run

    async def run(self, fields: MappedFields) -> QuoteResult:
        """Execute the full quote flow up to FINAL DETAILS (no payment)."""
        result = QuoteResult()

        # Preflight: validate against catalogs offline. If any blocker, do NOT
        # open the browser — hand back a batched report so the operator fixes
        # everything before re-running (kills the fix-rerun-break cycle).
        report = run_preflight(fields)
        result.assumptions = [f"{a.field} = {a.value}" for a in report.assumptions]
        if not report.ok():
            business = fields.business_name or "unknown"
            text = format_report(report, business)
            path = write_report(report, business)
            print(text)
            print(f"    [Progressive] preflight report written to {path}")
            result.step_reached = "preflight"
            result.error = (
                f"preflight: {len(report.blockers)} blocker(s) — "
                f"see {path}"
            )
            return result

        try:
            # Step 1: Login
            result.step_reached = "login"
            login_page = LoginPage(self.page, self.otp_reader)
            if not await login_page.login(self.username, self.password):
                result.error = "Login failed"
                result.screenshot_path = await login_page.screenshot("login_failed")
                return result

            # Step 2: Dashboard -> USDOT search -> new tab
            result.step_reached = "dashboard"
            home_page = HomePage(self.page)
            if not fields.usdot:
                result.error = "USDOT is required but missing from quote profile"
                return result

            wizard_page = await home_page.start_new_quote(fields.usdot, self.context)
            # The wizard runs in a NEW tab. Track it so error screenshots capture
            # the page the failure actually happened on (not the original home
            # tab, which is what self.page still points at).
            self._active_page = wizard_page

            # Step 3: START (BusinessOwnerInfo)
            result.step_reached = "business_info"
            biz_page = BusinessInfoPage(wizard_page)
            await biz_page.fill_and_submit(fields)
            if hasattr(biz_page, "warnings") and biz_page.warnings:
                result.warnings.extend(biz_page.warnings)

            # Progressive can DECLINE a risk right after START — it replaces the
            # wizard body with "We are Unable to Provide a Quote For This Risk"
            # (e.g. a USDOT whose operating history doesn't meet acceptability
            # criteria). The URL leaves BusinessOwnerInfo, so _click_start_quote
            # thinks it advanced; downstream steps then fail cryptically (live
            # ALMA FORCE 2026-06-25: declined → vehicles reported "never reached
            # the tile picker"). Detect it and HALT with a clear reason.
            decline = await self._check_declined(wizard_page)
            if decline:
                result.error = decline
                result.screenshot_path = await self._take_error_screenshot("declined")
                return result  # halted/not_eligible (no premium)

            # Step 4: VEHICLES (loop over fields.vehicles)
            result.step_reached = "vehicles"
            await self._add_all_vehicles(wizard_page, fields, result)

            # Step 5: DRIVERS (Policyholder auto-added; edit + add additional)
            result.step_reached = "drivers"
            await self._configure_drivers(wizard_page, fields, result)
            if result.error:
                return result

            # Step 6: BUSINESS (MoreAboutBusiness)
            result.step_reached = "more_business"
            more_biz = MoreBusinessPage(wizard_page)
            await more_biz.fill_and_submit(
                currently_insured=False,
                other_coverages="None",
                eld_required=False,
                customer_email=fields.owner_email,  # Diana 2026-06-25: faltaba el email del cliente
                has_general_liability=fields.has_general_liability,  # Diana #3: tildar GL (descuento)
                # Diana 2026-07-06: el radio "Are state or federal filings required?"
                # es CONDITIONAL — Progressive solo lo muestra para operaciones con
                # autoridad (for-hire trucking, etc.). Cuando aparece, el cliente
                # tiene permisos → va Yes (antes iba No y "faltaban los filings",
                # de lo que depende que le monten la prueba de seguro). Si no
                # aparece, _answer_federal_filings_conditional lo soft-skipea.
                federal_filings_required=True,
            )
            result.warnings.extend(more_biz.warnings)

            # Step 6.5: Filing/Proof of Insurance — interstitial CONDITIONAL
            # que aparece cuando R-002 respondió Yes a los filings. Live
            # 2026-07-31: PANTHER/ALTIMO/G&E morían esperando el premium de
            # RATES parados en esta página.
            filing = FilingProofPage(wizard_page)
            if await filing.is_present(wait_ms=4_000):
                result.step_reached = "filing_proof"
                await filing.complete()
                result.warnings.extend(filing.warnings)

            # Step 7: RATES (CoveragesRates) - the page with the premium
            result.step_reached = "rates"
            rates_page = CoveragesRatesPage(wizard_page)
            result.price = await rates_page.customize_and_capture(fields)
            result.warnings.extend(rates_page.warnings)

            # Fail-loud: reaching RATES without a real premium is NOT a valid
            # quote (mirrors GEICO G5). Don't capture a PDF, advance to FINAL
            # DETAILS, or report success with premium=None (live CMC 2026-06-10:
            # reached 'rates' and falsely reported success=True / premium=None).
            if not (result.price and result.price.annual_premium):
                result.error = (
                    "Reached RATES but captured no premium (premium=None) — "
                    "not a valid quote; refusing to report success."
                )
                try:
                    result.screenshot_path = await rates_page.screenshot(
                        "rates_no_premium"
                    )
                except Exception:
                    pass
                return result  # success stays False

            # Descargar el PDF OFICIAL de la cotización (proposal) desde RATES,
            # antes de proceed_to_final_details() que navega fuera de RATES. Si la
            # descarga falla tras reintentos, se cae a la captura de la página
            # (save_page_pdf) para no perder la evidencia. download_quote_pdf deja
            # el wizard en RATES pase lo que pase.
            _pdf_name = f"quote_{(result.price.quote_number if result.price else None) or 'unknown'}"
            result.pdf_path = await rates_page.download_quote_pdf(_pdf_name)
            if not result.pdf_path:
                result.warnings.append(
                    "PDF oficial de Progressive falló tras reintentos; "
                    "fallback a captura de RATES"
                )
                result.pdf_path = await rates_page.save_page_pdf(_pdf_name)

            if self.dry_run:
                result.success = True
                result.warnings.append(
                    "DRY RUN: stopped at RATES page (no FINAL DETAILS click)"
                )
                return result

            # Step 8: FINAL DETAILS (AdditionalDetails) — STOP before PAYMENT
            await rates_page.proceed_to_final_details()
            result.step_reached = "final_details"
            final_page = FinalDetailsPage(wizard_page)
            await final_page.land_and_review(order_mvr_reports=False)

            # Capture a screenshot of the final summary
            result.screenshot_path = await final_page.screenshot(
                f"quote_{result.price.quote_number or 'unknown'}"
            )

            result.success = True
            result.warnings.append(
                "Reached FINAL DETAILS. Quote captured but NOT bound (no payment)."
            )
            return result

        except UnmappableValueError as e:
            result.error = (
                f"HALT at '{result.step_reached}': {e.field} value "
                f"{e.source_value!r} matched no option. Options: "
                f"{', '.join(map(str, e.available_options[:8] or ['(none)']))}"
            )
            result.screenshot_path = (
                str(e.screenshot_path) if e.screenshot_path
                else await self._take_error_screenshot(result.step_reached)
            )
            return result
        except RuntimeError as e:
            # Expected errors (USDOT not found, missing critical field, etc.)
            result.error = str(e)
            result.screenshot_path = await self._take_error_screenshot(result.step_reached)
            return result
        except Exception as e:
            result.error = f"Unexpected error at step '{result.step_reached}': {e}"
            result.screenshot_path = await self._take_error_screenshot(result.step_reached)
            return result

    # ---- Sub-flows ----

    async def _add_all_vehicles(
        self, wizard_page: Page, fields: MappedFields, result: QuoteResult
    ) -> None:
        """Loop over fields.vehicles, adding each via VehicleSummary -> AddVehicle.

        Pre-check: read units already on the quote (Progressive remembers them
        between quotes for the same USDOT). Skip any PDF unit whose identifier
        matches a row already present, logging field-level diffs for visibility.

        Split remaining units into powered (Add Vehicle flow) and trailers
        (Add Trailer flow). Phase 0: trailer loop still skipped with WARN.
        Phase 1 wires AddTrailerPage in Task 11.
        """
        if not fields.vehicles:
            raise RuntimeError("At least one vehicle is required to quote")

        summary = VehicleSummaryPage(wizard_page)

        # Pre-existing detection
        existing = await summary.list_existing_units()
        existing_by_id = {u.identifier: u for u in existing if u.identifier}
        if existing:
            print(
                f"    [Progressive] VehicleSummary has {len(existing)} "
                f"pre-existing unit(s); pre-check enabled"
            )

        to_add: list = []
        for v in fields.vehicles:
            pdf_id = normalize_identifier(v.vin, v.year, v.make, v.model)
            if pdf_id and pdf_id in existing_by_id:
                diffs = diff_unit_vs_pdf(existing_by_id[pdf_id], v)
                msg = f"Pre-existing unit {pdf_id} kept as-is"
                if diffs:
                    msg += f" (diffs vs PDF: {diffs})"
                print(f"    [Progressive] SKIP {msg}")
                result.warnings.append(msg)
                continue
            to_add.append(v)

        # Split by is_trailer; substring fallback only if extractor failed to set
        # the flag (older fixtures / hand-built profiles in tests).
        powered, trailers = [], []
        for v in to_add:
            if v.is_trailer or self._looks_like_trailer_fallback(v):
                trailers.append(v)
            else:
                powered.append(v)

        if not (powered or existing):
            raise RuntimeError(
                "No powered vehicle to add and none pre-existing; "
                "Progressive requires at least one to quote."
            )

        # Powered loop (unchanged)
        for i, vehicle in enumerate(powered):
            print(f"    [Progressive] Vehicle {i + 1} / {len(powered)}")
            await summary.add_vehicle()

            most_common = MostCommonVehiclesPage(wizard_page)
            await most_common.select_vehicle_type(vehicle.trailer_type)

            add_form = AddVehiclePage(wizard_page)
            await add_form.fill_from_mapped(vehicle)
            if hasattr(add_form, "warnings") and add_form.warnings:
                result.warnings.extend(add_form.warnings)

        # Trailer loop (real Add Trailer flow).
        for j, trailer in enumerate(trailers):
            print(f"    [Progressive] Trailer {j + 1} / {len(trailers)}")
            await summary.add_trailer()
            most_common_t = MostCommonTrailersPage(wizard_page)
            await most_common_t.select_trailer_type(trailer.trailer_type)
            add_form_t = AddTrailerPage(wizard_page)
            await add_form_t.fill_from_mapped(trailer)
            if hasattr(add_form_t, "warnings") and add_form_t.warnings:
                result.warnings.extend(add_form_t.warnings)

        # All units added; continue to drivers
        await summary.click_continue()

    @staticmethod
    def _looks_like_trailer_fallback(vehicle) -> bool:
        """Substring heuristic kept as a safety net when an upstream extractor
        failed to set MappedVehicle.is_trailer (older fixtures / hand-built
        profiles in tests). Emits a one-line WARN so we can monitor for stray
        callers in production logs.
        """
        for s in (vehicle.trailer_type, vehicle.model, vehicle.make):
            if s and "TRAILER" in s.upper():
                print(
                    f"    [Progressive] WARN: _looks_like_trailer_fallback "
                    f"matched on '{s}' — extractor should be setting is_trailer"
                )
                return True
        return False

    async def _configure_drivers(
        self,
        wizard_page: Page,
        fields: MappedFields,
        result: QuoteResult,
    ) -> None:
        """Land on AddDriver (Policyholder), fill license number, continue.

        Note: Progressive auto-populates the Policyholder from BusinessOwnerInfo.
        We arrive directly on AddDriver pre-filled with their name.
        """
        # We're on AddDriver page for the policyholder
        # Find the policyholder driver in fields.drivers
        policyholder = next((d for d in fields.drivers if d.is_policyholder), None)
        if not policyholder and fields.drivers:
            policyholder = fields.drivers[0]

        # Progressive rule: 'There must be at least one driver that is not
        # excluded.' If the Blue Quote marks the policyholder as excluded AND
        # there are other non-excluded drivers to add, the order matters:
        # saving the policyholder as excluded FIRST blocks Add Another Driver
        # via this validation. So we DEFER policyholder exclusion: save them
        # as NOT excluded initially, add the non-excluded driver(s), then
        # Edit the policyholder row to set Exclude=Yes.
        non_excluded_additional = [
            d for d in fields.drivers
            if not d.is_policyholder and not d.exclude_from_policy
        ]
        defer_policyholder_exclusion = bool(
            policyholder
            and policyholder.exclude_from_policy
            and non_excluded_additional
        )

        add_driver = AddDriverPage(wizard_page)
        if policyholder:
            initial_exclude = (
                False if defer_policyholder_exclusion
                else policyholder.exclude_from_policy
            )
            if defer_policyholder_exclusion:
                print(
                    f"    [Progressive] Deferring policyholder exclusion "
                    f"(Blue Quote marked '{policyholder.name}' EXCLUDED but "
                    f"non-excluded additional driver(s) must be added first)"
                )
            await add_driver.fill_and_submit(
                license_state=policyholder.license_state,
                license_number=policyholder.license_number or "",
                exclude_from_policy=initial_exclude,
                has_driving_history=policyholder.has_driving_history,
                name=policyholder.name,
                date_of_birth=policyholder.date_of_birth,
            )
        else:
            # No driver info from blue quote — submit empty (will likely halt at NoHit)
            await add_driver.fill_and_submit(
                license_state="Texas",
                license_number="",
                exclude_from_policy=False,
                has_driving_history=False,
            )

        # Now on DriverSummary. Add any additional drivers.
        summary = DriverSummaryPage(wizard_page)
        for driver in fields.drivers:
            if driver.is_policyholder:
                continue
            await summary.add_driver()
            extra = AddDriverPage(wizard_page)
            await extra.fill_and_submit(
                license_state=driver.license_state,
                license_number=driver.license_number or "",
                exclude_from_policy=driver.exclude_from_policy,
                has_driving_history=driver.has_driving_history,
                name=driver.name,
                date_of_birth=driver.date_of_birth,
                additional=True,
            )

        # If we deferred policyholder exclusion, apply it now via Edit on the
        # policyholder row (index 0 — Progressive renders policyholder first).
        if defer_policyholder_exclusion and policyholder:
            print(
                f"    [Progressive] Applying deferred exclusion for "
                f"policyholder '{policyholder.name}'"
            )
            await summary.edit_driver(0)
            edit_form = AddDriverPage(wizard_page)
            await edit_form.fill_and_submit(
                license_state=policyholder.license_state,
                license_number=policyholder.license_number or "",
                exclude_from_policy=True,
                has_driving_history=policyholder.has_driving_history,
                name=policyholder.name,
                date_of_birth=policyholder.date_of_birth,
            )

        # Click Continue from DriverSummary
        await summary.click_continue()

        # Check for NoHit / 'verify info' page (MVR/CLUE lookup didn't return
        # full credit history). SSN is typically marked 'Recommended' here
        # rather than required, so try Continue without filling it. If
        # Progressive truly blocks (SSN required variant), halt with screenshot.
        if "NoHit" in wizard_page.url or "Order Results" in (await wizard_page.title()):
            no_hit = NoHitPage(wizard_page)
            advanced = await no_hit.try_continue_without_ssn()
            if advanced:
                result.warnings.append(
                    "MVR/CLUE returned no credit history; quote proceeds "
                    "with reduced underwriting accuracy (SSN not provided)."
                )
            else:
                result.warnings.append(
                    "NoHit page encountered (MVR lookup failed). "
                    "SSN required to continue — flow HALTED for safety."
                )
                result.error = (
                    "Driver MVR/CLUE lookup failed. Progressive requires the driver's "
                    "Social Security Number to proceed — which is not collected from the "
                    "blue quote. Verify driver license_number is correct or supply SSN."
                )
                result.screenshot_path = await no_hit.screenshot("nohit_halt")

    async def _check_declined(self, page: Page) -> Optional[str]:
        """Detect Progressive's 'Unable to Provide a Quote For This Risk' page.

        Progressive declines some risks outright (USDOT operating history /
        acceptability criteria) and swaps the wizard body for a decline notice
        while the URL still leaves BusinessOwnerInfo. Return a clear,
        human-readable decline reason (so the analysis email says WHY this risk
        can't be quoted), or None when the page is the normal wizard.
        """
        try:
            marker = page.get_by_text("Unable to Provide a Quote", exact=False)
            if await marker.count() == 0 or not await marker.first.is_visible():
                return None
            reason = (
                "Progressive DECLINED this risk: 'We are Unable to Provide a "
                "Quote For This Risk'. This is a carrier underwriting decline, "
                "not a bot error."
            )
            # Append Progressive's own explanation when present (acceptability
            # criteria paragraph) for an actionable analysis email.
            try:
                para = page.get_by_text("acceptability criteria", exact=False)
                if await para.count() > 0 and await para.first.is_visible():
                    detail = (await para.first.inner_text()).strip()
                    if detail:
                        reason += f" Reason: {detail}"
            except Exception:
                pass
            return reason
        except Exception:
            return None

    async def _take_error_screenshot(self, step: str) -> Optional[str]:
        try:
            # Prefer the wizard tab (where Steps 3+ happen); fall back to the
            # home tab for earlier failures (login / dashboard).
            page = getattr(self, "_active_page", None) or self.page
            base = BasePage(page)
            return await base.screenshot(f"error_{step}")
        except Exception:
            return None
