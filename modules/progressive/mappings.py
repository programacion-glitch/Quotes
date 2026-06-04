"""Shared Blue-Quote -> Progressive option mappings (used by pages + preflight)."""

from __future__ import annotations

import re
from typing import Optional, Tuple

# Vehicle-tile synonyms (token -> Progressive tile label).
VEHICLE_TILE_MAP = {
    "FLATBED": "Flatbed Truck",
    "BOX": "Box Truck",
    "STRAIGHT": "Box Truck",
    "DRY VAN": "Box Truck",
    "REEFER": "Box Truck",
    "PICKUP": "Pickup Truck",
    "CARGO": "Cargo Van",
    "VAN": "Cargo Van",
    "TRACTOR": "Truck Tractor",
    "DUMP": "Dump Truck",
}

# Trailer-tile synonyms (token -> Progressive trailer tile label).
# Matched as `token in trailer_type.upper()` (same scheme as VEHICLE_TILE_MAP).
# Order note: "DRY VAN"/"DRY FREIGHT" listed before generic terms; there is no
# bare "VAN" key here so no Cargo-Van collision.
TRAILER_TILE_MAP = {
    "GOOSENECK": "Gooseneck Trailer",
    "FLATBED": "Flatbed Trailer",
    "DRY VAN": "Dry Freight Trailer",
    "DRY FREIGHT": "Dry Freight Trailer",
    "REEFER": "Refrigerated Dry Freight",
    "REFRIGERAT": "Refrigerated Dry Freight",
}

# Commodity table: (synonym keys, Progressive Business-type option).
_COMMODITY_TABLE = [
    (("FRACK", "FRACKING"), "Fracking Sand Hauling"),
    (("DIRT", "SAND", "GRAVEL"), "Dirt Sand & Gravel (For A Fee)"),
    (("COAL",), "Coal Hauling"),
    (("AUTO HAUL", "CAR HAUL", "AUTO HAULER", "CAR HAULER"),
     "Auto Hauler (For Hire Trucking)"),
    (("LIVESTOCK",), "Livestock Hauling (For A Fee)"),
    (("LOG", "LOGGING", "WOOD CHIP", "WOOD CHIPS"), "Logging Trucker"),
    (("GARBAGE", "TRASH"), "Garbage & Trash Hauling/Removal"),
    (("HAZARD", "HAZMAT", "HAZARDOUS"), "Hazardous Materials Hauling"),
    (("CONTAINER", "CONTAINERS"), "Container Hauling"),
    (("AGRICULTURAL", "AGRICULTURE", "FARM PRODUCE"),
     "Agricultural Hauling (For A Fee)"),
    (("DAIRY",), "Dairy Products Hauling (For A Fee)"),
    (("REFRIG", "REFRIGERATED", "REEFER", "FROZEN"), "Frozen Foods Hauling"),
    # NOTE: "WATER" maps to Beverage Distributor as a known approximation
    # (inherited; water/liquid tanker hauling is technically distinct).
    (("BEVERAGE", "BEER", "WATER", "LIQUIDS", "BOTTLED"), "Beverage Distributor"),
]

_GENERAL_FREIGHT_KEYS = ("FLATBED", "DRY VAN", "BOX TRUCK", "STRAIGHT",
                         "CARGO VAN", "FREIGHT", "GENERAL")


def map_commodity(commodity: Optional[str]) -> Tuple[Optional[str], bool]:
    """Return (Progressive option | None, is_generic).

    Word-boundary matching: 'PACKED CHARCOAL' does NOT trigger 'COAL'.
    - specific hit -> (option, False)
    - general-freight family -> ('General Freight Hauler', True)
    - nothing -> (None, False)   # caller HALTs
    """
    c = (commodity or "").upper()

    # field_mapper defaults an absent-commodity quote to the "Trucker" sentinel
    # (USDOT present). That is a valid generic business-type selection the live
    # page already uses — treat it as a generic match, not an unmappable value.
    if c.strip() == "TRUCKER":
        return ("Trucker", True)

    tokens = set(re.findall(r"\b[A-Z][A-Z0-9]+\b", c))

    def matches(key: str) -> bool:
        parts = key.split()
        if len(parts) == 1:
            return parts[0] in tokens
        pattern = r"\b" + r"\W+".join(re.escape(p) for p in parts) + r"\b"
        return re.search(pattern, c) is not None

    for keys, opt in _COMMODITY_TABLE:
        if any(matches(k) for k in keys):
            return (opt, False)
    if any(matches(k) for k in _GENERAL_FREIGHT_KEYS):
        return ("General Freight Hauler", True)
    # Mixed/percentage-split load with no dominant specialty -> generic Trucker
    # (general freight). E.g. "Processed wood 33%, pipes 33%, Building Materials
    # 34%": two or more percentage shares and no single specialty keyword above
    # means it's hauled as general freight. Routes to the live-validated
    # "Trucker" path (M&D baseline -> Type-of-Trucker 'General Freight / Other'),
    # not the unvalidated "General Freight Hauler" option.
    if len(re.findall(r"\d+\s*%", c)) >= 2:
        return ("Trucker", True)
    return (None, False)
