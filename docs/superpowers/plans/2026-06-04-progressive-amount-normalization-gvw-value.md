# Progressive Amount Normalization + GVW/Value Fail-Loud Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the bot process messy Blue Quote numbers (US `$45,000.00` AND latino `$45.000`) and resolve GVW + vehicle value correctly, failing loud only when a present value is genuinely unusable — so REPUBLIC AGGREGATE-style quotes (`"51.000 LBS"`, `"$45.000"`) process and quote instead of breaking at AddVehicle.

**Architecture:** A pure `parse_amount` normalizer disambiguates US/latino number formats. A `vehicle_amounts` module turns a parsed GVW weight into the matching Progressive range bucket (`resolve_gvw`) and validates the vehicle value (`resolve_vehicle_value`), both raising `UnmappableValueError` only for present-but-unusable data. field_mapper stores raw values; preflight pre-checks them offline; vehicles_page resolves against live combo options and fails loud instead of WARN-and-continue.

**Tech Stack:** Python 3, dataclasses, pytest (async tests already configured), Playwright (async). No new dependencies. Builds on the prior fail-loud feature (`choice_resolver`, `catalogs`, `preflight`, `UnmappableValueError`).

---

## File Structure

- **Create** `modules/progressive/amounts.py` — `parse_amount(raw) -> float | None`. Pure number normalizer.
- **Create** `modules/progressive/vehicle_amounts.py` — `bucket_gvw`, `resolve_gvw`, `resolve_vehicle_value`. Numeric AddVehicle-field resolvers (consolidates the spec's `gvw.py` plus value validation, same family). Imports `parse_amount` + `UnmappableValueError`.
- **Create** `modules/progressive/catalogs/gvw.json` — GVW combo options (initial seed; refined via DIAG in Task 8).
- **Modify** `modules/progressive/field_mapper.py` — `_map_vehicle` stores raw GVW + raw value (drops the old digits-only value normalization); `MappedVehicle.gvw` becomes the raw string.
- **Modify** `modules/progressive/preflight.py` — add `_check_gvw`, `_check_value`.
- **Modify** `modules/progressive/pages/vehicles_page.py` — GVW via `resolve_gvw` over live options; value via `resolve_vehicle_value`; both fail loud. Temporary GVW DIAG dump (removed in Task 8).
- **Modify** `tests/progressive/test_catalogs.py` — register `"gvw"`.
- **Create** tests: `test_amounts.py`, `test_gvw_bucket.py`, `test_value_validation.py`; extend `test_preflight.py`.

---

## Task 1: `parse_amount` normalizer

**Files:**
- Create: `modules/progressive/amounts.py`
- Test: `tests/progressive/test_amounts.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/progressive/test_amounts.py
import pytest
from modules.progressive.amounts import parse_amount


@pytest.mark.parametrize("raw,expected", [
    ("51.000 LBS", 51000),       # latino thousands + unit
    ("$45.000", 45000),          # latino thousands + currency
    ("$45,000.00", 45000.0),     # US thousands + decimal cents
    ("$45.000,50", 45000.5),     # latino thousands + decimal cents
    ("1.500.000", 1500000),      # latino, multiple separators
    ("1,500,000", 1500000),      # US, multiple separators
    ("1,500", 1500),             # single comma, 3 digits -> thousands
    ("45.5", 45.5),              # single dot, 1 digit -> decimal
    ("45.00", 45.0),             # single dot, 2 digits -> decimal (cents)
    ("45.000", 45000),           # single dot, 3 digits -> thousands
    ("26001", 26001),            # plain integer
    ("$0", 0),                   # zero
])
def test_parse_amount_formats(raw, expected):
    assert parse_amount(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", None, "banana", "$", "LBS", "N/A"])
def test_parse_amount_unparseable_returns_none(raw):
    assert parse_amount(raw) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/progressive/test_amounts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'modules.progressive.amounts'`

- [ ] **Step 3: Implement `amounts.py`**

```python
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
    after = s.split(sep)[1]
    if len(after) == 3:
        return _to_number(s.replace(sep, ""))
    return _to_number(s.replace(sep, ".") if sep == "," else s)


def _to_number(s: str) -> Optional[float]:
    try:
        f = float(s)
    except ValueError:
        return None
    return int(f) if f == int(f) else f
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/progressive/test_amounts.py -v`
Expected: PASS (18 cases)

- [ ] **Step 5: Commit**

```bash
git add modules/progressive/amounts.py tests/progressive/test_amounts.py
git commit -m "feat(progressive): parse_amount normalizer (US + latino number formats)"
```

---

## Task 2: GVW bucket + `resolve_gvw`

**Files:**
- Create: `modules/progressive/vehicle_amounts.py`
- Test: `tests/progressive/test_gvw_bucket.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/progressive/test_gvw_bucket.py
import pytest
from modules.progressive.vehicle_amounts import bucket_gvw, resolve_gvw
from modules.progressive.pages._exceptions import UnmappableValueError

OPTS = ["10,000 lbs or less", "10,001 - 26,000 lbs", "26,001 lbs or greater"]


def test_bucket_high_weight():
    assert bucket_gvw(51000, OPTS) == "26,001 lbs or greater"


def test_bucket_low_weight():
    assert bucket_gvw(8000, OPTS) == "10,000 lbs or less"


def test_bucket_mid_weight():
    assert bucket_gvw(15000, OPTS) == "10,001 - 26,000 lbs"


def test_bucket_boundary_inclusive():
    assert bucket_gvw(26000, OPTS) == "10,001 - 26,000 lbs"
    assert bucket_gvw(26001, OPTS) == "26,001 lbs or greater"


def test_resolve_gvw_present_weight_buckets():
    assert resolve_gvw("51.000 LBS", OPTS) == "26,001 lbs or greater"


def test_resolve_gvw_absent_uses_default():
    assert resolve_gvw(None, OPTS) == "26,001 lbs or greater"
    assert resolve_gvw("", OPTS) == "26,001 lbs or greater"


def test_resolve_gvw_present_but_garbage_halts():
    with pytest.raises(UnmappableValueError) as exc:
        resolve_gvw("banana", OPTS)
    assert exc.value.source_value == "banana"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/progressive/test_gvw_bucket.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'modules.progressive.vehicle_amounts'`

- [ ] **Step 3: Implement `vehicle_amounts.py` (GVW portion)**

```python
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
    screenshot_path=None,
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/progressive/test_gvw_bucket.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add modules/progressive/vehicle_amounts.py tests/progressive/test_gvw_bucket.py
git commit -m "feat(progressive): GVW range bucketing + resolve_gvw (fail-loud)"
```

---

## Task 3: `resolve_vehicle_value` validation

**Files:**
- Modify: `modules/progressive/vehicle_amounts.py`
- Test: `tests/progressive/test_value_validation.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/progressive/test_value_validation.py
import pytest
from modules.progressive.vehicle_amounts import resolve_vehicle_value
from modules.progressive.pages._exceptions import UnmappableValueError


def test_value_present_processes():
    assert resolve_vehicle_value("$45.000") == 45000   # latino -> 45000


def test_value_us_format_processes():
    assert resolve_vehicle_value("$45,000.00") == 45000.0


def test_value_absent_is_none_no_apd():
    assert resolve_vehicle_value(None) is None
    assert resolve_vehicle_value("") is None


def test_value_zero_is_none_no_apd():
    assert resolve_vehicle_value("$0") is None
    assert resolve_vehicle_value("0") is None


def test_value_below_floor_halts():
    # the mis-parsed "$45" case: present, parses, but < $100 -> HALT
    with pytest.raises(UnmappableValueError) as exc:
        resolve_vehicle_value("$45")
    assert exc.value.source_value == "$45"


def test_value_garbage_halts():
    with pytest.raises(UnmappableValueError):
        resolve_vehicle_value("banana")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/progressive/test_value_validation.py -v`
Expected: FAIL with `ImportError: cannot import name 'resolve_vehicle_value'`

- [ ] **Step 3: Add `resolve_vehicle_value` to `vehicle_amounts.py`**

```python
VALUE_FLOOR = 100   # Progressive: "The vehicle value must be greater than $100."


def resolve_vehicle_value(
    raw: Optional[str], *, floor: float = VALUE_FLOOR, screenshot_path=None
) -> Optional[float]:
    """Validate a raw Blue-Quote vehicle value.

    absent / zero -> None (no APD). present & >= floor -> the number.
    present but unparseable OR 0 < value < floor -> HALT.
    """
    if not (raw and str(raw).strip()):
        return None
    num = parse_amount(raw)
    if num is None:
        raise UnmappableValueError(
            field="Vehicle value", source_value=raw,
            available_options=[], screenshot_path=screenshot_path,
        )
    if num == 0:
        return None
    if num < floor:
        raise UnmappableValueError(
            field="Vehicle value", source_value=raw,
            available_options=[f"must be greater than ${floor}"],
            screenshot_path=screenshot_path,
        )
    return num
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/progressive/test_value_validation.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add modules/progressive/vehicle_amounts.py tests/progressive/test_value_validation.py
git commit -m "feat(progressive): resolve_vehicle_value validation (fail-loud, $100 floor)"
```

---

## Task 4: GVW catalog

**Files:**
- Create: `modules/progressive/catalogs/gvw.json`
- Modify: `tests/progressive/test_catalogs.py`

- [ ] **Step 1: Write the failing test change**

In `tests/progressive/test_catalogs.py`, add `"gvw"` to the `NAMES` list (around the top):

```python
NAMES = ["type_of_trucker", "vehicle_tiles", "business_type", "gvw"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/progressive/test_catalogs.py -v`
Expected: FAIL — `gvw` parametrization errors (file not found).

- [ ] **Step 3: Create `modules/progressive/catalogs/gvw.json`**

Initial seed (standard Progressive commercial GVW buckets; Task 8 confirms/corrects via DIAG):

```json
{
  "field": "Gross vehicle weight",
  "captured": "2026-06-04",
  "source": "initial seed — confirm via DIAG (Task 8)",
  "options": [
    "10,000 lbs or less",
    "10,001 - 26,000 lbs",
    "26,001 lbs or greater"
  ],
  "generic_aliases": []
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/progressive/test_catalogs.py -v`
Expected: PASS (now includes `gvw`).

- [ ] **Step 5: Commit**

```bash
git add modules/progressive/catalogs/gvw.json tests/progressive/test_catalogs.py
git commit -m "feat(progressive): GVW options catalog (seed; DIAG-confirmed in Task 8)"
```

---

## Task 5: field_mapper stores raw GVW + raw value

**Files:**
- Modify: `modules/progressive/field_mapper.py` (`MappedVehicle` ~line 20-39, `_map_vehicle` ~line 144-171)
- Test: `tests/progressive/test_field_mapper_amounts.py`

Context: today `_map_vehicle` sets `gvw=v.gvw or "26,001 lbs or greater"` (a label) and normalizes value to a digits string. We move both decisions to the resolvers (Tasks 2-3), so the mapper now stores the RAW strings and lets `resolve_gvw`/`resolve_vehicle_value` decide later. APD intent is computed from `resolve_vehicle_value` at the page, not `bool(value)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/progressive/test_field_mapper_amounts.py
from modules.quote_profile import VehicleProfile
from modules.progressive.field_mapper import _map_vehicle


def test_map_vehicle_keeps_raw_gvw_and_value():
    v = VehicleProfile(vin="X", gvw="51.000 LBS", value="$45.000")
    mv = _map_vehicle(v, fallback_zip="77055", fallback_type="FLATBED")
    assert mv.gvw == "51.000 LBS"     # raw preserved (resolved later)
    assert mv.value == "$45.000"      # raw preserved (resolved later)


def test_map_vehicle_absent_gvw_is_none():
    v = VehicleProfile(vin="X")
    mv = _map_vehicle(v, fallback_zip=None, fallback_type="FLATBED")
    assert mv.gvw is None             # absent -> resolve_gvw will default it
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/progressive/test_field_mapper_amounts.py -v`
Expected: FAIL (current `_map_vehicle` sets gvw to a label and normalizes value).

- [ ] **Step 3: Update `MappedVehicle` and `_map_vehicle`**

In `field_mapper.py`, change the `MappedVehicle` field defaults:

```python
    gvw: Optional[str] = None       # raw Blue Quote GVW; resolved by resolve_gvw
    radius_miles: str = "Over 500 miles"
```
(Remove the old `gvw: str = "26,001 lbs or greater"` default. Keep `value: Optional[str] = None` — it now holds the RAW value.)

In `_map_vehicle`, REMOVE the value-normalization block (the `value_normalized` digits logic) and the `gvw=v.gvw or "26,001 lbs or greater"` line. Replace the relevant parts of the returned `MappedVehicle` with:

```python
    return MappedVehicle(
        vin=v.vin,
        year=v.year,
        make=v.make,
        model=v.model,
        trailer_type=(v.trailer_type or fallback_type or "FLATBED"),
        gvw=(v.gvw or None),               # raw; resolve_gvw defaults if absent
        radius_miles=v.radius_miles or "Over 500 miles",
        has_loan=has_loan,
        garaging_zip=v.garaging_zip or fallback_zip,
        value=(v.value or None),           # raw; resolve_vehicle_value validates
        is_trailer=v.is_trailer,
    )
```

- [ ] **Step 4: Run the new test + full suite**

Run: `python -m pytest tests/progressive/test_field_mapper_amounts.py tests/progressive/ -q`
Expected: the two new tests PASS. If any EXISTING test asserted the old `gvw="26,001 lbs or greater"` default or a normalized `value` (e.g. `"$80,000"` -> `"80000"`), update that test to expect the raw value now (the resolution moved downstream). List and fix each. The suite must end green.

- [ ] **Step 5: Commit**

```bash
git add modules/progressive/field_mapper.py tests/progressive/test_field_mapper_amounts.py
git commit -m "refactor(progressive): field_mapper stores raw GVW/value (resolution moved downstream)"
```

---

## Task 6: preflight checks GVW + value

**Files:**
- Modify: `modules/progressive/preflight.py`
- Test: `tests/progressive/test_preflight.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/progressive/test_preflight.py`:

```python
def test_preflight_republic_normalizes_and_passes():
    # REPUBLIC: latino GVW + value -> must PROCESS (no blocker)
    f = MappedFields(
        usdot="1", business_name="REPUBLIC LLC", effective_date="06/15/2026",
        owner_name="O", commodity="SAND & GRAVEL 100%",
        vehicles=[MappedVehicle(trailer_type="DUMP TRUCK", gvw="51.000 LBS", value="$45.000")],
    )
    rep = run_preflight(f)
    assert rep.ok()


def test_preflight_blocks_unusable_value():
    f = MappedFields(
        usdot="1", business_name="X LLC", effective_date="06/15/2026",
        owner_name="O", commodity="Trucker",
        vehicles=[MappedVehicle(trailer_type="FLATBED", value="$45")],  # < $100
    )
    rep = run_preflight(f)
    assert not rep.ok()
    assert any(b.field == "Vehicle value" for b in rep.blockers)


def test_preflight_blocks_garbage_gvw():
    f = MappedFields(
        usdot="1", business_name="X LLC", effective_date="06/15/2026",
        owner_name="O", commodity="Trucker",
        vehicles=[MappedVehicle(trailer_type="FLATBED", gvw="banana")],
    )
    rep = run_preflight(f)
    assert not rep.ok()
    assert any(b.field == "Gross vehicle weight" for b in rep.blockers)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/progressive/test_preflight.py -k "republic or unusable or garbage" -v`
Expected: FAIL (no GVW/value checks yet — garbage/low value not detected).

- [ ] **Step 3: Add the checks to `preflight.py`**

Add imports near the top:

```python
from modules.progressive.catalogs import load_catalog
from modules.progressive.vehicle_amounts import resolve_gvw, resolve_vehicle_value
from modules.progressive.pages._exceptions import UnmappableValueError
```

Add two check functions and call them in `run_preflight`:

```python
def _check_gvw(mapped: MappedFields, rep: PreflightReport) -> None:
    cat = load_catalog("gvw")
    for i, v in enumerate(mapped.vehicles):
        try:
            resolve_gvw(v.gvw, list(cat.options))
        except UnmappableValueError as e:
            rep.blockers.append(Blocker(
                field="Gross vehicle weight",
                source_value=f"vehicle[{i}]: {e.source_value}",
                available_options=list(cat.options),
                suggestion="GVW present but not parseable / out of range — fix the Blue Quote.",
            ))


def _check_value(mapped: MappedFields, rep: PreflightReport) -> None:
    for i, v in enumerate(mapped.vehicles):
        try:
            resolve_vehicle_value(v.value)
        except UnmappableValueError as e:
            rep.blockers.append(Blocker(
                field="Vehicle value",
                source_value=f"vehicle[{i}]: {e.source_value}",
                available_options=list(e.available_options),
                suggestion="Vehicle value present but unusable (< $100 or garbage) — fix the Blue Quote.",
            ))
```

In `run_preflight`, after the existing checks, add:

```python
    _check_gvw(mapped, rep)
    _check_value(mapped, rep)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/progressive/test_preflight.py -q`
Expected: PASS (all preflight tests, including the 3 new).

- [ ] **Step 5: Commit**

```bash
git add modules/progressive/preflight.py tests/progressive/test_preflight.py
git commit -m "feat(progressive): preflight checks GVW + vehicle value"
```

---

## Task 7: vehicles_page — fail-loud GVW + value (with temporary DIAG)

**Files:**
- Modify: `modules/progressive/pages/vehicles_page.py` (`AddVehiclePage.fill_from_mapped` ~line 379-381 GVW; `_fill_vehicle_value` / APD block ~line 419-453; `_set_combobox_by_label` ~647)
- Test: `tests/progressive/test_addvehicle_gvw_value.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/progressive/test_addvehicle_gvw_value.py
import pytest
from modules.progressive.pages.vehicles_page import AddVehiclePage
from modules.progressive.pages._exceptions import UnmappableValueError


def _page(gvw_options):
    obj = AddVehiclePage.__new__(AddVehiclePage)

    async def _enum():
        return gvw_options
    obj._enumerate_gvw_options = _enum

    async def _shot(name):
        return None
    obj.screenshot = _shot
    return obj


@pytest.mark.asyncio
async def test_resolve_gvw_label_buckets_live():
    page = _page(["10,000 lbs or less", "10,001 - 26,000 lbs", "26,001 lbs or greater"])
    label = await page.resolve_gvw_label("51.000 LBS")
    assert label == "26,001 lbs or greater"


@pytest.mark.asyncio
async def test_resolve_gvw_label_absent_defaults():
    page = _page(["10,000 lbs or less", "26,001 lbs or greater"])
    label = await page.resolve_gvw_label(None)
    assert label == "26,001 lbs or greater"


@pytest.mark.asyncio
async def test_resolve_gvw_label_garbage_halts():
    page = _page(["26,001 lbs or greater"])
    with pytest.raises(UnmappableValueError):
        await page.resolve_gvw_label("banana")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/progressive/test_addvehicle_gvw_value.py -v`
Expected: FAIL (`AttributeError: ... has no attribute 'resolve_gvw_label'`).

- [ ] **Step 3: Implement live GVW resolution in `AddVehiclePage`**

Add imports at the top of vehicles_page.py:

```python
from modules.progressive.vehicle_amounts import resolve_gvw, resolve_vehicle_value
```

Add these methods to `AddVehiclePage`:

```python
    async def _enumerate_gvw_options(self) -> list:
        """Open the GVW combo and read its real option labels."""
        combo = await self.find_combo("What is the gross vehicle weight?")
        if await combo.count() == 0:
            return []
        try:
            await combo.click(timeout=5_000)
            await self.page.wait_for_timeout(300)
            raw = await self.page.get_by_role("option").all_inner_texts()
            return [o.strip() for o in raw if o.strip()]
        except Exception:
            return []

    async def resolve_gvw_label(self, gvw_raw) -> str:
        """Resolve the raw Blue-Quote GVW to a live combo option (or HALT)."""
        options = await self._enumerate_gvw_options()
        if not options:
            from modules.progressive.catalogs import load_catalog
            options = list(load_catalog("gvw").options)
        screenshot = await self.screenshot("gvw_unmapped")
        return resolve_gvw(gvw_raw, options, screenshot_path=screenshot)
```

Replace the GVW call in `fill_from_mapped` (the `_set_combobox_by_label("What is the gross vehicle weight?", vehicle.gvw)` call) with:

```python
        # GVW — resolve the raw value to a live range bucket, or HALT.
        gvw_label = await self.resolve_gvw_label(vehicle.gvw)
        combo = await self.find_combo("What is the gross vehicle weight?")
        if await combo.count() > 0:
            await self.safe_select_combo(combo, gvw_label)
        print(f"    [Progressive] GVW: {vehicle.gvw!r} -> {gvw_label!r}")

        # --- TEMPORARY DIAG (remove in Task 8): dump live GVW options ---
        try:
            _diag = await self._enumerate_gvw_options()
            print(f"    [Progressive] DIAG GVW options: {_diag}")
        except Exception:
            pass
        # --- END DIAG ---
```

In the APD block (where `wants_apd = bool(vehicle.value)` is computed), replace with `resolve_vehicle_value`:

```python
        if vehicle.has_loan == "No":
            screenshot = await self.screenshot("vehicle_value_unmapped")
            val = resolve_vehicle_value(vehicle.value, screenshot_path=screenshot)
            wants_apd = val is not None
            apd_answer = "Yes" if wants_apd else "No"
            await self._set_radio(
                "Does the customer need Comprehensive or Collision coverage",
                apd_answer,
            )
            try:
                await self.wait_for_extjs_idle(timeout_ms=4_000)
            except Exception:
                pass
            if wants_apd:
                await self._tick_no_equipment_checkbox()
                await self._fill_vehicle_value(default=str(int(val)))
            else:
                print(
                    "    [Progressive] APD = No (no usable Value for this "
                    "vehicle); skipping equipment + Vehicle Value section"
                )
```

(Keep `_fill_vehicle_value`'s signature; it now receives a clean integer string like `"45000"`.)

- [ ] **Step 4: Run tests + full suite**

Run: `python -m pytest tests/progressive/test_addvehicle_gvw_value.py tests/progressive/ -q`
Expected: the 3 new tests PASS; full suite green. If the simulator's mock needs a GVW option list for `all_inner_texts`, that is handled by the existing `all_inner_texts` stub returning TRUCKER_SUBTYPES — but GVW enumeration may return those; verify `python tests/simulate_progressive.py` still reports `success=True $53,064`. If the simulator's GVW combo now resolves via the mock and fails, update the simulator mock so `all_inner_texts` returns GVW labels when the combo is the GVW one (model faithfully — do not weaken production code). Confirm simulator green.

- [ ] **Step 5: Commit**

```bash
git add modules/progressive/pages/vehicles_page.py tests/progressive/test_addvehicle_gvw_value.py
git commit -m "feat(progressive): AddVehicle GVW + value fail-loud (live bucket + validation) + GVW DIAG"
```

---

## Task 8: Live DIAG capture, catalog refine, validation (NEEDS USER)

**Files:**
- Modify: `modules/progressive/catalogs/gvw.json` (refine from DIAG)
- Modify: `modules/progressive/pages/vehicles_page.py` (remove DIAG block)

- [ ] **Step 1: Live run REPUBLIC to capture real GVW options**

Run (user):
```powershell
$env:PYTHONIOENCODING="utf-8"
python -u scripts\run_progressive_from_pdf.py "data\input\20260528 BLUE QUOTE.pdf" 06/15/2026
```
Capture the `[Progressive] DIAG GVW options: [...]` line from the log.

- [ ] **Step 2: Refine `gvw.json` from the DIAG dump**

Replace `options` in `modules/progressive/catalogs/gvw.json` with the exact labels from the DIAG line, bump `captured` to today and `source` to `"DIAG REPUBLIC run"`. Run `python -m pytest tests/progressive/test_catalogs.py tests/progressive/test_gvw_bucket.py -v` — if the real labels differ in wording (e.g. "lbs." vs "lbs"), confirm `_label_to_range` still parses them; adjust the regex/qualifiers in `vehicle_amounts._label_to_range` if needed and re-run.

- [ ] **Step 3: Remove the temporary DIAG block**

Delete the `# --- TEMPORARY DIAG ... END DIAG ---` block added in Task 7 from `vehicles_page.py::fill_from_mapped`.

- [ ] **Step 4: Re-run REPUBLIC to confirm it PROCESSES**

Run (user): same command as Step 1. Expected: GVW resolves (`GVW: '51.000 LBS' -> '26,001 lbs or greater'`), value fills ($45,000), the AddVehicle form Continues past where it previously stuck, quote reaches RATES (or stops only at known out-of-scope issues like BI CSL / non-owned trailer limit).

- [ ] **Step 5: No-regression + commit**

Run: `python -m pytest tests/progressive/ -q` (green) and `python tests/simulate_progressive.py` (`success=True $53,064`).
```bash
git add modules/progressive/catalogs/gvw.json modules/progressive/pages/vehicles_page.py
git commit -m "feat(progressive): GVW catalog from DIAG + remove diagnostic; REPUBLIC processes"
```

---

## Self-Review notes

- **Spec coverage:** S1 normalizer → Task 1. S2 GVW (catalog + bucket + fail-loud + DIAG) → Tasks 2,4,8. S3 value validation → Task 3. S4 integration (field_mapper, preflight, vehicles_page, tests) → Tasks 5,6,7. Out-of-scope (extractor, other numeric fields) honored.
- **Naming note:** the spec's `gvw.py` is implemented as `vehicle_amounts.py` so the same module also houses `resolve_vehicle_value` (same numeric-field-resolver family); `parse_amount` stays in `amounts.py`. All call sites use these names consistently.
- **Type consistency:** `parse_amount(raw) -> float|None`; `bucket_gvw(weight: float, options) -> str`; `resolve_gvw(gvw_raw, options, *, default, screenshot_path) -> str`; `resolve_vehicle_value(raw, *, floor, screenshot_path) -> float|None`. `MappedVehicle.gvw: Optional[str]` (raw), `MappedVehicle.value: Optional[str]` (raw). Same signatures across Tasks 5-8.
- **Data-model change risk:** Task 5 changes `MappedVehicle.gvw`/`value` semantics from processed to raw. Task 5 Step 4 explicitly finds and updates any existing test that asserted the old processed values; the suite must stay green before proceeding.
- **Known dependency:** Task 8 needs a user live run (REPUBLIC) for the GVW DIAG and final validation — the rest (Tasks 1-7) are fully offline.
