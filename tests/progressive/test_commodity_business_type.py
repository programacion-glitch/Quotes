import pytest
from modules.progressive.pages.business_info_page import BusinessInfoPage
from modules.progressive.pages._exceptions import UnmappableValueError


def _biz():
    return BusinessInfoPage.__new__(BusinessInfoPage)


def test_unmappable_commodity_raises_instead_of_trucker():
    biz = _biz()
    with pytest.raises(UnmappableValueError) as exc:
        biz.resolve_business_type("PACKED CHARCOAL")
    assert exc.value.source_value == "PACKED CHARCOAL"


def test_specific_commodity_resolves():
    biz = _biz()
    res = biz.resolve_business_type("BEVERAGE DISTRIBUTION")
    assert res.value == "Beverage Distributor"


def test_general_freight_resolves_generic():
    biz = _biz()
    res = biz.resolve_business_type("DRY VAN FREIGHT")
    assert res.value == "General Freight Hauler"


def test_trucker_sentinel_resolves():
    biz = _biz()
    res = biz.resolve_business_type("Trucker")
    assert res.value == "Trucker"
