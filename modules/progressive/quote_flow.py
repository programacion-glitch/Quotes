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
from modules.progressive.pages.more_business_page import MoreBusinessPage
from modules.progressive.pages.vehicles_page import (
    AddVehiclePage,
    MostCommonVehiclesPage,
    VehicleSummaryPage,
)


@dataclass
class QuoteResult:
    """Result of a Progressive quote attempt."""
    success: bool = False
    step_reached: str = ""
    error: Optional[str] = None
    screenshot_path: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
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

            # Step 4: VEHICLES (loop over fields.vehicles)
            result.step_reached = "vehicles"
            await self._add_all_vehicles(wizard_page, fields)

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
            )

            # Step 7: RATES (CoveragesRates) - the page with the premium
            result.step_reached = "rates"
            rates_page = CoveragesRatesPage(wizard_page)
            result.price = await rates_page.customize_and_capture(fields)

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

    async def _add_all_vehicles(self, wizard_page: Page, fields: MappedFields) -> None:
        """Loop over fields.vehicles, adding each via VehicleSummary -> AddVehicle."""
        if not fields.vehicles:
            raise RuntimeError("At least one vehicle is required to quote")

        summary = VehicleSummaryPage(wizard_page)

        for i, vehicle in enumerate(fields.vehicles):
            print(f"    [Progressive] Vehicle {i + 1} / {len(fields.vehicles)}")
            await summary.add_vehicle()

            most_common = MostCommonVehiclesPage(wizard_page)
            await most_common.select_vehicle_type(vehicle.trailer_type)

            add_form = AddVehiclePage(wizard_page)
            await add_form.fill_from_mapped(vehicle)
            # add_form.fill_from_mapped() clicks Continue and returns to VehicleSummary

        # All vehicles added; continue to drivers
        await summary.click_continue()

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

        add_driver = AddDriverPage(wizard_page)
        if policyholder:
            await add_driver.fill_and_submit(
                license_state=policyholder.license_state,
                license_number=policyholder.license_number or "",
                exclude_from_policy=policyholder.exclude_from_policy,
                has_driving_history=policyholder.has_driving_history,
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
            )

        # Click Continue from DriverSummary
        await summary.click_continue()

        # Check for NoHit (MVR lookup failed for any driver)
        if "NoHit" in wizard_page.url or "Order Results" in (await wizard_page.title()):
            no_hit = NoHitPage(wizard_page)
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

    async def _take_error_screenshot(self, step: str) -> Optional[str]:
        try:
            # Prefer the wizard tab (where Steps 3+ happen); fall back to the
            # home tab for earlier failures (login / dashboard).
            page = getattr(self, "_active_page", None) or self.page
            base = BasePage(page)
            return await base.screenshot(f"error_{step}")
        except Exception:
            return None
