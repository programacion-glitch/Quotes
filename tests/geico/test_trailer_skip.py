"""Trailers must NOT be sent through GEICO's Add VEHICLE flow.

Live DIBOLL 2026-06-12: unit 2 was a Dry Van Trailer (VIN 3H3V...). Fed into
the vehicle entry form, GEICO's VIN decode returns nothing -> Year/Make/Model
stay empty -> validation silently blocks the submit and the wizard never
reaches the summary. The BlueQuote pipeline already distinguishes them
(VehicleProfile.is_trailer from the separate 'trailers' table), so the GEICO
mapper must skip trailers (recorded in skipped_trailers for a WARN) until the
Add Trailer flow (chooser value 'No') is mapped.
"""

from __future__ import annotations

from modules.geico.field_mapper import map_profile_to_fields
from modules.quote_profile import (
    ApplicantProfile,
    QuoteProfile,
    UnitsProfile,
    VehicleProfile,
)


def _profile(vehicles):
    return QuoteProfile(
        applicant=ApplicantProfile(
            business_name="DIBOLL LOGISTICS LLC",
            owner_name="ELENA EURIOLES",
            usdot="4573040",
            zip_code="75941",
        ),
        units=UnitsProfile(count=len(vehicles), vehicles=vehicles),
    )


TRACTOR = VehicleProfile(vin="1XKYDP9X4JJ180910", year=2018, make="KENWORTH",
                         is_trailer=False)
TRAILER = VehicleProfile(vin="3H3V532C4GT140066", year=2016,
                         trailer_type="DRY VAN TRAILER", is_trailer=True)


def test_trailer_unit_not_mapped_as_vehicle():
    fields = map_profile_to_fields(_profile([TRACTOR, TRAILER]))
    assert len(fields.vehicles) == 1
    assert fields.vehicles[0].vin == TRACTOR.vin


def test_skipped_trailers_recorded_for_warning():
    fields = map_profile_to_fields(_profile([TRACTOR, TRAILER]))
    assert len(fields.skipped_trailers) == 1
    assert "3H3V532C4GT140066" in fields.skipped_trailers[0]
    assert "DRY VAN TRAILER" in fields.skipped_trailers[0]


def test_no_trailers_means_no_skips():
    fields = map_profile_to_fields(_profile([TRACTOR]))
    assert fields.vehicles and fields.skipped_trailers == []


def test_all_trailers_leaves_vehicles_empty_and_critical():
    # A trailer-only profile cannot quote — missing_critical must flag it.
    fields = map_profile_to_fields(_profile([TRAILER]))
    assert fields.vehicles == []
    assert any("vehicles" in m for m in fields.missing_critical())
