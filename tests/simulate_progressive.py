"""
Progressive module simulation — exercises the full quote_flow against
a mock Playwright browser so every interaction is traced without touching
the network.

Run:
    python tests/simulate_progressive.py
"""

import asyncio
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from modules.quote_profile import (  # noqa: E402
    ApplicantProfile,
    CoveragesProfile,
    DriverProfile,
    QuoteProfile,
    UnitsProfile,
    VehicleProfile,
)
from modules.progressive.field_mapper import map_profile_to_fields  # noqa: E402
from modules.progressive.quote_flow import QuoteFlow  # noqa: E402
from modules.progressive import otp_reader as otp_reader_module  # noqa: E402


# ---------- Mock Playwright ------------------------------------------------

TRACE: list[str] = []


def _t(msg: str) -> None:
    TRACE.append(msg)
    print(f"  >> {msg}")


class MockLocator:
    """Minimal Playwright Locator double."""

    NOT_FOUND_MARKERS = (
        "error-message-placeholder",
        "passcode",
        "one-time",
        "verification code",
        " OTP",  # space to avoid USDOT match
        "Add a trailer instead",
        "NoHit",
    )

    def __init__(self, page: "MockPage", path: str, *, count: int | None = None):
        self.page = page
        self.path = path
        self._explicit_count = count

    @property
    def first(self):
        return MockLocator(self.page, f"{self.path}.first", count=self._explicit_count)

    @property
    def last(self):
        return MockLocator(self.page, f"{self.path}.last", count=self._explicit_count)

    def nth(self, i: int):
        return MockLocator(self.page, f"{self.path}.nth({i})", count=self._explicit_count)

    def filter(self, **kwargs):
        return MockLocator(self.page, f"{self.path}.filter({kwargs})")

    def locator(self, selector: str):
        return MockLocator(self.page, f"{self.path} >> {selector}")

    def get_by_role(self, role: str, name=None, exact=None):
        return MockLocator(self.page, f"{self.path} >> role={role},name={name!r}")

    def get_by_text(self, text: str, exact=None):
        return MockLocator(self.page, f"{self.path} >> text={text!r}")

    async def fill(self, value: str, **_):
        _t(f"FILL {self.path} = {value!r}")

    async def click(self, **_):
        _t(f"CLICK {self.path}")

    async def check(self, **_):
        _t(f"CHECK {self.path}")

    async def type(self, text: str, **_):
        _t(f"TYPE {self.path} = {text!r}")

    async def wait_for(self, **_):
        pass

    async def select_option(self, **kwargs):
        _t(f"SELECT {self.path} = {kwargs}")

    async def all_text_contents(self):
        return []

    async def inner_text(self):
        return ""

    async def input_value(self):
        return ""

    async def evaluate(self, _js: str):
        return None

    async def count(self) -> int:
        if self._explicit_count is not None:
            return self._explicit_count
        for marker in self.NOT_FOUND_MARKERS:
            if marker.lower() in self.path.lower():
                return 0
        return 1


class MockKeyboard:
    async def press(self, key: str):
        _t(f"KEY {key}")


class MockPage:
    """Minimal Playwright Page double."""

    def __init__(self, url: str = "https://foragentsonly.com/home", title: str = "Home"):
        self.url = url
        self.keyboard = MockKeyboard()
        self._title = title

    async def goto(self, url, **_):
        _t(f"GOTO {url}")
        self.url = url

    async def fill(self, selector: str, value: str):
        _t(f"FILL(selector) {selector!r} = {value!r}")

    async def click(self, selector: str):
        _t(f"CLICK(selector) {selector!r}")

    async def wait_for_load_state(self, *_, **__):
        pass

    async def wait_for_timeout(self, ms: int):
        pass

    async def screenshot(self, path: str = "", **_):
        _t(f"SCREENSHOT path={path}")
        return b""

    async def evaluate(self, _js: str):
        return None

    async def inner_text(self, _selector: str):
        # Provide a fake body with price info so capture works
        return (
            "Named Insured: M&D CUSTOM FREIGHT LLC\n"
            "Quote Number: CA116960411\n"
            "Total premium amount $53,064.00 per year\n"
            "Or save $9,041.00 by paying in full: $44,023.00\n"
            "Quote provided by: Progressive County Mutual Ins Co\n"
        )

    async def title(self):
        return self._title

    def locator(self, selector: str):
        return MockLocator(self, selector)

    def get_by_role(self, role: str, name=None, exact=None):
        return MockLocator(self, f"role={role},name={name!r}")

    def get_by_text(self, text: str, exact=None):
        return MockLocator(self, f"text={text!r}")

    def get_by_label(self, text: str):
        return MockLocator(self, f"label={text!r}")


class MockContext:
    def __init__(self):
        self.pages: list[MockPage] = []

    async def new_page(self):
        p = MockPage()
        self.pages.append(p)
        return p

    @asynccontextmanager
    async def expect_page(self, timeout: int | None = None):
        wizard = MockPage(
            url="https://clpolicy.foragentsonly.com/Express/Default.aspx?pageName=BusinessOwnerInfo",
            title="Insured And Business Info - Progressive Commercial Auto",
        )

        class _Value:
            def __init__(self, p):
                self._p = p

            def __await__(self):
                async def _():
                    return self._p
                return _().__await__()

        class _Awaitable:
            def __init__(self, p):
                self.value = _Value(p)

        yield _Awaitable(wizard)


# ---------- Helpers --------------------------------------------------------

def banner(title: str) -> None:
    print("\n" + "=" * 72)
    print(f"  {title}")
    print("=" * 72)


def build_sample_profile() -> QuoteProfile:
    """Realistic profile resembling a BlueQuote extraction for M&D Custom Freight."""
    return QuoteProfile(
        applicant=ApplicantProfile(
            business_name="M&D CUSTOM FREIGHT LLC",
            owner_name="JUAN PEREZ",
            owner_age=42,
            usdot="2998569",
            business_years=3,
            is_new_venture=False,
            industry_experience_years=10,
            owner_dob="01/15/1984",
            street_address="7630 AMELIA RD APT 110",
            city="HOUSTON",
            state="TX",
            zip_code="77055",
        ),
        commodity="GENERAL FREIGHT / FLATBED",
        coverages=["AL", "PD"],
        coverages_detail=CoveragesProfile(
            hired_auto=True,
            hired_auto_contractual=True,
            hired_auto_count_last_year="1-2",
        ),
        units=UnitsProfile(
            count=1,
            trailer_types=["PICKUP"],
            vehicles=[
                VehicleProfile(
                    vin="2GKALNEK6H6187660",
                    year=2017,
                    make="GMC",
                    model="TERRAIN",
                    trailer_type="PICKUP",
                    gvw="6,000 or less",
                    radius_miles="500 miles",
                    has_loan="No",
                    garaging_zip="77055",
                ),
            ],
        ),
        drivers=[
            DriverProfile(
                name="JUAN PEREZ",
                cdl_present=True,
                cdl_years=12,
                cdl_class="A",
                mvr_present=True,
                mvr_years_covered=5,
                mvr_is_clean=True,
                license_number="12345678",
                license_state="Texas",
                date_of_birth="01/15/1984",
            ),
        ],
    )


# ---------- Simulation sections --------------------------------------------

def sim_pure_logic(profile: QuoteProfile) -> None:
    banner("PART A — Pure logic (real execution, no mocks)")

    print("\n[A.1] field_mapper.map_profile_to_fields(profile, '04/25/2026')")
    fields = map_profile_to_fields(profile, effective_date="04/25/2026")
    for k, v in fields.__dict__.items():
        # Truncate large nested structures for readability
        if isinstance(v, list):
            print(f"        {k:18s} = [{len(v)} items]")
        else:
            print(f"        {k:18s} = {v!r}")
    print(f"        missing_critical()       = {fields.missing_critical()}")
    print(f"        missing_for_accurate_price() = {fields.missing_for_accurate_price()}")


async def sim_full_flow(profile: QuoteProfile) -> None:
    banner("PART B — QuoteFlow.run() against mocked Playwright (full trace)")

    # Monkeypatch OTP reader so it doesn't try IMAP
    def fake_fetch_otp(self, sent_after):
        _t("GmailOTPReader.fetch_otp -> returning fake OTP 123456")
        return "123456"

    otp_reader_module.GmailOTPReader.fetch_otp = fake_fetch_otp  # type: ignore[assignment]

    fields = map_profile_to_fields(profile, effective_date="04/25/2026")

    page = MockPage(url="https://www.foragentsonly.com/home/?Welcome=584")
    context = MockContext()
    otp_reader = otp_reader_module.GmailOTPReader("fake@gmail.com", "fake-pass")

    flow = QuoteFlow(
        page=page,
        context=context,
        otp_reader=otp_reader,
        username="FAKE_USER",
        password="FAKE_PASS",
        dry_run=True,
    )

    TRACE.clear()
    print("\n[B.1] Calling QuoteFlow.run(fields) with dry_run=True (stops at RATES)...")
    result = await flow.run(fields)

    print("\n[B.2] Result:")
    print(f"        success          = {result.success}")
    print(f"        step_reached     = {result.step_reached}")
    print(f"        error            = {result.error}")
    print(f"        warnings         = {result.warnings}")
    print(f"        screenshot       = {result.screenshot_path}")
    if result.price:
        print(f"        price.annual     = {result.price.annual_premium}")
        print(f"        price.pay_full   = {result.price.pay_in_full_amount}")
        print(f"        price.savings    = {result.price.pay_in_full_savings}")
        print(f"        price.carrier    = {result.price.quote_provided_by}")
        print(f"        price.quote_no   = {result.price.quote_number}")
    print(f"\n        total mock actions traced: {len(TRACE)}")


def sim_summary() -> None:
    banner("PART C — End-to-end coverage summary")

    print(
        """
    WIRED + LIVE-VALIDATED:
      1. LoginPage.login()                           (login + OTP)
      2. HomePage.start_new_quote()                  (state + product + USDOT + new tab)
      3. BusinessInfoPage.fill_and_submit()          (START - all fields)
      4. VehicleSummary -> MostCommon -> AddVehicle  (VEHICLES - looped per vehicle)
      5. AddDriver -> DriverSummary                  (DRIVERS - policyholder + extras)
      6. NoHit detection                             (HALT if MVR fails, no SSN)
      7. MoreBusinessPage.fill_and_submit()          (BUSINESS)
      8. CoveragesRatesPage.customize_and_capture()  (RATES - captures premium $)
      9. CoveragesRatesPage._configure_hired_auto()  (Hired Auto subform)
     10. CoveragesRatesPage._configure_non_owned()   (Non-Owned subform)
     11. FinalDetailsPage.land_and_review()          (FINAL DETAILS - STOPS HERE)

    NOT AUTOMATED (intentional):
      - PAYMENT step (would bind the policy)
      - COMPLETE step (only reachable after payment)
    """
    )


# ---------- Main -----------------------------------------------------------

async def main() -> None:
    banner("Progressive RPA — simulation run")
    print(f"Root: {ROOT}")
    print(f"Date: {datetime.now(timezone.utc).isoformat(timespec='seconds')}")

    profile = build_sample_profile()
    print(f"\nSample profile: {profile.applicant.business_name} / USDOT {profile.applicant.usdot}")

    sim_pure_logic(profile)
    await sim_full_flow(profile)
    sim_summary()


if __name__ == "__main__":
    asyncio.run(main())
