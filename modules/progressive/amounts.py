"""Money/weight string normalizer. Handles US ('$45,000.00') and latino
('$45.000') number formats, disambiguating by context. Pure, no state."""

from __future__ import annotations

import re
from typing import Optional


def parse_amount(raw: Optional[str]) -> Optional[float]:
    """Normalize a messy amount/weight string to a number, or None.

    '51.000 LBS' -> 51000 · '$45,000.00' -> 45000.0 · '$45.000' -> 45000
    '45.5' -> 45.5 · '1.500.000' -> 1500000 · ''/garbage -> None
    """
    if raw is None:
        return None
    # Keep only digits and the two separators.
    s = re.sub(r"[^0-9.,]", "", str(raw))
    if not re.search(r"\d", s):
        return None

    has_dot = "." in s
    has_comma = "," in s

    if has_dot and has_comma:
        # The separator that appears LAST is the decimal; the other is thousands.
        dec = "." if s.rfind(".") > s.rfind(",") else ","
        tho = "," if dec == "." else "."
        s = s.replace(tho, "").replace(dec, ".")
        return _to_number(s)

    sep = "." if has_dot else ("," if has_comma else None)
    if sep is None:
        return _to_number(s)

    if s.count(sep) > 1:
        # Multiple occurrences -> thousands separator.
        return _to_number(s.replace(sep, ""))

    # Single occurrence: 3 digits after -> thousands; 1-2 -> decimal; 4+ -> decimal.
    before, after = s.split(sep)[0], s.split(sep)[1]
    # 3 digits after -> thousands separator (e.g. "51.000" -> 51000),
    # EXCEPT when the integer part is just "0" (e.g. "0.001"), which is a
    # genuine fraction, not 0 thousands.
    if len(after) == 3 and before.strip("0") != "":
        return _to_number(s.replace(sep, ""))
    return _to_number(s.replace(sep, ".") if sep == "," else s)


def _to_number(s: str) -> Optional[float]:
    try:
        f = float(s)
    except ValueError:
        return None
    return int(f) if f == int(f) else f
