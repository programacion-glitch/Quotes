"""Commodity -> Progressive Business Type resolution: table -> AI -> None."""

from __future__ import annotations

from modules.progressive.business_type_classifier import (
    resolve_commodity_to_business_type,
    classify_business_type_ai,
    ai_pick_from_options,
    load_trucking_business_types,
)


class _FakeClassifier:
    """Stand-in for AICommodityClassifier — records calls, returns a scripted
    answer. The real one makes a network call we can't run in tests."""

    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def classify_commodity(self, commodity_text, business_types):
        self.calls.append((commodity_text, list(business_types)))
        return self.answer


def test_specific_table_hit_does_not_call_ai():
    fake = _FakeClassifier(answer="SHOULD NOT BE USED")
    label, note = resolve_commodity_to_business_type("SAND & GRAVEL 100%", classifier=fake)
    assert label == "Dirt Sand & Gravel (For A Fee)"
    assert note == "mapping"
    assert fake.calls == []  # table hit short-circuits the AI


def test_generic_table_hit_does_not_call_ai():
    fake = _FakeClassifier(answer="SHOULD NOT BE USED")
    label, note = resolve_commodity_to_business_type("Trucker", classifier=fake)
    assert label == "Trucker"
    assert note == "generic"
    assert fake.calls == []


def test_unmapped_commodity_falls_back_to_ai():
    """SCRAP METAL is in no keyword table; the AI maps it to the real
    Progressive option."""
    fake = _FakeClassifier(answer="Scrap Metal/Scrap Auto Hauler")
    label, note = resolve_commodity_to_business_type("SCRAP METAL 100%", classifier=fake)
    assert label == "Scrap Metal/Scrap Auto Hauler"
    assert note == "ai"
    assert len(fake.calls) == 1
    # The AI must be offered the real Progressive trucking taxonomy.
    _, offered = fake.calls[0]
    assert "Scrap Metal/Scrap Auto Hauler" in offered


def test_ai_returns_none_yields_unmapped():
    fake = _FakeClassifier(answer=None)
    label, note = resolve_commodity_to_business_type("SOMETHING BIZARRE XYZ", classifier=fake)
    assert label is None
    assert note == "unmapped"


def test_classify_ai_empty_commodity_is_none():
    fake = _FakeClassifier(answer="X")
    assert classify_business_type_ai("", classifier=fake) is None
    assert classify_business_type_ai(None, classifier=fake) is None
    assert fake.calls == []


def test_classify_ai_handles_classifier_exception():
    class _Boom:
        def classify_commodity(self, *a):
            raise RuntimeError("proxy down")
    # options passed explicitly so it doesn't depend on the catalog file
    assert classify_business_type_ai(
        "SCRAP METAL", classifier=_Boom(), options=["Scrap Metal/Scrap Auto Hauler"]
    ) is None


def test_ai_pick_from_options_generic_for_mtc():
    """ai_pick_from_options is reused for the MTC cargo category/commodity
    pickers — map a free-text commodity to one of an arbitrary option list."""
    cats = ["Food & Beverage", "Metals/ Minerals/ Coal", "Paper/ Plastic/ Glass"]
    fake = _FakeClassifier(answer="Metals/ Minerals/ Coal")
    assert ai_pick_from_options("SCRAP METAL 100%", cats, classifier=fake) == "Metals/ Minerals/ Coal"
    assert fake.calls[0][1] == cats


def test_ai_pick_from_options_rejects_off_list_answer():
    """If the model hallucinates an answer not in the offered list, return None
    (the caller falls back) — never select something that isn't an option."""
    fake = _FakeClassifier(answer="Something Not Offered")
    assert ai_pick_from_options("X", ["A", "B"], classifier=fake) is None


def test_ai_pick_from_options_empty_inputs():
    fake = _FakeClassifier(answer="A")
    assert ai_pick_from_options("", ["A"], classifier=fake) is None
    assert ai_pick_from_options("X", [], classifier=fake) is None


def test_trucking_subset_catalog_loads_and_has_scrap_metal():
    opts = load_trucking_business_types()
    assert len(opts) > 30
    assert "Scrap Metal/Scrap Auto Hauler" in opts
    assert "General Freight Hauler" in opts
