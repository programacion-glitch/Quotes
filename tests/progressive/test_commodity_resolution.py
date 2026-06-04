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


def test_vehicle_tile_map_restores_box_truck_synonyms():
    from modules.progressive.mappings import VEHICLE_TILE_MAP
    t = "UTILITY DRY VAN".upper()
    token = next((k for k in VEHICLE_TILE_MAP if k in t), None)
    assert VEHICLE_TILE_MAP[token] == "Box Truck"


def test_trailer_tile_map_has_gooseneck():
    from modules.progressive.mappings import TRAILER_TILE_MAP
    assert TRAILER_TILE_MAP["GOOSENECK"] == "Gooseneck Trailer"


def test_map_commodity_fracking_sand_not_dirt():
    opt, generic = map_commodity("FRACKING SAND")
    assert opt == "Fracking Sand Hauling" and generic is False


def test_map_commodity_mixed_percentage_load_is_trucker():
    # Mixed/percentage-split load, no dominant specialty -> generic Trucker.
    opt, generic = map_commodity(
        "Processed wood 33%, pipes 33%, Building Materials (LIGHT MACHINERY) 34%"
    )
    assert opt == "Trucker" and generic is True


def test_map_commodity_single_specialty_with_percent_still_specialty():
    # A single specialty with one percentage still maps to the specialty
    # (table is checked before the mixed-load rule).
    opt, generic = map_commodity("SAND & GRAVEL 100%")
    assert opt == "Dirt Sand & Gravel (For A Fee)" and generic is False
