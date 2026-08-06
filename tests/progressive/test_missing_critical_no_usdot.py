"""El USDOT tampoco puede seguir siendo 'crítico' en Progressive.

`ProgressiveClient.create_quote` corta con `missing_critical()` ANTES de abrir
el browser (client.py:95), así que dejar 'usdot' en esa lista anula el path de
New Venture aunque quote_flow ya no halte. R-092.
"""

from __future__ import annotations

from modules.progressive.field_mapper import MappedFields, MappedVehicle


def _fields(**kw):
    base = dict(
        business_name="TEST LLC", effective_date="08/10/2026",
        owner_name="ANA GARCIA",
        vehicles=[MappedVehicle(vin="1FUJGLDR8LSLT1234", year=2020,
                                make="FREIGHT", model="CASCADIA")],
    )
    base.update(kw)
    return MappedFields(**base)


def test_missing_usdot_no_longer_blocks_the_quote():
    assert "usdot" not in _fields(usdot=None).missing_critical()


def test_complete_new_venture_has_nothing_missing():
    assert _fields(usdot=None).missing_critical() == []


def test_other_critical_fields_still_block():
    missing = _fields(usdot=None, business_name=None,
                      owner_name=None, vehicles=[]).missing_critical()
    assert "business_name" in missing
    assert "owner_name" in missing
    assert any("vehicles" in m for m in missing)
