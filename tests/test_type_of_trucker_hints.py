"""
R-015 (Diana 2026-08-03, PANTHER): la clasificación sigue a la operación.
subtype_from_unit_hints deriva el Type-of-Trucker del tipo de unidad cuando
el commodity es genérico/mixto/ausente.
"""

from modules.progressive.mappings import subtype_from_unit_hints


class TestSubtypeFromUnitHints:
    def test_reefer_goes_refrigerated(self):
        assert subtype_from_unit_hints(["REEFER TRAILER"]) == (
            "Refrigerated Goods", "REEFER TRAILER")

    def test_refrigerated_alias(self):
        assert subtype_from_unit_hints(["REFRIGERATED VAN"]) == (
            "Refrigerated Goods", "REFRIGERATED VAN")

    def test_dry_van_goes_general_freight(self):
        assert subtype_from_unit_hints(["DRY VAN TRAILER"]) == (
            "General Freight / Other", "DRY VAN TRAILER")

    def test_flatbed_goes_general_freight(self):
        assert subtype_from_unit_hints(["FLATBED"]) == (
            "General Freight / Other", "FLATBED")

    def test_first_unit_with_signal_wins(self):
        label, src = subtype_from_unit_hints(["TRACTOR", "DRY VAN TRAILER"])
        assert label == "General Freight / Other"
        assert src == "DRY VAN TRAILER"

    def test_no_signal_returns_none(self):
        assert subtype_from_unit_hints([]) == (None, None)
        assert subtype_from_unit_hints(None) == (None, None)
        assert subtype_from_unit_hints(["TRACTOR", "PICKUP"]) == (None, None)
