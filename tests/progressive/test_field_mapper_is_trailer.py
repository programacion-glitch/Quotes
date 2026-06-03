"""is_trailer flag must propagate VehicleProfile → MappedVehicle through _map_vehicle."""

from __future__ import annotations

from modules.quote_profile import VehicleProfile
from modules.progressive.field_mapper import _map_vehicle


def test_map_vehicle_propagates_is_trailer_true():
    v = VehicleProfile(vin="1UYVS253XM7301310", year=2021, make="UTILITY",
                       model="DRY VAN", is_trailer=True)
    mapped = _map_vehicle(v, fallback_zip=None, fallback_type="DRY VAN")
    assert mapped.is_trailer is True


def test_map_vehicle_propagates_is_trailer_false():
    v = VehicleProfile(vin="1FUJGLDR8LSLT1234", year=2020, make="FREIGHTLINER",
                       model="CASCADIA", is_trailer=False)
    mapped = _map_vehicle(v, fallback_zip=None, fallback_type="TRACTOR")
    assert mapped.is_trailer is False
