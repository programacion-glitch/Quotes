"""nearest_distance_option: pickups expose a TRIMMED distance option set
(starts at '101-200' — live ON THE GO 2026-06-11); when the desired bucket
is absent, pick the nearest available at-or-above it."""

from __future__ import annotations

from modules.geico.pages.vehicles_page import nearest_distance_option

PICKUP_OPTS = ["Please Select", "101-200", "201-300", "301-500",
               "More than 500"]
FULL_OPTS = ["Please Select", "0-25", "26-50", "51-100", "101-200",
             "201-300", "301-500", "More than 500"]


def test_desired_present_is_returned():
    assert nearest_distance_option("51-100", FULL_OPTS) == "51-100"

def test_desired_below_trimmed_set_picks_first_available():
    assert nearest_distance_option("51-100", PICKUP_OPTS) == "101-200"

def test_desired_above_picks_it():
    assert nearest_distance_option("301-500", PICKUP_OPTS) == "301-500"

def test_more_than_500():
    assert nearest_distance_option("More than 500", PICKUP_OPTS) == "More than 500"

def test_unknown_desired_falls_back_to_first_real_option():
    assert nearest_distance_option("weird", PICKUP_OPTS) == "101-200"

def test_placeholder_never_returned():
    assert nearest_distance_option("0-25", ["Please Select", "0-25"]) == "0-25"
