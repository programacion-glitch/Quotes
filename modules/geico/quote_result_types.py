"""
Shared result dataclasses for the GEICO quote flow.

These dataclasses are split out of `quote_flow.py` so that page objects
(e.g. `coverages_page.py`) can import them without producing a circular
import (`quote_flow` imports the page modules — the pages can't import
back from `quote_flow`).

Keep this module dependency-free aside from stdlib so any layer of the
GEICO stack can import it cheaply.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class QuotePrice:
    """Premium info captured from the Quote & Coverages page."""

    annual_premium: Optional[str] = None       # e.g. "$18,941.00"
    pay_in_full_savings: Optional[str] = None  # e.g. "$2,075.00"
    quote_number: Optional[str] = None         # if visible
    term_months: int = 12


@dataclass
class QuoteResult:
    """Result of a GEICO quote attempt."""

    success: bool = False
    step_reached: str = ""
    error: Optional[str] = None
    screenshot_path: Optional[str] = None
    pdf_path: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    price: Optional[QuotePrice] = None
    # True when the flow stopped at a known scaffolding checkpoint (e.g. a
    # half-implemented Block N stub) instead of at a real failure.
    # The retry loop in client.py uses this to skip pointless retries.
    is_stub: bool = False
    # True when GEICO definitively rejected the USDOT/ZIP eligibility check.
    # This is a final answer (not a transient failure), so client.py must NOT
    # retry — the same USDOT would be rejected again.
    halted: bool = False
    # True when GEICO could not verify the business owner's identity and is
    # asking for the owner's SSN. We never auto-fill the SSN (sensitive data).
    # This failure is intermittent, so client.py RETRIES it; once retries are
    # exhausted it is promoted to a HALT for manual intervention.
    needs_manual_review: bool = False
