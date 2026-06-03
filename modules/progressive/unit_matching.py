"""Pure helpers for matching vehicle/trailer units across the PDF↔Progressive boundary.

These functions have no Playwright dependency so they are unit-tested in
isolation. Used by quote_flow._add_all_vehicles to detect units that
Progressive already has on the quote (from a prior run for the same USDOT)
and skip duplicating them.
"""

from __future__ import annotations

import re
from typing import Optional

# Markers that look like a VIN field but are not real VINs. "" entry is
# defensive — the truthiness check on the caller path already excludes it,
# but listing it here makes the intent visible alongside the named markers.
NON_OWNED_MARKERS = frozenset({"NON OWNED", "NONOWNED", "NON-OWNED", "N/A", ""})

# Standard VIN: 17 characters from A-Z (excluding I, O, Q) and 0-9.
_VIN_PATTERN = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")


def normalize_identifier(
    vin: Optional[str],
    year: Optional[int],
    make: Optional[str],
    model: Optional[str],
) -> Optional[str]:
    """Compose a stable identifier for matching units PDF↔Progressive.

    Priority:
      1. Real VIN (17 chars in standard VIN alphabet, not a NON_OWNED marker)
      2. f"{year}|{MAKE}|{MODEL}" if all three are present after stripping
      3. None — insufficient identity; caller will NOT skip the unit
    """
    vin_clean = (vin or "").strip().upper()
    if vin_clean and vin_clean not in NON_OWNED_MARKERS and _VIN_PATTERN.match(vin_clean):
        return vin_clean

    if year is not None and make and model:
        make_norm = make.strip().upper()
        model_norm = model.strip().upper()
        if make_norm and model_norm:
            return f"{year}|{make_norm}|{model_norm}"

    return None
