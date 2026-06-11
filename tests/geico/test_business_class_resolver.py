"""resolve_business_class: commodity -> GEICO Business Class (G12).

Resolution order (same self-feeding pattern as Progressive):
  exact catalog match -> learned cache -> AI over prefiltered candidates
  (remembered on success) -> None (caller fails loud).

The live trigger: DIBOLL LOGISTICS ('CANNED GOODS 25%, PLASTIC BLOTTLES 25%,
TOILETRIES 25%, BEVERAGE (NON ALCOHOLIC) 25%') — a mixed commodity far
outside the 8-entry dirt/sand/gravel keyword table.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from modules.geico.business_class_resolver import (
    _candidate_options,
    resolve_business_class,
)
from modules.progressive.learned_mappings import learned_lookup, learned_remember

CATALOG = [
    "Beverage Distributor (Non-Alcoholic)",
    "Canned Goods Hauling",
    "Dirt Sand & Gravel (For A Fee)",
    "Dump Trucking",
    "General Freight Hauling",
    "Household Goods Moving",
    "Toiletries & Cosmetics Distributor",
    "Trucking (General)",
]


class FakeClassifier:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def classify_commodity(self, text, options):
        self.calls.append((text, list(options)))
        return self.answer


def test_exact_match_case_insensitive():
    label, source = resolve_business_class(
        "dirt sand & gravel (for a fee)", CATALOG, classifier=None
    )
    assert label == "Dirt Sand & Gravel (For A Fee)"
    assert source == "exact"


def test_learned_cache_hit(tmp_path: Path):
    store = tmp_path / "learned.xlsx"
    learned_remember(
        "geico_business_class", "CANNED GOODS 25%, TOILETRIES 75%",
        "Canned Goods Hauling", store=store,
    )
    label, source = resolve_business_class(
        "CANNED GOODS 25%, TOILETRIES 75%", CATALOG,
        classifier=None, store=store,
    )
    assert label == "Canned Goods Hauling"
    assert source == "learned"


def test_ai_resolution_is_remembered(tmp_path: Path):
    store = tmp_path / "learned.xlsx"
    fake = FakeClassifier("Beverage Distributor (Non-Alcoholic)")
    label, source = resolve_business_class(
        "BEVERAGE (NON ALCOHOLIC) 50%, CANNED GOODS 50%", CATALOG,
        classifier=fake, store=store,
    )
    assert label == "Beverage Distributor (Non-Alcoholic)"
    assert source == "ai"
    assert fake.calls, "classifier must be consulted"
    # Next time: served from the cache, no AI call.
    assert learned_lookup(
        "geico_business_class", "BEVERAGE (NON ALCOHOLIC) 50%, CANNED GOODS 50%",
        store=store,
    ) == "Beverage Distributor (Non-Alcoholic)"


def test_ai_answer_outside_catalog_is_rejected(tmp_path: Path):
    store = tmp_path / "learned.xlsx"
    fake = FakeClassifier("Made Up Class")
    label, source = resolve_business_class(
        "WIDGETS 100%", CATALOG, classifier=fake, store=store,
    )
    assert label is None
    assert source == ""


def test_no_classifier_no_match_returns_none(tmp_path: Path):
    label, source = resolve_business_class(
        "WIDGETS 100%", CATALOG, classifier=None,
        store=tmp_path / "learned.xlsx",
    )
    assert label is None


def test_candidates_prefilter_token_hits_and_generics():
    cands = _candidate_options(
        "CANNED GOODS 25%, BEVERAGE (NON ALCOHOLIC) 25%", CATALOG
    )
    assert "Canned Goods Hauling" in cands
    assert "Beverage Distributor (Non-Alcoholic)" in cands
    # generic fallbacks always present so the AI can pick a catch-all
    assert "General Freight Hauling" in cands
    assert "Trucking (General)" in cands
    # unrelated specialty entries are filtered out
    assert "Household Goods Moving" not in cands


def test_candidates_capped():
    big_catalog = [f"Class {i:04d} Hauling" for i in range(900)]
    cands = _candidate_options("HAULING STUFF", big_catalog, cap=200)
    assert len(cands) <= 200
