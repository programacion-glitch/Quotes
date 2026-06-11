"""MTC limit snap-up: Blue Quotes request arbitrary amounts ('Others: $30,000')
but Progressive only offers fixed tiers — the chosen tier must COVER the
request (smallest >= amount), preferring the standard $1,000 deductible.
Live case: WHITE CASTLE 2026-06-11 (cargo 'Others: $30.000', no $30k tier)."""

import pytest

from modules.progressive.pages.coverages_rates_page import CoveragesRatesPage

OPTIONS = [
    "Not selected",
    "$5k with a $500 Deductible",
    "$5k with a $1,000 Deductible",
    "$10k with a $500 Deductible",
    "$10k with a $1,000 Deductible",
    "$25k with a $500 Deductible",
    "$25k with a $1,000 Deductible",
    "$50k with a $500 Deductible",
    "$50k with a $1,000 Deductible",
    "$75k with a $1,000 Deductible",
    "$100k with a $1,000 Deductible",
    "$100k with a $2,500 Deductible",
    "$150k with a $1,000 Deductible",
    "$150k with a $2,500 Deductible",
    "$200k with a $1,000 Deductible",
    "$200k with a $2,500 Deductible",
    "$250k with a $1,000 Deductible",
    "$250k with a $2,500 Deductible",
]

choose = CoveragesRatesPage._choose_mtc_limit_option
parse = CoveragesRatesPage._parse_dollar_amount


class TestChooseMtcLimitOption:
    def test_exact_tier_prefers_1000_deductible(self):
        text, value = choose(OPTIONS, 100_000)
        assert text == "$100k with a $1,000 Deductible"
        assert value == 100_000

    def test_snaps_up_when_tier_missing(self):
        # $30k is not offered — must cover the cargo value with $50k.
        text, value = choose(OPTIONS, 30_000)
        assert text == "$50k with a $1,000 Deductible"
        assert value == 50_000

    def test_above_max_uses_largest_available(self):
        text, value = choose(OPTIONS, 300_000)
        assert text == "$250k with a $1,000 Deductible"
        assert value == 250_000

    def test_small_amount_snaps_to_smallest_covering(self):
        text, value = choose(OPTIONS, 1_000)
        assert text == "$5k with a $1,000 Deductible"

    def test_tier_without_1000_ded_falls_back_to_500(self):
        opts = ["$5k with a $500 Deductible"]
        text, value = choose(opts, 5_000)
        assert text == "$5k with a $500 Deductible"

    def test_not_selected_and_garbage_ignored(self):
        assert choose(["Not selected", "garbage"], 50_000) is None

    def test_empty_options(self):
        assert choose([], 50_000) is None


class TestParseDollarAmount:
    @pytest.mark.parametrize("raw,expected", [
        ("$100,000", 100_000),
        ("$30.000", 30_000),       # handwritten dot as thousands separator
        ("100000", 100_000),
        ("$100k", 100_000),
        ("50 K", 50_000),
        ("$ 25,000", 25_000),
        ("Others", None),
        ("", None),
        (None, None),
    ])
    def test_cases(self, raw, expected):
        assert parse(raw) == expected
