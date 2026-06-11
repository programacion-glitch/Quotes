"""Name parsing, owner matching and license-state normalization (G7 fixes).

Lessons already paid for in Progressive:
  - trailing suffix:    "CLIFTON THOMAS JR" must yield last=THOMAS, suffix=JR
  - two-surname names:  owner "JERSSON MEDINA" must match driver
                        "JERSSON STIVEN MEDINA ROBAYO" (commit 0f780cd)
  - state abbreviations: BlueQuote brings "TX"; GEICO's select options are
                        full names ("Texas") (commit 9605d34)
"""

from __future__ import annotations

from modules.geico.field_mapper import _map_driver, _parse_name
from modules.quote_profile import DriverProfile


# ---------- _parse_name ----------

def test_parse_name_plain():
    assert _parse_name("JOHN SMITH") == ("JOHN", "SMITH", None)


def test_parse_name_middle_name_dropped():
    assert _parse_name("MARY ANN DOE") == ("MARY", "DOE", None)


def test_parse_name_suffix_in_middle():
    assert _parse_name("CLIFTON JR THOMAS") == ("CLIFTON", "THOMAS", "JR")


def test_parse_name_trailing_suffix():
    # The natural BlueQuote order. Current code returns last="JR" — bug.
    assert _parse_name("CLIFTON THOMAS JR") == ("CLIFTON", "THOMAS", "JR")


def test_parse_name_trailing_suffix_with_period():
    assert _parse_name("JOHN SMITH SR.") == ("JOHN", "SMITH", "SR")


def test_parse_name_two_tokens_suffixlike_last_is_kept_as_last():
    # "JOHN JR" is ambiguous; without a real surname we keep it as last name.
    assert _parse_name("JOHN JR") == ("JOHN", "JR", None)


def test_parse_name_empty():
    assert _parse_name("") == ("", "", None)


# ---------- owner detection (_map_driver.is_owner) ----------

def _driver(name: str, **kw) -> DriverProfile:
    return DriverProfile(name=name, **kw)


def test_owner_match_exact():
    md = _map_driver(_driver("HUMBERTO VILLARREAL"), "HUMBERTO VILLARREAL")
    assert md.is_owner is True


def test_owner_match_middle_initial():
    md = _map_driver(_driver("HUMBERTO F VILLARREAL"), "HUMBERTO VILLARREAL")
    assert md.is_owner is True


def test_owner_match_two_surnames():
    md = _map_driver(
        _driver("JERSSON STIVEN MEDINA ROBAYO"), "JERSSON MEDINA"
    )
    assert md.is_owner is True


def test_owner_no_match_different_first_name():
    md = _map_driver(_driver("JUAN GARCIA"), "JOSE GARCIA")
    assert md.is_owner is False


def test_owner_no_match_no_shared_surname():
    md = _map_driver(_driver("JOSE TORRES"), "JOSE GARCIA")
    assert md.is_owner is False


# ---------- license state normalization ----------

def test_license_state_abbreviation_expands():
    md = _map_driver(_driver("JOHN SMITH", license_state="TX"), None)
    assert md.license_state == "Texas"


def test_license_state_full_name_passes_through():
    md = _map_driver(_driver("JOHN SMITH", license_state="Texas"), None)
    assert md.license_state == "Texas"


def test_license_state_none_defaults_to_texas():
    md = _map_driver(_driver("JOHN SMITH", license_state=None), None)
    assert md.license_state == "Texas"


def test_license_state_other_abbreviation():
    md = _map_driver(_driver("JOHN SMITH", license_state="ga"), None)
    assert md.license_state == "Georgia"
