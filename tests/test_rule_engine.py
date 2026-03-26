"""
Unit tests for the RuleEngine module.

Rules are mocked by directly setting engine._rules_cache — no Excel file required.
"""

import pytest

from modules.rule_engine import RuleEngine, MGAEvaluation, FailedRule
from modules.quote_profile import (
    QuoteProfile,
    ApplicantProfile,
    DriverProfile,
    LossRunProfile,
    IftasProfile,
    AppProfile,
    UnitsProfile,
)

# ---------------------------------------------------------------------------
# Shared mock rules (two MGAs, both for DIRT SAND & GRAVEL)
# ---------------------------------------------------------------------------

MOCK_RULES = [
    {
        "MGA": "MGA_A",
        "TIPO_DE_NEGOCIO": "DIRT SAND & GRAVEL",
        "MIN_BUSINESS_YEARS": "2",
        "MIN_CDL_YEARS": "2",
        "REQUIRES_MVR": "YES",
        "MVR_MIN_YEARS": None,
        "REQUIRES_IFTAS": "SI_APLICA",
        "REQUIRES_LOSS_RUN": "YES",
        "LOSS_RUN_MIN_YEARS": "5",
        "LOSSES_MUST_BE_CLEAN": None,
        "REQUIRES_APP": "YES",
        "REQUIRES_EIN": None,
        "REQUIRES_QUESTIONS": None,
        "REQUIRES_REGISTRATIONS": None,
        "MIN_UNITS": None,
        "MIN_OWNER_AGE": None,
        "MIN_INDUSTRY_EXP_YEARS": None,
        "ALLOWED_COVERAGES": None,
        "BLOCKED_TRAILER_TYPES": "DUMP",
        "BLOCKED_COMMODITIES": None,
        "ALLOWED_TRAILER_TYPES": None,
        "ROUTING": None,
        "DOWN_PAYMENT_PCT": None,
        "MIN_PRICE": None,
        "SPECIAL_FORM": None,
        "NOTES": None,
    },
    {
        "MGA": "MGA_B",
        "TIPO_DE_NEGOCIO": "DIRT SAND & GRAVEL",
        "MIN_BUSINESS_YEARS": "1",
        "MIN_CDL_YEARS": "1",
        "REQUIRES_MVR": "YES",
        "MVR_MIN_YEARS": None,
        "REQUIRES_IFTAS": "YES",
        "REQUIRES_LOSS_RUN": "SI_APLICA",
        "LOSS_RUN_MIN_YEARS": None,
        "LOSSES_MUST_BE_CLEAN": None,
        "REQUIRES_APP": None,
        "REQUIRES_EIN": None,
        "REQUIRES_QUESTIONS": None,
        "REQUIRES_REGISTRATIONS": None,
        "MIN_UNITS": None,
        "MIN_OWNER_AGE": "30",
        "MIN_INDUSTRY_EXP_YEARS": None,
        "ALLOWED_COVERAGES": "AL,MTC,APD,GL",
        "BLOCKED_TRAILER_TYPES": None,
        "BLOCKED_COMMODITIES": "FERTILIZANTES",
        "ALLOWED_TRAILER_TYPES": None,
        "ROUTING": "SOLO_NICO",
        "DOWN_PAYMENT_PCT": "25",
        "MIN_PRICE": "25000",
        "SPECIAL_FORM": None,
        "NOTES": "Test note",
    },
]

TIPO = "DIRT SAND & GRAVEL"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def engine(tmp_path):
    """RuleEngine with _rules_cache pre-loaded (no Excel I/O)."""
    # We need a file path that exists so __init__ doesn't raise; use tmp_path.
    dummy_excel = tmp_path / "dummy.xlsx"
    dummy_excel.write_bytes(b"")  # empty file — _load_rules won't be called
    eng = RuleEngine(str(dummy_excel))
    eng._rules_cache = MOCK_RULES
    return eng


def make_profile(
    business_years: int = 3,
    owner_age: int = 35,
    cdl_years: int = 3,
    mvr_present: bool = True,
    iftas_present: bool = True,
    loss_run_present: bool = True,
    loss_run_years: int = 5,
    app_present: bool = True,
    trailer_types=None,
    commodity: str = "ARENA Y GRAVA",
    coverages=None,
) -> QuoteProfile:
    """Return a fully valid QuoteProfile for DIRT SAND & GRAVEL."""
    if trailer_types is None:
        trailer_types = ["FLATBED"]
    if coverages is None:
        coverages = ["AL", "MTC"]

    return QuoteProfile(
        applicant=ApplicantProfile(
            business_name="Test Co",
            owner_name="Juan Perez",
            owner_age=owner_age,
            business_years=business_years,
        ),
        commodity=commodity,
        coverages=coverages,
        units=UnitsProfile(count=2, trailer_types=trailer_types),
        drivers=[
            DriverProfile(
                name="Juan Perez",
                cdl_present=True,
                cdl_years=cdl_years,
                mvr_present=mvr_present,
                mvr_years_covered=3,
            )
        ],
        loss_run=LossRunProfile(
            present=loss_run_present,
            years_covered=loss_run_years,
            is_clean=True,
        ),
        iftas=IftasProfile(present=iftas_present),
        app=AppProfile(present=app_present),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEligibleProfile:
    def test_eligible_profile_passes_all(self, engine):
        """A complete, fully-valid profile should pass both MGAs."""
        profile = make_profile()
        results = engine.evaluate(profile, TIPO)

        assert len(results) == 2
        for result in results:
            assert result.eligible is True, (
                f"{result.mga_name} failed: "
                + "; ".join(f.reason for f in result.failed_rules)
            )


class TestBusinessYears:
    def test_business_years_too_low(self, engine):
        """1 business year fails MGA_A (requires 2+) but passes MGA_B (requires 1+)."""
        profile = make_profile(business_years=1)
        results = engine.evaluate(profile, TIPO)

        mga_a = next(r for r in results if r.mga_name == "MGA_A")
        mga_b = next(r for r in results if r.mga_name == "MGA_B")

        assert mga_a.eligible is False
        failed_rules = [f.rule for f in mga_a.failed_rules]
        assert "MIN_BUSINESS_YEARS" in failed_rules

        assert mga_b.eligible is True


class TestBlockedTrailerType:
    def test_blocked_trailer_type(self, engine):
        """DUMP trailer fails MGA_A (BLOCKED_TRAILER_TYPES=DUMP)."""
        profile = make_profile(trailer_types=["DUMP"])
        results = engine.evaluate(profile, TIPO)

        mga_a = next(r for r in results if r.mga_name == "MGA_A")
        assert mga_a.eligible is False
        failed_rules = [f.rule for f in mga_a.failed_rules]
        assert "BLOCKED_TRAILER_TYPES" in failed_rules


class TestSiAplicaWarning:
    def test_si_aplica_generates_warning(self, engine):
        """Missing IFTAS with SI_APLICA on MGA_A generates a warning, NOT a failure."""
        profile = make_profile(iftas_present=False)
        results = engine.evaluate(profile, TIPO)

        mga_a = next(r for r in results if r.mga_name == "MGA_A")

        # Should not be a hard failure
        failed_rules = [f.rule for f in mga_a.failed_rules]
        assert "REQUIRES_IFTAS" not in failed_rules

        # Should produce a warning
        assert any("IFTAS" in w for w in mga_a.warnings)


class TestMissingMvr:
    def test_missing_mvr_fails(self, engine):
        """No MVR when REQUIRES_MVR=YES fails both MGAs."""
        profile = make_profile(mvr_present=False)
        results = engine.evaluate(profile, TIPO)

        for result in results:
            assert result.eligible is False, f"{result.mga_name} should have failed"
            failed_rules = [f.rule for f in result.failed_rules]
            assert "REQUIRES_MVR" in failed_rules, (
                f"{result.mga_name} did not record REQUIRES_MVR failure"
            )


class TestBlockedCommodity:
    def test_blocked_commodity(self, engine):
        """FERTILIZANTES commodity fails MGA_B (BLOCKED_COMMODITIES=FERTILIZANTES)."""
        profile = make_profile(commodity="FERTILIZANTES Y PESTICIDAS")
        results = engine.evaluate(profile, TIPO)

        mga_b = next(r for r in results if r.mga_name == "MGA_B")
        assert mga_b.eligible is False
        failed_rules = [f.rule for f in mga_b.failed_rules]
        assert "BLOCKED_COMMODITIES" in failed_rules


class TestInformational:
    def test_informational_passed_through(self, engine):
        """ROUTING, DOWN_PAYMENT_PCT, and NOTES appear in MGA_B informational dict."""
        profile = make_profile()
        results = engine.evaluate(profile, TIPO)

        mga_b = next(r for r in results if r.mga_name == "MGA_B")
        info = mga_b.informational

        assert info.get("routing") == "SOLO_NICO"
        assert info.get("down_payment_pct") == 25
        assert info.get("notes") == "Test note"


class TestNoRules:
    def test_no_rules_returns_empty(self, engine):
        """A tipo_negocio with no matching rules returns an empty list."""
        profile = make_profile()
        results = engine.evaluate(profile, "NONEXISTENT BUSINESS TYPE")
        assert results == []


class TestOwnerAge:
    def test_owner_age_too_low(self, engine):
        """Owner age 25 fails MGA_B (MIN_OWNER_AGE=30)."""
        profile = make_profile(owner_age=25)
        results = engine.evaluate(profile, TIPO)

        mga_b = next(r for r in results if r.mga_name == "MGA_B")
        assert mga_b.eligible is False
        failed_rules = [f.rule for f in mga_b.failed_rules]
        assert "MIN_OWNER_AGE" in failed_rules


class TestCdlYears:
    def test_cdl_years_too_low_per_driver(self, engine):
        """CDL years of 1 fails MGA_A (MIN_CDL_YEARS=2) but passes MGA_B (MIN_CDL_YEARS=1)."""
        profile = make_profile(cdl_years=1)
        results = engine.evaluate(profile, TIPO)

        mga_a = next(r for r in results if r.mga_name == "MGA_A")
        mga_b = next(r for r in results if r.mga_name == "MGA_B")

        assert mga_a.eligible is False
        failed_rules = [f.rule for f in mga_a.failed_rules]
        assert "MIN_CDL_YEARS" in failed_rules

        assert mga_b.eligible is True
