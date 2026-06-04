import pytest
from modules.progressive.catalogs import load_catalog, Catalog

NAMES = ["type_of_trucker", "vehicle_tiles", "trailer_tiles", "business_type", "gvw"]


@pytest.mark.parametrize("name", NAMES)
def test_catalog_loads_with_options_and_metadata(name):
    cat = load_catalog(name)
    assert isinstance(cat, Catalog)
    assert cat.options, f"{name} has empty options"
    assert cat.captured, f"{name} missing capture date"
    assert all(isinstance(o, str) and o for o in cat.options)


def test_catalog_is_cached():
    assert load_catalog("vehicle_tiles") is load_catalog("vehicle_tiles")


def test_generic_aliases_present_for_business_type():
    assert "general freight" in load_catalog("business_type").generic_aliases
