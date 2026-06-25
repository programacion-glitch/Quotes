"""Unit de reconcile(): form autoritativo, IA llena huecos. Determinista."""
from modules.quote_profile import ApplicantProfile, UnitsProfile, DriverProfile, CoveragesProfile
from modules.extraction_reconciler import ExtractionFields, reconcile


def _drv(n):
    return [DriverProfile(name=f"D{i}") for i in range(n)]


def test_form_drivers_win_over_ai_undercount():
    # Caso ELITE: form 4 drivers, IA 2 -> 4 + discrepancia.
    form = ExtractionFields(applicant=ApplicantProfile(business_name="ELITE"),
                            drivers=_drv(4), units=UnitsProfile(count=4))
    ai = ExtractionFields(applicant=ApplicantProfile(business_name="ELITE"),
                          drivers=_drv(2), units=UnitsProfile(count=4))
    out, disc = reconcile(form, ai)
    assert len(out.drivers) == 4
    assert any(d.field == "drivers" for d in disc)


def test_form_empty_uses_ai_drivers():
    form = ExtractionFields(applicant=ApplicantProfile(business_name="X"), drivers=[])
    ai = ExtractionFields(applicant=ApplicantProfile(business_name="X"), drivers=_drv(3))
    out, disc = reconcile(form, ai)
    assert len(out.drivers) == 3
    assert any(d.field == "drivers" and "IA" in d.resolution for d in disc)


def test_commodity_form_wins():
    form = ExtractionFields(commodity="BUILDING MATERIALS")
    ai = ExtractionFields(commodity="GENERAL FREIGHT")
    out, disc = reconcile(form, ai)
    assert out.commodity == "BUILDING MATERIALS"
    assert any(d.field == "commodity" for d in disc)


def test_ai_none_uses_form():
    form = ExtractionFields(applicant=ApplicantProfile(business_name="X"), drivers=_drv(4))
    out, disc = reconcile(form, None)
    assert len(out.drivers) == 4
    assert disc == []


def test_form_none_uses_ai():
    ai = ExtractionFields(applicant=ApplicantProfile(business_name="X"), drivers=_drv(2))
    out, disc = reconcile(None, ai)
    assert len(out.drivers) == 2


def test_scalar_gap_filled_from_ai():
    # form sin email -> usa el email de la IA.
    form = ExtractionFields(applicant=ApplicantProfile(business_name="X", email=None))
    ai = ExtractionFields(applicant=ApplicantProfile(business_name="X", email="a@b.com"))
    out, _ = reconcile(form, ai)
    assert out.applicant.email == "a@b.com"


def test_unit_count_mismatch_form_wins_with_warning():
    form = ExtractionFields(units=UnitsProfile(count=4, vehicles=[]),
                            drivers=_drv(1))
    ai = ExtractionFields(units=UnitsProfile(count=2))
    out, disc = reconcile(form, ai)
    assert out.units.count == 4
    assert any(d.field == "units" for d in disc)


def test_coverages_detail_from_form_only():
    cd = CoveragesProfile()
    form = ExtractionFields(coverages_detail=cd)
    ai = ExtractionFields(coverages_detail=None)
    out, _ = reconcile(form, ai)
    assert out.coverages_detail is cd
