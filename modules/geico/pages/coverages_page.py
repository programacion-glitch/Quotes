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

# How far (chars) around a "Due Today" label an amount may sit to count as
# anchored to it in the body text.
_ANCHOR_WINDOW = 120


def pick_premium(page_text: str) -> Optional[str]:
    """Extract the premium from the Step 6 body text.

    Anchor-first: the amount nearest a "Due Today" label wins. Order-based
    scanning is NOT safe here — in the HUMBERTO live mapping the BI line
    item ($19,344.00) was LARGER than the real premium ($18,941.00) and only
    DOM order saved the capture. Amounts that belong to the pay-in-full
    savings line ("Save $X") are excluded from the anchored scan.

    Fallback (no anchor present): first cents-bearing amount >= $1,000
    (>= PREMIUM_MIN_DIGITS integer digits), which filters out per-coverage
    line items like "$582.00". $0.00-style rating glitches never qualify.
    """
    if not page_text:
        return None

    # 1. Anchored scan: nearest qualifying amount to each "Due Today".
    best: Optional[tuple] = None  # (distance, "$amount")
    for anchor in re.finditer(r"Due\s+Today", page_text, re.IGNORECASE):
        lo = max(0, anchor.start() - _ANCHOR_WINDOW)
        hi = anchor.end() + _ANCHOR_WINDOW
        anchor_mid = (anchor.start() + anchor.end()) / 2
        for m in PREMIUM_RE.finditer(page_text, lo, hi):
            try:
                amount = float(m.group(1).replace(",", ""))
            except ValueError:
                continue
            if amount <= 0:
                continue
            # Skip the savings line ("Save $2,075.00 by paying in full").
            prefix = page_text[max(0, m.start() - 8):m.start()]
            if re.search(r"save\s*$", prefix, re.IGNORECASE):
                continue
            dist = abs((m.start() + m.end()) / 2 - anchor_mid)
            if best is None or dist < best[0]:
                best = (dist, f"${m.group(1)}")
    if best:
        return best[1]

    # 2. Fallback: first large cents-bearing amount in the body.
    for m in PREMIUM_RE.finditer(page_text):
        try:
            amount = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        if amount <= 0:
            continue
        integer_part = m.group(1).split(".")[0].replace(",", "")
        if len(integer_part) >= PREMIUM_MIN_DIGITS:
            return f"${m.group(1)}"
    return None


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

        # Fail-loud: a quote without a premium is NOT a quote. Stop here
        # (page state preserved for diagnostics) instead of advancing and
        # letting the flow report success with price=None.
        if not price.annual_premium:
            await self.screenshot("step6_no_premium_captured")
            raise RuntimeError(
                "Step 6: no qualifying premium found on Quote & Coverages — "
                "refusing to advance/report success without a price"
            )

        self._log_captured(price)

        pdf_url = await self._extract_pdf_url()
        print(f"    [GEICO] Step 6: PDF URL -> {pdf_url[:80]}...")

        # GEICO shows no 'Quote #' on Step 6; the conversationId in the
        # PrintQuote URL is the quote's stable identifier (live SOLANO
        # 2026-06-11) — use it when no explicit number was found.
        if not price.quote_number:
            m = re.search(r"conversationId=([A-Za-z0-9-]{8,})", pdf_url)
            if m:
                price.quote_number = m.group(1)
                print(f"    [GEICO] Step 6:   Quote id (conversationId): "
                      f"{price.quote_number}")

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
            self.note_warning(f"Recalculate handling failed: {e}")

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
            self.note_warning(f"term detection failed: {e}")
        return 12

    # ------------------------------------------------------------------
    # Premium capture (top-of-page "Due Today" or bottom "Quote/Total")
    # ------------------------------------------------------------------

    async def _capture_premium(self) -> Optional[str]:
        """Read the body text and delegate to `pick_premium` (anchored to
        'Due Today'; see its docstring for the ordering pitfall)."""
        try:
            page_text = await self.page.inner_text("body")
        except Exception as e:
            self.note_warning(f"could not read page text: {e}")
            return None
        return pick_premium(page_text)

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
        """Find the 'Print Quote Proposal' control and return an ABSOLUTE URL.

        Live SOLANO 2026-06-11: the control is a **gds-button with an href
        attribute**, NOT an <a> — role=link never matches it. The href is
        relative (`/PrintQuote?doctype=...`); prepend the sales base URL.
        """
        href = None
        try:
            # 1. gds-button (or any element) carrying the href.
            href = await self.page.evaluate(
                """() => {
                    const el = Array.from(document.querySelectorAll(
                        'gds-button, a'
                    )).find(x => /print quote proposal/i.test(x.textContent || '')
                                 && x.getAttribute('href'));
                    return el ? el.getAttribute('href') : null;
                }"""
            )
            if not href:
                # 2. legacy <a role=link>.
                link = self.page.get_by_role("link", name="Print Quote Proposal")
                if await link.count() > 0:
                    href = await link.first.get_attribute("href")
        except Exception as e:
            await self.screenshot("step6_print_quote_link_error")
            raise RuntimeError(
                f"Step 6: failed to extract Print Quote Proposal URL: {e}"
            ) from e

        if not href:
            await self.screenshot("step6_print_quote_link_missing")
            raise RuntimeError(
                "Step 6: 'Print Quote Proposal' control not found "
                "(gds-button[href] / role=link)"
            )

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
            # Dynamic outcome wait; 60s cap (coverage recompute is slow).
            await self.wait_for_step_outcome(
                ["Final Quote Details"], budget_ms=60_000
            )
            print("    [GEICO] Step 6 -> Step 7 (Final Quote Details) loaded")
        except (RuntimeError, TimeoutError) as e:
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
