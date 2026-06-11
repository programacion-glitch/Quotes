"""pick_premium: anchored premium extraction from Step 6 body text (G6).

The old heuristic ("first cents-bearing amount >= $1,000 in the body") was
order-dependent: in the HUMBERTO live mapping the BI line item ($19,344.00)
was LARGER than the real premium ($18,941.00) and only DOM order saved the
capture. The 'Due Today' anchor is the stable signal.
"""

from __future__ import annotations

from modules.geico.pages.coverages_page import pick_premium


def test_due_today_anchor_beats_earlier_larger_line_item():
    text = (
        "Liability Coverage Bodily Injury $19,344.00\n"
        "UM/UIM $582.00\n"
        "Basic PIP $183.00\n"
        "$18,941.00 Due Today\n"
        "Save $2,075.00 by paying in full"
    )
    assert pick_premium(text) == "$18,941.00"


def test_due_today_anchor_amount_after_label():
    text = "Some coverage $19,344.00 ... Due Today $18,941.00 more text"
    assert pick_premium(text) == "$18,941.00"


def test_fallback_first_large_amount_when_no_anchor():
    text = "Quote total $19,344.00 and a line item $582.00"
    assert pick_premium(text) == "$19,344.00"


def test_zero_amounts_rejected_even_near_anchor():
    text = "$0.00 Due Today glitch ... real total $18,941.00"
    assert pick_premium(text) == "$18,941.00"


def test_small_line_items_only_returns_none():
    text = "UM/UIM $582.00 and PIP $183.00"
    assert pick_premium(text) is None


def test_no_amounts_returns_none():
    assert pick_premium("no dollars here") is None


def test_empty_returns_none():
    assert pick_premium("") is None


def test_amounts_without_cents_ignored():
    # "$500" deductible-style integers must not match.
    text = "Comprehensive $500 deductible Due Today"
    assert pick_premium(text) is None
