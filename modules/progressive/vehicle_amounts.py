"""Numeric AddVehicle-field resolvers: GVW range bucketing and vehicle-value
validation. Both fail loud (UnmappableValueError) ONLY for present-but-unusable
data; absent values use documented defaults / no-APD."""

from __future__ import annotations

import re
from typing import Optional

from modules.progressive.amounts import parse_amount
from modules.progressive.pages._exceptions import UnmappableValueError

GVW_DEFAULT = "26,001 lbs or greater"


def _label_to_range(label: str) -> tuple[float, float]:
    """Parse a GVW option label into (min, max) inclusive numeric bounds.

      '26,001 lbs or greater' -> (26001, inf)
      '10,000 lbs or less'    -> (0, 10000)
      '10,001 - 26,000 lbs'   -> (10001, 26000)
    """
    low = label.lower()
    nums = [parse_amount(n) for n in re.findall(r"[\d.,]+", label)]
    nums = [n for n in nums if n is not None]
    if not nums:
        return (0.0, float("inf"))
    if "greater" in low or "more" in low or "over" in low:
        return (nums[0], float("inf"))
    if "less" in low or "under" in low:
        return (0.0, nums[0])
    if len(nums) >= 2:
        return (nums[0], nums[1])
    # Single number, no qualifier — treat as exact-or-greater (defensive).
    return (nums[0], float("inf")) if nums else (0.0, float("inf"))


def bucket_gvw(weight: float, options: list[str]) -> str:
    """Return the option whose numeric range contains `weight`, or HALT."""
    for opt in options:
        lo, hi = _label_to_range(opt)
        if lo <= weight <= hi:
            return opt
    raise UnmappableValueError(
        field="Gross vehicle weight",
        source_value=str(weight),
        available_options=list(options),
    )


def resolve_gvw(
    gvw_raw: Optional[str],
    options: list[str],
    *,
    default: str = GVW_DEFAULT,
    screenshot_path: Optional[str] = None,
) -> str:
    """Resolve a raw Blue-Quote GVW string to a Progressive range option.

    absent -> default (assumption). present+parses -> bucket_gvw.
    present but unparseable -> HALT.
    """
    if not (gvw_raw and str(gvw_raw).strip()):
        return default
    weight = parse_amount(gvw_raw)
    if weight is None:
        raise UnmappableValueError(
            field="Gross vehicle weight",
            source_value=gvw_raw,
            available_options=list(options),
            screenshot_path=screenshot_path,
        )
    try:
        return bucket_gvw(weight, options)
    except UnmappableValueError:
        raise UnmappableValueError(
            field="Gross vehicle weight",
            source_value=gvw_raw,
            available_options=list(options),
            screenshot_path=screenshot_path,
        )
