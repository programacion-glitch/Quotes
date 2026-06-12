"""Owner-driver dedup (hallazgo SOLANO 2026-06-11).

GEICO's owner placeholder already leaves the owner as an ACTIVE driver
(Driver Summary showed 'OSCAR SOLANO | Owner | Active'). Adding the owner
again through Add Driver would duplicate him. The Add Driver loop must skip
is_owner records; the at-least-one-driver validation still counts them.
"""

from __future__ import annotations

import pytest

from modules.geico.field_mapper import MappedDriver, MappedFields
from modules.geico.quote_flow import addable_drivers


def _fields(drivers):
    return MappedFields(drivers=drivers)


def test_owner_driver_is_not_added_again():
    owner = MappedDriver(first_name="OSCAR", last_name="SOLANO",
                         is_owner=True, is_excluded=False)
    fields = _fields([owner])
    assert addable_drivers(fields) == []  # placeholder already covers him


def test_non_owner_drivers_are_added():
    owner = MappedDriver(first_name="HUMBERTO", last_name="VILLARREAL",
                         is_owner=True, is_excluded=True)
    employee = MappedDriver(first_name="CLIFTON", last_name="THOMAS",
                            is_owner=False, is_excluded=False)
    fields = _fields([owner, employee])
    assert addable_drivers(fields) == [employee]


def test_excluded_non_owner_not_added():
    excluded = MappedDriver(first_name="JOE", last_name="DOE",
                            is_owner=False, is_excluded=True)
    driver = MappedDriver(first_name="ANA", last_name="RUIZ",
                          is_owner=False, is_excluded=False)
    fields = _fields([excluded, driver])
    assert addable_drivers(fields) == [driver]


def test_owner_only_quote_is_still_quotable():
    # The validation requirement (>=1 non-excluded driver) counts the owner
    # even though he is not re-added.
    owner = MappedDriver(first_name="OSCAR", last_name="SOLANO",
                         is_owner=True, is_excluded=False)
    fields = _fields([owner])
    assert fields.missing_critical() == [] or \
        "at least one non-excluded driver" not in fields.missing_critical()
