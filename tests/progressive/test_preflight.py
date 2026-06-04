from modules.progressive.field_mapper import MappedFields, MappedVehicle
from modules.progressive.preflight import run_preflight, PreflightReport


def _fields(commodity, vehicle_type):
    return MappedFields(
        usdot="123", business_name="X LLC", effective_date="06/15/2026",
        owner_name="Owner", commodity=commodity,
        vehicles=[MappedVehicle(trailer_type=vehicle_type)],
    )


def test_clean_fields_no_blockers():
    rep = run_preflight(_fields("BEVERAGE DISTRIBUTION", "FLATBED"))
    assert isinstance(rep, PreflightReport)
    assert rep.ok() and rep.blockers == []


def test_unmappable_commodity_blocks():
    rep = run_preflight(_fields("PACKED CHARCOAL", "FLATBED"))
    assert not rep.ok()
    assert any(b.field == "Business type" and b.source_value == "PACKED CHARCOAL"
               for b in rep.blockers)


def test_collects_all_blockers_in_one_pass():
    rep = run_preflight(_fields("PACKED CHARCOAL", "MONORAIL SLED"))
    # both commodity AND vehicle fail, both reported (NOT fail-fast)
    fields = {b.field for b in rep.blockers}
    assert "Business type" in fields and "Vehicle tile" in fields


def test_generic_commodity_is_assumption_not_blocker():
    rep = run_preflight(_fields("DRY VAN FREIGHT", "FLATBED"))
    assert rep.ok()


def test_trucker_default_is_assumption_not_blocker():
    # absent-commodity quotes default to "Trucker" — must pass preflight
    rep = run_preflight(_fields("Trucker", "FLATBED"))
    assert rep.ok()
    assert any(a.value == "Trucker" for a in rep.assumptions)
