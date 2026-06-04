from modules.progressive.mappings import (
    VEHICLE_TILE_MAP,
    map_commodity,
)


def test_map_commodity_specific_hit():
    opt, generic = map_commodity("BEVERAGE DISTRIBUTION")
    assert opt == "Beverage Distributor" and generic is False


def test_map_commodity_general_freight_is_generic():
    opt, generic = map_commodity("DRY VAN FREIGHT")
    assert opt == "General Freight Hauler" and generic is True


def test_map_commodity_packed_charcoal_does_not_hit_coal():
    opt, generic = map_commodity("PACKED CHARCOAL")
    assert opt is None and generic is False    # -> caller HALTs


def test_map_commodity_trucker_sentinel_is_generic():
    # field_mapper's absent-commodity default must NOT be treated as unmappable
    opt, generic = map_commodity("Trucker")
    assert opt == "Trucker" and generic is True


def test_vehicle_tile_map_has_core_types():
    assert VEHICLE_TILE_MAP["FLATBED"] == "Flatbed Truck"
    assert VEHICLE_TILE_MAP["DUMP"] == "Dump Truck"
