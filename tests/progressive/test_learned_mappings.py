"""Self-feeding learned-mappings Excel cache."""

from __future__ import annotations

import pytest

from modules.progressive.learned_mappings import learned_lookup, learned_remember
from modules.progressive.business_type_classifier import (
    resolve_commodity_to_business_type,
    ai_pick_from_options,
)


@pytest.fixture
def store(tmp_path):
    return tmp_path / "learned.xlsx"


def test_remember_then_lookup_roundtrip(store):
    assert learned_lookup("business_type", "SCRAP METAL 100%", store=store) is None
    learned_remember("business_type", "SCRAP METAL 100%",
                     "Scrap Metal/Scrap Auto Hauler", store=store)
    assert learned_lookup("business_type", "SCRAP METAL 100%", store=store) == \
        "Scrap Metal/Scrap Auto Hauler"


def test_lookup_normalizes_case_whitespace_and_percent(store):
    learned_remember("business_type", "FRESH PRODUCE 100%",
                     "Farm Produce/Production Hauling (For A Fee)", store=store)
    # different casing / spacing / 'space %' must still hit
    assert learned_lookup("business_type", "  fresh   produce 100 %  ", store=store) == \
        "Farm Produce/Production Hauling (For A Fee)"


def test_remember_is_idempotent(store):
    learned_remember("business_type", "X 100%", "Trucker", store=store)
    learned_remember("business_type", "X 100%", "Trucker", store=store)  # no dup row
    import openpyxl
    ws = openpyxl.load_workbook(store)["mappings"]
    rows = [r for r in ws.iter_rows(min_row=2, values_only=True) if r and r[0]]
    assert len(rows) == 1


def test_decision_types_are_isolated(store):
    learned_remember("business_type", "WATER", "Beverage Distributor", store=store)
    assert learned_lookup("mtc_commodity", "WATER", store=store) is None


class _FakeClassifier:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def classify_commodity(self, text, options):
        self.calls.append((text, options))
        return self.answer


def test_resolve_uses_cache_before_ai(store):
    learned_remember("business_type", "SCRAP METAL 100%",
                     "Scrap Metal/Scrap Auto Hauler", store=store)
    fake = _FakeClassifier(answer="SHOULD NOT BE CALLED")
    label, note = resolve_commodity_to_business_type(
        "SCRAP METAL 100%", classifier=fake, store=store)
    assert label == "Scrap Metal/Scrap Auto Hauler"
    assert note == "learned"
    assert fake.calls == []  # cache hit -> no AI call


def test_resolve_remembers_ai_result(store):
    fake = _FakeClassifier(answer="General Freight Hauler")
    label, note = resolve_commodity_to_business_type(
        "MYSTERY GOODS 100%", classifier=fake, store=store)
    assert (label, note) == ("General Freight Hauler", "ai")
    assert len(fake.calls) == 1
    # The decision was written — a second resolve serves it from cache, no AI.
    fake2 = _FakeClassifier(answer="X")
    label2, note2 = resolve_commodity_to_business_type(
        "MYSTERY GOODS 100%", classifier=fake2, store=store)
    assert (label2, note2) == ("General Freight Hauler", "learned")
    assert fake2.calls == []


def test_ai_pick_caches_tile_and_mtc_decisions(store):
    """The generic matcher (tiles, MTC, makes) caches by decision_type and
    serves a repeat input without the AI — but only if the cached value is still
    a current option."""
    fake = _FakeClassifier(answer="Refrigerated Dry Freight")
    tiles = ["Dry Freight Trailer", "Refrigerated Dry Freight", "Other / Not Listed"]
    got = ai_pick_from_options("REFRIGERATED TRAILER", tiles, classifier=fake,
                               decision_type="trailer_tile", store=store)
    assert got == "Refrigerated Dry Freight"
    assert len(fake.calls) == 1

    # Repeat -> served from cache, no AI call.
    fake2 = _FakeClassifier(answer="X")
    got2 = ai_pick_from_options("Refrigerated Trailer", tiles, classifier=fake2,
                                decision_type="trailer_tile", store=store)
    assert got2 == "Refrigerated Dry Freight"
    assert fake2.calls == []


def test_ai_pick_cache_ignored_when_value_not_in_current_options(store):
    """A cached label that isn't among the current options must NOT be returned
    (option lists are business-type dependent); fall through to the AI."""
    learned_remember("trailer_tile", "REFRIGERATED TRAILER",
                     "Refrigerated Dry Freight", store=store)
    fake = _FakeClassifier(answer="Dry Freight Trailer")
    # Current options lack the cached 'Refrigerated Dry Freight'.
    got = ai_pick_from_options("REFRIGERATED TRAILER",
                               ["Dry Freight Trailer", "Flatbed Trailer"],
                               classifier=fake, decision_type="trailer_tile", store=store)
    assert got == "Dry Freight Trailer"
    assert len(fake.calls) == 1


def test_ai_pick_without_decision_type_does_not_cache(store):
    """Business Type calls ai_pick without a decision_type (it caches at a higher
    layer) — so no row is written here."""
    fake = _FakeClassifier(answer="A")
    ai_pick_from_options("X", ["A", "B"], classifier=fake, store=store)
    assert not store.exists()


def test_table_hit_skips_cache_and_ai(store):
    fake = _FakeClassifier(answer="X")
    label, note = resolve_commodity_to_business_type(
        "SAND & GRAVEL 100%", classifier=fake, store=store)
    assert label == "Dirt Sand & Gravel (For A Fee)"
    assert note == "mapping"
    assert fake.calls == []
