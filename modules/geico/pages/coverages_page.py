"""
Quote & Coverages Page Object for GEICO wizard (Step 6).

Title: `GEICO Quote & Coverages`. This is THE page that displays the
premium and exposes the `Print Quote Proposal` link — our PDF deliverable.

Block 4 MVP scope (per docs/Proceso GEICO.md Step 6):
  * ACCEPT the GEICO-default coverages (BI/CSL $500k, UM/UIM $500k CSL,
    PIP $2,500, all per-vehicle defaults). We do NOT customize anything
    here — keeping behavior conservative until the field_mapper learns
    coverage customization.
  * Capture the premium text + (optional) quote_number + (optional)
    pay-in-full savings amount.
  * Read which term button is `[pressed]` to know whether it's a 6- vs
    12-month policy (default is 12-Month).
  * Extract the absolute `Print Quote Proposal` PDF URL — the actual
    download is performed by the orchestrator/caller (JS `fetch` with
    credentials in the same browser context).
  * If a `Recalculate` button is visible (because GEICO/system flagged
    a recompute), click it BEFORE capturing the price.
  * Click `Next` to advance to Step 7 `Final Quote Details`.

Known informational alerts that must NOT block the capture:
  * "MVR/CLUE Hasn't run" — premium may shift after Step 8, but for the
    quote-only flow this is the number we surface.
  * "An unidentified trailer has been added to your policy" — side-effect
    of selecting Tractor in Step 3; informational only.

Returns a (QuotePrice, pdf_url) tuple. `pdf_url` is absolute and points
at `https://sales.geico.com/PrintQuote?...`. Either field of QuotePrice
may be None if the page didn't render it — that's intentional, the
caller decides whether None is fatal.
"""

import re
from typing import Optional

from playwright.async_api import Page

from modules.geico.pages.base_page import BasePage
from modules.geico.quote_result_types import QuotePrice


# Matches "$18,941.00", "$2,075.00", etc. Requires cents to avoid
# matching things like "$500" (deductible defaults rendered as plain ints).
PREMIUM_RE = re.compile(r"\$([\d,]+\.\d{2})")

# A "real" premium has at least 4 digits before the decimal (i.e. >= $1,000).
# Used to distinguish premium amounts from line-item coverage prices like
# "$582.00" UM/UIM line item.
PREMIUM_MIN_DIGITS = 4

# Base URL for the absolute PrintQuote endpoint. The link's `href` attribute
# is relative (starts with `/PrintQuote?...`).
GEICO_SALES_BASE_URL = "https://sales.geico.com"


class CoveragesPage(BasePage):
    """GEICO wizard Step 6 — Quote & Coverages (PREMIUM + PDF link)."""

    def __init__(self, page: Page):
        super().__init__(page)

    async def capture_and_advance(self) -> tuple[QuotePrice, str]:
        """
        Wait for the premium to be visible, capture price + (optional)
        quote_number, extract the absolute Print Quote Proposal URL, click
        Next to advance to Step 7.

        Returns:
            (QuotePrice, pdf_url) tuple. pdf_url is an absolute URL
            (e.g. 'https://sales.geico.com/PrintQuote?doctype=...').

        Pre-state: 'Quote & Coverages' title visible.
        Post-state: 'Final Quote Details' title (Step 7) loaded.
        """
        await self.page.wait_for_load_state("networkidle", timeout=30_000)
        await self.remove_overlays()
        print("    [GEICO] Step 6: Quote & Coverages")

        await self._wait_for_premium()
        await self._recalculate_if_needed()

        price = QuotePrice()
        price.term_months = await self._detect_term_months()
        price.annual_premium = await self._capture_premium()
        price.pay_in_full_savings = await self._capture_pay_in_full_savings()
        price.quote_number = await self._capture_quote_number()

        self._log_captured(price)

        pdf_url = await self._extract_pdf_url()
        print(f"    [GEICO] Step 6: PDF URL -> {pdf_url[:80]}...")

        await self._click_next()
        return price, pdf_url

    # ------------------------------------------------------------------
    # Wait for the premium to be rendered
    # ------------------------------------------------------------------

    async def _wait_for_premium(self) -> None:
        """Wait until SOME dollar amount with cents is visible on the page.

        We don't pin to a specific label because the "Due Today" / "Quote"
        wording shifts between renders — the cents-bearing dollar amount
        is the most stable signal that the premium has finished loading.
        """
        try:
            await self.page.get_by_text(
                re.compile(r"\$[\d,]+\.\d{2}")
            ).first.wait_for(state="visible", timeout=45_000)
        except Exception as e:
            await self.screenshot("step6_premium_not_visible")
            raise RuntimeError(
                f"Step 6: premium never became visible (timeout): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Recalculate if the page asks us to
    # ------------------------------------------------------------------

    async def _recalculate_if_needed(self) -> None:
        """Click Recalculate if it's visible (coverages were changed)."""
        try:
            btn = self.page.get_by_role("button", name="Recalculate")
            if await btn.count() == 0:
                return
            print("    [GEICO] Step 6: Recalculate visible -> clicking")
            await btn.first.click(timeout=10_000)
            await self.page.wait_for_load_state(
                "networkidle", timeout=30_000
            )
            await self.page.wait_for_timeout(2_000)
        except Exception as e:
            # Recalc is a soft path — log and continue with whatever
            # price is currently shown.
            print(f"    [GEICO] WARN: Recalculate handling failed: {e}")

    # ------------------------------------------------------------------
    # Term (6-month vs 12-month) detection
    # ------------------------------------------------------------------

    async def _detect_term_months(self) -> int:
        """Read which term toggle button is currently pressed.

        Defaults to 12 if we can't tell (matches GEICO's default render).
        """
        try:
            btn_12 = self.page.get_by_role("button", name="12 Month")
            if await btn_12.count() > 0:
                pressed = await btn_12.first.get_attribute("aria-pressed")
                if pressed and pressed.lower() == "true":
                    return 12

            btn_6 = self.page.get_by_role("button", name="6 Month")
            if await btn_6.count() > 0:
                pressed = await btn_6.first.get_attribute("aria-pressed")
                if pressed and pressed.lower() == "true":
                    return 6
        except Exception as e:
            print(f"    [GEICO] WARN: term detection failed: {e}")
        return 12

    # ------------------------------------------------------------------
    # Premium capture (top-of-page "Due Today" or bottom "Quote/Total")
    # ------------------------------------------------------------------

    async def _capture_premium(self) -> Optional[str]:
        """Return the first dollar amount with >= 4 digits (i.e. >= $1,000).

        We scan the page text and pick the first cents-bearing dollar
        amount whose integer part has at least 4 digits — this filters
        out coverage line items like "$582.00" while still matching
        "$18,941.00" or "$1,234.56".
        """
        try:
            page_text = await self.page.inner_text("body")
        except Exception as e:
            print(f"    [GEICO] WARN: could not read page text: {e}")
            return None

        for match in PREMIUM_RE.finditer(page_text):
            digits_only = match.group(1).replace(",", "").replace(".", "")
            # Reject $0.00 / $0,000.00 etc. — these are rating-engine glitches
            # and should NOT propagate as a "valid" premium to the orchestrator.
            try:
                amount = float(match.group(1).replace(",", ""))
            except ValueError:
                continue
            if amount <= 0:
                continue
            integer_part = match.group(1).split(".")[0].replace(",", "")
            if len(integer_part) >= PREMIUM_MIN_DIGITS:
                return f"${match.group(1)}"

        # No qualifying premium found. Do NOT fall back to "any small amount"
        # — that path historically returned $0.00 on glitches. Let the caller
        # treat None as a real failure.
        return None

    # ------------------------------------------------------------------
    # "Save $X by paying in full"
    # ------------------------------------------------------------------

    async def _capture_pay_in_full_savings(self) -> Optional[str]:
        """Return the savings dollar amount from 'Save $X by paying in full'."""
        try:
            page_text = await self.page.inner_text("body")
        except Exception:
            return None
        m = re.search(
            r"Save\s+\$([\d,]+\.\d{2})\s+by\s+paying\s+in\s+full",
            page_text,
            re.IGNORECASE,
        )
        if m:
            return f"${m.group(1)}"
        # Looser fallback ("Save $X" without "by paying in full" suffix).
        m = re.search(
            r"Save\s+\$([\d,]+\.\d{2})", page_text, re.IGNORECASE
        )
        return f"${m.group(1)}" if m else None

    # ------------------------------------------------------------------
    # Quote number (may not be present on Step 6 — fine to be None)
    # ------------------------------------------------------------------

    async def _capture_quote_number(self) -> Optional[str]:
        """Look for a 'Quote #' or 'Quote Number' label and grab the value."""
        try:
            page_text = await self.page.inner_text("body")
        except Exception:
            return None
        m = re.search(
            r"Quote\s*(?:#|Number)[:\s]*([A-Z0-9\-]{6,})",
            page_text,
            re.IGNORECASE,
        )
        return m.group(1) if m else None

    # ------------------------------------------------------------------
    # PDF URL extraction (Print Quote Proposal link)
    # ------------------------------------------------------------------

    async def _extract_pdf_url(self) -> str:
        """Find the 'Print Quote Proposal' link and return an ABSOLUTE URL.

        The href is rendered relative (e.g. `/PrintQuote?doctype=...`).
        We prepend the sales base URL to make it absolute, so the caller
        can `fetch()` it directly.
        """
        try:
            link = self.page.get_by_role("link", name="Print Quote Proposal")
            if await link.count() == 0:
                await self.screenshot("step6_print_quote_link_missing")
                raise RuntimeError(
                    "Step 6: 'Print Quote Proposal' link not found"
                )
            href = await link.first.get_attribute("href")
            if not href:
                await self.screenshot("step6_print_quote_href_empty")
                raise RuntimeError(
                    "Step 6: 'Print Quote Proposal' link has no href"
                )
        except RuntimeError:
            raise
        except Exception as e:
            await self.screenshot("step6_print_quote_link_error")
            raise RuntimeError(
                f"Step 6: failed to extract Print Quote Proposal URL: {e}"
            ) from e

        if href.startswith("http://") or href.startswith("https://"):
            return href
        if not href.startswith("/"):
            href = "/" + href
        return f"{GEICO_SALES_BASE_URL}{href}"

    # ------------------------------------------------------------------
    # Submit (Next -> Step 7 Final Quote Details)
    # ------------------------------------------------------------------

    async def _click_next(self) -> None:
        """Click Next at the bottom of the Quote panel; wait for Step 7."""
        print("    [GEICO] Step 6: Clicking Next...")
        await self.remove_overlays()
        try:
            btn = self.page.get_by_role("button", name="Next")
            count = await btn.count()
            if count == 0:
                await self.screenshot("step6_next_missing")
                raise RuntimeError("Step 6: 'Next' button not found")
            # Use the LAST Next on the page — the Quote panel's primary
            # CTA sits at the bottom; older render fragments at the top
            # can also expose a 'Next' that does nothing useful.
            await btn.last.click(timeout=10_000)
        except RuntimeError:
            raise
        except Exception as e:
            await self.screenshot("step6_next_click_error")
            raise RuntimeError(
                f"Step 6: failed to click Next: {e}"
            ) from e

        try:
            # Coverage recompute on advance can be slow — 30s is intentional.
            await self.page.wait_for_function(
                "() => document.title.includes('Final Quote Details')",
                timeout=30_000,
            )
            print("    [GEICO] Step 6 -> Step 7 (Final Quote Details) loaded")
        except Exception as e:
            await self.screenshot("step6_to_step7_navigation_error")
            raise RuntimeError(
                f"Step 6 submit did not advance to Final Quote Details: {e}"
            ) from e

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _log_captured(self, price: QuotePrice) -> None:
        """Echo what we captured for the log trail."""
        print(
            f"    [GEICO] Step 6: PRICE CAPTURED -> "
            f"{price.annual_premium} ({price.term_months}-Month)"
        )
        if price.pay_in_full_savings:
            print(
                f"    [GEICO] Step 6:   Pay-in-full savings: "
                f"{price.pay_in_full_savings}"
            )
        if price.quote_number:
            print(f"    [GEICO] Step 6:   Quote #: {price.quote_number}")
