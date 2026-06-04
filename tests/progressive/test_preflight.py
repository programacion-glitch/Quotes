import asyncio

from modules.progressive.field_mapper import MappedFields, MappedVehicle
from modules.progressive.preflight import run_preflight, PreflightReport
from modules.progressive.quote_flow import QuoteFlow, QuoteResult


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


def test_quoteresult_has_assumptions_field():
    r = QuoteResult()
    assert hasattr(r, "assumptions") and r.assumptions == []


def test_specific_commodity_is_not_listed_as_assumption():
    rep = run_preflight(_fields("BEVERAGE DISTRIBUTION", "FLATBED"))
    assert rep.ok()
    assert not any(a.value == "Beverage Distributor" for a in rep.assumptions)


def test_run_halts_before_browser_on_blocker(monkeypatch):
    # PACKED CHARCOAL blocks at preflight; run() must return WITHOUT login.
    flow = QuoteFlow.__new__(QuoteFlow)          # bypass __init__/browser
    flow.dry_run = True

    called = {"login": False}

    async def _boom(*a, **k):
        called["login"] = True
        raise AssertionError("browser should not open on preflight blocker")

    monkeypatch.setattr("modules.progressive.quote_flow.LoginPage", _boom)

    fields = MappedFields(
        usdot="1", business_name="JUAREZ LLC", effective_date="06/15/2026",
        owner_name="O", commodity="PACKED CHARCOAL",
        vehicles=[MappedVehicle(trailer_type="FLATBED")],
    )
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(flow.run(fields))
    finally:
        loop.close()
    assert not result.success
    assert "preflight" in (result.error or "").lower()
    assert called["login"] is False


def test_preflight_republic_normalizes_and_passes():
    # REPUBLIC: latino GVW + value -> must PROCESS (no blocker)
    f = MappedFields(
        usdot="1", business_name="REPUBLIC LLC", effective_date="06/15/2026",
        owner_name="O", commodity="SAND & GRAVEL 100%",
        vehicles=[MappedVehicle(trailer_type="DUMP TRUCK", gvw="51.000 LBS", value="$45.000")],
    )
    rep = run_preflight(f)
    assert rep.ok()


def test_preflight_blocks_unusable_value():
    f = MappedFields(
        usdot="1", business_name="X LLC", effective_date="06/15/2026",
        owner_name="O", commodity="Trucker",
        vehicles=[MappedVehicle(trailer_type="FLATBED", value="$45")],  # < $100
    )
    rep = run_preflight(f)
    assert not rep.ok()
    assert any(b.field == "Vehicle value" for b in rep.blockers)


def test_preflight_blocks_garbage_gvw():
    f = MappedFields(
        usdot="1", business_name="X LLC", effective_date="06/15/2026",
        owner_name="O", commodity="Trucker",
        vehicles=[MappedVehicle(trailer_type="FLATBED", gvw="banana")],
    )
    rep = run_preflight(f)
    assert not rep.ok()
    assert any(b.field == "Gross vehicle weight" for b in rep.blockers)


def test_preflight_light_vehicle_not_blocked_by_partial_catalog():
    # gvw=8000 LBS parses fine but is NOT in the partial heavy-only catalog
    # (['33,001 to 45,000','45,001 or more']). The LIVE combo is authoritative,
    # so preflight must NOT falsely block a parseable-but-out-of-catalog GVW.
    f = MappedFields(
        usdot="1", business_name="LIGHT LLC", effective_date="06/15/2026",
        owner_name="O", commodity="Trucker",
        vehicles=[MappedVehicle(trailer_type="PICKUP", gvw="8000 LBS")],
    )
    rep = run_preflight(f)
    assert rep.ok()


def test_preflight_skips_trailer_powered_vehicle_checks():
    # A trailer (is_trailer=True) with a non-tile type / heavy GVW must NOT block
    # preflight — trailers go through the Add Trailer flow, not the powered
    # AddVehicle tile picker (JUAREZ: Pickup + Gooseneck Trailer).
    f = MappedFields(
        usdot="1", business_name="JUAREZ", effective_date="06/15/2026",
        owner_name="O", commodity="Trucker",
        vehicles=[
            MappedVehicle(trailer_type="PICKUP TRUCK", gvw="9,000 lbs", is_trailer=False),
            MappedVehicle(trailer_type="GOOSENECK TRAILER", gvw="15,950 lbs", is_trailer=True),
        ],
    )
    rep = run_preflight(f)
    assert rep.ok()
