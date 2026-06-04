from modules.quote_profile import VehicleProfile
from modules.progressive.field_mapper import _map_vehicle


def test_map_vehicle_keeps_raw_gvw_and_value():
    v = VehicleProfile(vin="X", gvw="51.000 LBS", value="$45.000")
    mv = _map_vehicle(v, fallback_zip="77055", fallback_type="FLATBED")
    assert mv.gvw == "51.000 LBS"     # raw preserved (resolved later)
    assert mv.value == "$45.000"      # raw preserved (resolved later)


def test_map_vehicle_absent_gvw_is_none():
    v = VehicleProfile(vin="X")
    mv = _map_vehicle(v, fallback_zip=None, fallback_type="FLATBED")
    assert mv.gvw is None             # absent -> resolve_gvw will default it
