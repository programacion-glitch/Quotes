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

# Trailer/truck MAKE abbreviations -> full manufacturer name. Blue Quotes
# abbreviate the make ('GD' = Great Dane, 'PTRB' = Peterbilt). Some are not a
# prefix of the full name ('GD' -> 'Great Dane'), so neither safe_select_combo's
# substring match nor the typeahead-by-prefix can find them — we expand here
# first. Keyed by the make's FIRST token, uppercased. The combo match stays
# tolerant, so an approximate full name ('Great Dane' vs 'Great Dane Trailers')
# still resolves.
MAKE_ALIASES = {
    "GD": "Great Dane",
    "GDAN": "Great Dane",
    "GREATDANE": "Great Dane",
    "UTIL": "Utility",
    "BIGT": "Big Tex",
    "WAB": "Wabash",
    "WANC": "Wabash",
    "WAN": "Wabash",
    "STOU": "Stoughton",
    "DORS": "Dorsey",
    "FONT": "Fontaine",
    "MANAC": "Manac",
    "HEIL": "Heil",
    "POLA": "Polar",
    "POLAR": "Polar",
    "TRAI": "Trail King",
    "PTRB": "Peterbilt",
    "PB": "Peterbilt",
    "KW": "Kenworth",
    "FRHT": "Freightliner",
    "FRT": "Freightliner",
    "INTL": "International",
    "VNL": "Volvo",
}


def expand_make(make):
    """Expand a Blue-Quote make abbreviation to its full manufacturer name via
    MAKE_ALIASES (keyed by the first token). Returns the original string when no
    alias applies."""
    if not make:
        return make
    first = make.strip().upper().split()[0] if make.strip() else ""
    return MAKE_ALIASES.get(first, make)


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


# R-015 (Diana 2026-08-03 + mapping completo 2026-08-04): la clasificación
# sigue a la OPERACIÓN. Cuando el commodity es genérico/mixto/ausente/sin
# match, el subtipo Type-of-Trucker se deriva del tipo de unidad:
#   dry van / flatbed → General Freight / Other (validado con captura)
#   reefer → Refrigerated Goods · auto hauler → Auto Hauler
#   tank / cement mixer → Trucker + 'Other for hire'
#   dump → Dirt, Sand and Gravel o Scrap Metal SEGÚN el commodity
_SUBTYPE_BY_UNIT = (
    ("REEFER", "Refrigerated Goods"),
    ("REFRIGERATED", "Refrigerated Goods"),
    ("DRY VAN", "General Freight / Other"),
    ("FLATBED", "General Freight / Other"),
    ("AUTO HAULER", "Auto Hauler"),
    ("CAR HAULER", "Auto Hauler"),
    ("TANK", "Other for hire"),
    ("CEMENT", "Other for hire"),
    ("MIXER", "Other for hire"),
)


def subtype_from_unit_hints(
    unit_hints, commodity: Optional[str] = None
) -> Tuple[Optional[str], Optional[str]]:
    """Return (Type-of-Trucker label | None, unit hint que disparó | None).

    DUMP se resuelve por el commodity (Diana 2026-08-04): scrap → Scrap
    Metal; arena/grava → Dirt, Sand and Gravel; sin señal → sin veredicto.
    """
    c = (commodity or "").upper()
    for h in (unit_hints or []):
        hu = (h or "").upper()
        if "DUMP" in hu:
            if "SCRAP" in c:
                return ("Scrap Metal", h)
            if any(k in c for k in ("ARENA", "GRAVA", "SAND", "GRAVEL", "DIRT")):
                return ("Dirt, Sand and Gravel", h)
            continue  # dump sin señal en el commodity: sin veredicto
        for key, label in _SUBTYPE_BY_UNIT:
            if key in hu:
                return label, h
    return (None, None)


def radius_exceeds_500(radius_strs) -> bool:
    """True si algún radio indica MÁS de 500 millas (R-002, Diana 2026-08-04:
    >500 → filing federal; ≤500 → estatal). 'Unlimited' cuenta como >500."""
    for s in (radius_strs or []):
        t = str(s or "").lower()
        if "unlimit" in t or "ilimit" in t:
            return True
        m = re.search(r"(?:more than|over)\s+(\d+)", t)
        if m and int(m.group(1)) >= 500:
            return True
        nums = [int(n) for n in re.findall(r"\d+", t)]
        if nums and min(nums) > 500:
            return True
    return False
