"""
Quote Flow for GEICO (end-to-end orchestrator).

Sequence (see docs/Proceso GEICO.md for full mapping):
  1. Login + MFA (Azure B2C → Email OTP via Gmail IMAP)
  2. Dashboard: Commercial Auto checkbox → USDOT eligibility → ZIP eligibility →
     Start New Quote → new tab opens with wizard
  3. Business Class & USDOT      [Block 2]
  4. Business & Owner Info       [Block 2]
  5. Vehicles                    [Block 2]
  6. Drivers & Incidents         [Block 3]
  7. Additional Business Info    [Block 3]
  7b. DriveEasy Pro (dynamic)    [Block 3]
  8. Quote & Coverages           [Block 4] — premium captured + PDF downloaded
  9. Final Quote Details         [Block 4] — STOP HERE (no click on the Next
                                              that goes to MVR & CLUE / Payment)

This file is the orchestrator. Block 1 implements through step 2 (dashboard);
later blocks fill in steps 3-9.
"""

from pathlib import Path
from typing import Optional

from playwright.async_api import Page, BrowserContext

from modules.geico.field_mapper import MappedDriver, MappedFields
from modules.geico.otp_reader import GeicoOTPReader
from modules.geico.pdf_downloader import download_geico_pdf, quote_pdf_filename
from modules.geico.pages.additional_business_page import AdditionalBusinessPage
from modules.geico.pages.base_page import BasePage
from modules.geico.pages.business_class_page import BusinessClassPage
from modules.geico.pages.business_owner_page import (
    BusinessOwnerPage,
    OwnerVerificationError,
)
from modules.geico.pages.coverages_page import CoveragesPage
from modules.geico.pages.dashboard_page import DashboardPage, EligibilityHaltError
from modules.geico.pages.driveeasy_page import DriveEasyProPage
from modules.geico.pages.drivers_page import (
    AddDriverPage,
    DriverPlaceholderPage,
    DriverSummaryPage,
)
from modules.geico.pages.final_details_page import FinalDetailsPage
from modules.geico.pages.login_page import LoginPage
from modules.geico.pages.vehicles_page import (
    CompCollSubPage,
    VehicleEntryPage,
    VehicleSummaryPage,
)
# QuotePrice / QuoteResult live in quote_result_types so that page objects
# (notably coverages_page) can import them without a circular dependency
# back through this module. Re-exported here so callers can keep doing
# `from modules.geico.quote_flow import QuoteResult` unchanged.
from modules.geico.quote_result_types import QuotePrice, QuoteResult  # noqa: F401


# Where to save downloaded quote PDFs. Anchored to the project root
# (= parent of `modules/`) so the path is independent of the orchestrator's
# CWD (cron / Task Scheduler launches with weird CWDs and a relative
# Path('data') would land in unexpected places).
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PDF_OUTPUT_DIR = _PROJECT_ROOT / "data" / "output"


class QuoteFlow:
    """Orchestrates the GEICO quote wizard end-to-end."""

    def __init__(
        self,
        page: Page,
        context: BrowserContext,
        otp_reader: GeicoOTPReader,
        username: str,
        password: str,
        login_url: str,
        dry_run: bool = False,
    ):
        self.page = page
        self.context = context
        self.otp_reader = otp_reader
        self.username = username
        self.password = password
        self.login_url = login_url
        self.dry_run = dry_run

    async def run(self, fields: MappedFields) -> QuoteResult:
        """Execute the full quote flow up to FINAL QUOTE DETAILS (no payment)."""
        result = QuoteResult()

        try:
            # ----- Step 1: Login + MFA -----
            result.step_reached = "login"
            login_page = LoginPage(self.page, self.otp_reader, self.login_url)
            if not await login_page.login(self.username, self.password):
                result.error = "Login failed (see screenshot)"
                result.screenshot_path = await login_page.screenshot("login_failed")
                return result

            # ----- Step 2: Dashboard - eligibility + start quote -----
            result.step_reached = "dashboard"
            if not fields.usdot:
                result.error = "USDOT is required but missing from quote profile"
                return result
            if not fields.zip_code:
                result.error = "ZIP code is required but missing from quote profile"
                return result

            dashboard = DashboardPage(self.page)
            wizard_page = await dashboard.start_new_quote(
                usdot=fields.usdot,
                zip_code=fields.zip_code,
                context=self.context,
            )
            # From here on, errors should be screenshotted on the WIZARD tab,
            # not the gateway tab. Track it so _take_error_screenshot grabs the
            # page the failure actually happened on.
            self._active_page = wizard_page

            # ----- Step 3: Business Class & USDOT (wizard Step 1) -----
            result.step_reached = "business_class"
            await BusinessClassPage(wizard_page).fill_and_submit(fields)

            # ----- Step 4: Business & Owner Info (wizard Step 2) -----
            result.step_reached = "business_owner"
            await BusinessOwnerPage(wizard_page).fill_and_submit(fields)

            # ----- Step 5: Vehicles (wizard Step 3) - loop + summary -----
            result.step_reached = "vehicles"
            await self._add_all_vehicles(wizard_page, fields)

            # ----- Step 6: Drivers & Incidents (wizard Step 4) -----
            result.step_reached = "drivers"
            await self._configure_drivers(wizard_page, fields)

            # ----- Step 7: Additional Business Info (wizard Step 5) -----
            result.step_reached = "additional_business"
            await AdditionalBusinessPage(wizard_page).fill_and_submit(fields)

            # ----- Step 8: DriveEasy Pro (wizard Step 5b, dynamic) -----
            result.step_reached = "driveeasy"
            await DriveEasyProPage(wizard_page).skip_to_coverages()

            # ----- Step 9: Quote & Coverages (wizard Step 6) — PRICE + PDF -----
            result.step_reached = "coverages"
            price, pdf_url = await CoveragesPage(wizard_page).capture_and_advance()
            result.price = price

            # Download the quote PDF using the authenticated browser session.
            # Errors here are non-fatal: the price was already captured, so
            # we keep going (pdf_path stays None and a warning is recorded).
            try:
                pdf_filename = quote_pdf_filename(
                    fields.business_name or "unknown",
                    price.quote_number,
                )
                pdf_path = _PDF_OUTPUT_DIR / pdf_filename
                info = await download_geico_pdf(wizard_page, pdf_url, pdf_path)
                result.pdf_path = info["path"]
                print(
                    f"    [GEICO] Quote PDF saved: {info['path']} "
                    f"({info['size']} bytes)"
                )
            except Exception as e:
                result.warnings.append(f"PDF download failed: {e}")
                print(f"    [GEICO] WARN: PDF download failed: {e}")

            # ----- Step 10: Final Quote Details (wizard Step 7) — STOP -----
            # FinalDetailsPage.fill_and_stop() fills DL numbers + workers comp +
            # vehicle owner + owned/leased, but DOES NOT click the final Next
            # (that would trigger MVR/CLUE and PAYMENT — out of cotización scope).
            result.step_reached = "final_details"
            await FinalDetailsPage(wizard_page).fill_and_stop(fields)

            # Take a confirmation screenshot of the filled final-details page.
            try:
                base = BasePage(wizard_page)
                tag = f"quote_{price.quote_number or 'no_qn'}"
                result.screenshot_path = await base.screenshot(tag)
            except Exception:
                pass  # screenshot is nice-to-have, not critical

            result.success = True
            result.is_stub = False
            result.warnings.append(
                "Reached Final Quote Details. Quote captured but NOT bound "
                "(no MVR/CLUE pull, no payment)."
            )
            return result

        except EligibilityHaltError as e:
            # Server-side rejection — surface as a clean halt, not a crash.
            # Mark halted so client.py does NOT retry (the same USDOT/ZIP
            # would be rejected identically on a second attempt).
            result.error = f"GEICO eligibility HALT: {e}"
            result.halted = True
            result.warnings.append("USDOT or ZIP not eligible per GEICO criteria.")
            try:
                base = BasePage(self.page)
                result.screenshot_path = await base.screenshot(
                    f"eligibility_halt_{result.step_reached}"
                )
            except Exception:
                pass
            return result

        except OwnerVerificationError as e:
            # GEICO asked for the owner's SSN (could not verify identity).
            # Intermittent: leave halted=False so client.py retries. Flag it so
            # the client can promote it to a HALT once retries are exhausted
            # (we never auto-fill the SSN — sensitive data).
            result.error = str(e)
            result.needs_manual_review = True
            result.warnings.append(
                "GEICO requested the Business Owner SSN. Not auto-filled; "
                "retrying the quote. If this persists, manual entry is needed."
            )
            result.screenshot_path = await self._take_error_screenshot(
                result.step_reached
            )
            return result

        except RuntimeError as e:
            result.error = str(e)
            result.screenshot_path = await self._take_error_screenshot(
                result.step_reached
            )
            return result

        except Exception as e:
            result.error = f"Unexpected error at step '{result.step_reached}': {e}"
            result.screenshot_path = await self._take_error_screenshot(
                result.step_reached
            )
            return result

    # ---- Sub-flows ----

    async def _add_all_vehicles(self, wizard_page: Page, fields: MappedFields) -> None:
        """Loop over fields.vehicles. For each: entry form → comp/coll sub-page.
        After the last one, click 'Looks Good' to advance to Drivers step.

        Pre-state: 'Vehicles' page showing 'Tell us about the vehicle...' form.
        Post-state: 'Drivers & Incidents' page loaded.

        Raises RuntimeError if fields.vehicles is empty (should have been
        caught by missing_critical earlier, but defensive here).
        """
        if not fields.vehicles:
            raise RuntimeError("At least one vehicle is required to quote")

        for i, vehicle in enumerate(fields.vehicles):
            print(f"    [GEICO] Vehicle {i + 1}/{len(fields.vehicles)}")
            await VehicleEntryPage(wizard_page).fill_and_submit(vehicle)
            await CompCollSubPage(wizard_page).answer(vehicle.has_comp_coll)
            summary = VehicleSummaryPage(wizard_page)
            is_last = i == len(fields.vehicles) - 1
            if is_last:
                await summary.click_looks_good()
            else:
                await summary.add_another()

    async def _configure_drivers(self, wizard_page: Page, fields: MappedFields) -> None:
        """Fill the owner placeholder (sub-page 1), then loop over non-excluded
        drivers via Add Driver (sub-page 2), then click Looks Good (sub-page 3)
        to advance to Step 5 'Additional Business Info'.

        Owner-driver semantics:
          * GEICO always creates a placeholder for the owner. We fill it with
            license-state + CDL Yes/No regardless of whether the owner drives.
          * Non-excluded drivers in fields.drivers get a full Add Driver entry.
            Excluded drivers (like the owner when owner_is_driver=False) are
            skipped from Add Driver — they already exist as the placeholder.

        Pre-state: 'Drivers & Incidents' page showing the owner placeholder form.
        Post-state: 'Additional Business Info' title loaded.

        Raises RuntimeError if no non-excluded driver exists.
        """
        non_excluded = [d for d in fields.drivers if not d.is_excluded]
        if not non_excluded:
            raise RuntimeError(
                "At least one non-excluded driver is required to quote "
                "(BlueQuote must include a driver with excluded != YES)"
            )

        # Sub-page 1: owner placeholder. Use the owner record if we have one in
        # the drivers list; otherwise synthesize a minimal one (Texas, no CDL).
        owner_record = next((d for d in fields.drivers if d.is_owner), None)
        if owner_record is None:
            owner_record = MappedDriver(
                first_name=fields.owner_first_name or "",
                last_name=fields.owner_last_name or "",
                license_state="Texas",
                has_cdl=False,
                is_owner=True,
                is_excluded=not fields.owner_is_driver,
            )
        await DriverPlaceholderPage(wizard_page).fill_owner_placeholder(owner_record)

        # Sub-page 2: Add Driver for each non-excluded driver. The page lands
        # on the entry form for the first one; after Save and Continue it goes
        # to the Driver Summary. add_another() brings the entry form back.
        for i, driver in enumerate(non_excluded):
            print(
                f"    [GEICO] Step 4: driver {i + 1}/{len(non_excluded)} "
                f"({driver.first_name} {driver.last_name})"
            )
            if i > 0:
                await DriverSummaryPage(wizard_page).add_another()
            await AddDriverPage(wizard_page).fill_and_submit(driver)

        # Sub-page 3: summary -> Looks Good -> advance to Step 5.
        await DriverSummaryPage(wizard_page).click_looks_good()

    async def _take_error_screenshot(self, step: str) -> Optional[str]:
        try:
            # Use the wizard tab once it's open (errors in Steps 1-7 happen
            # there); fall back to the gateway tab for earlier failures.
            page = getattr(self, "_active_page", None) or self.page
            base = BasePage(page)
            return await base.screenshot(f"error_{step}")
        except Exception:
            return None
