"""Ola 2 (Diana 2026-08-04): clasificación por trailer, radio 500 millas y
matriz de filings del interstitial Filing/Proof of Insurance."""

from modules.progressive.mappings import subtype_from_unit_hints, radius_exceeds_500
from modules.progressive.business_type_classifier import resolve_commodity_to_business_type
from modules.progressive.pages.filing_proof_page import filing_selection
from modules.progressive.pages.business_info_page import BusinessInfoPage


class TestSubtypeAmpliado:
    def test_auto_hauler(self):
        assert subtype_from_unit_hints(["AUTO HAULER TRAILER"]) == (
            "Auto Hauler", "AUTO HAULER TRAILER")

    def test_tank_va_a_other_for_hire(self):
        assert subtype_from_unit_hints(["TANK TRAILER"]) == (
            "Other for hire", "TANK TRAILER")

    def test_cement_mixer_va_a_other_for_hire(self):
        assert subtype_from_unit_hints(["CEMENT MIXER"])[0] == "Other for hire"

    def test_dump_con_scrap_en_commodity(self):
        label, _ = subtype_from_unit_hints(["DUMP"], commodity="SCRAP METAL 100%")
        assert label == "Scrap Metal"

    def test_dump_con_arena_en_commodity(self):
        label, _ = subtype_from_unit_hints(["DUMP"], commodity="ARENA Y GRAVA")
        assert label == "Dirt, Sand and Gravel"

    def test_dump_sin_senal_no_afirma(self):
        assert subtype_from_unit_hints(["DUMP"], commodity="PIPES") == (None, None)


class TestBusinessTypeTrailerFallback:
    def test_packed_charcoal_en_dry_van_cae_a_trucker(self, tmp_path):
        """Caso JUAREZ: tabla y AI fallan pero el dry van clasifica (antes HALT)."""
        label, note = resolve_commodity_to_business_type(
            "PACKED CHARCOAL",
            unit_hints=["DRY VAN TRAILER"],
            classifier=lambda text: None,
            store=tmp_path / "cache.json",
        )
        assert label == "Trucker"
        assert note.startswith("trailer-fallback")

    def test_sin_trailer_sigue_unmapped(self, tmp_path):
        label, note = resolve_commodity_to_business_type(
            "PACKED CHARCOAL", unit_hints=[],
            classifier=lambda text: None, store=tmp_path / "cache.json",
        )
        assert label is None
        assert note == "unmapped"


class TestRadius500:
    def test_unlimited_supera(self):
        assert radius_exceeds_500(["Unlimited"]) is True

    def test_over_500_supera(self):
        assert radius_exceeds_500(["Over 500 miles"]) is True
        assert radius_exceeds_500(["More than 500 miles"]) is True

    def test_500_o_menos_no_supera(self):
        assert radius_exceeds_500(["500 miles"]) is False
        assert radius_exceeds_500(["0-50 miles"]) is False

    def test_sin_datos_no_supera(self):
        assert radius_exceeds_500([]) is False
        assert radius_exceeds_500([None, ""]) is False


class TestFilingSelection:
    _ALL = ["Federal Liability Filing", "MCS-90", "State"]

    def test_tres_premarcados_se_dejan(self):
        """Ambos permisos activos (los 3 pre-marcados por SAFER) → no tocar."""
        assert filing_selection(self._ALL, True) is None
        assert filing_selection(self._ALL, False) is None

    def test_sin_radio_no_afirma(self):
        assert filing_selection(["State"], None) is None

    def test_mas_de_500_federales(self):
        want = filing_selection(["State"], True)
        assert want == {"Federal Liability Filing": True, "MCS-90": True,
                        "State": False}

    def test_hasta_500_estatal(self):
        want = filing_selection(["Federal Liability Filing"], False)
        assert want == {"Federal Liability Filing": False, "MCS-90": False,
                        "State": True}


class TestFindOption:
    def test_exacto_normalizado(self):
        assert BusinessInfoPage._find_option(
            "Refrigerated Goods", ["Agricultural", "Refrigerated Goods"]
        ) == "Refrigerated Goods"

    def test_tokens_matchean_variante(self):
        """'Other for hire' de Diana matchea la opción real aunque el label
        exacto de Progressive difiera."""
        assert BusinessInfoPage._find_option(
            "Other for hire", ["Agricultural", "Other For-Hire Trucking"]
        ) == "Other For-Hire Trucking"

    def test_sin_match_devuelve_none(self):
        assert BusinessInfoPage._find_option(
            "Other for hire", ["Agricultural", "Coal"]
        ) is None
