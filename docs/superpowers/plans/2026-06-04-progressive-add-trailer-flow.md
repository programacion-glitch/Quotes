# Progressive Add Trailer Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Progressive's separate "Add Trailer" form to the RPA, detect pre-existing units in VehicleSummary to avoid duplicate adds, and route "NON OWNED" trailer entries to the Non-Owned Trailer Phys Damage coverage instead of the unit list.

**Architecture:** Three components mirroring the module's existing separation. (1) Extractors gain an explicit `is_trailer` flag on `VehicleProfile`, propagated to `MappedVehicle`. (2) Field mapper detects `NON OWNED` markers and bumps the rates-page coverage default. (3) Quote flow gains a pre-check loop that reads existing units from `VehicleSummaryPage` and a trailer loop that calls a new `AddTrailerPage` for non-owned trailers.

**Tech Stack:** Python 3, Playwright async, pytest + pytest-asyncio, ExtJS-aware primitives in `BasePage`.

**Spec:** [`docs/superpowers/specs/2026-06-04-progressive-add-trailer-flow-design.md`](../specs/2026-06-04-progressive-add-trailer-flow-design.md)

---

## Phase Layout

- **Phase 0 (Tasks 1–8)** — pre-existing detection + NON OWNED routing + `is_trailer` plumbing. No new Progressive form. Mergeable independently.
- **Phase 1 (Tasks 9–13)** — live diagnostic of AddTrailer form, then `AddTrailerPage` + wiring. Begins after Phase 0 is validated live.

Run `python -m pytest tests/progressive/ -q` after every task; expect green throughout.

---

## Phase 0 — Pre-existing Detection + NON OWNED Routing

### Task 1: Add `is_trailer` to VehicleProfile + extractor wiring

**Files:**
- Modify: `modules/quote_profile.py` (VehicleProfile dataclass, after `value` field)
- Modify: `modules/document_ai_extractor.py:569-586` (merge loop sets `is_trailer`)
- Test: `tests/progressive/test_extractor_is_trailer.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/progressive/test_extractor_is_trailer.py`:

```python
"""Verify the document_ai_extractor flags trailer entries with is_trailer=True."""

from __future__ import annotations

from modules.document_ai_extractor import DocumentAIExtractor


def test_is_trailer_flag_propagates_from_structured_dict():
    """Trucks should land with is_trailer=False, trailers with is_trailer=True."""
    extracted = {
        "applicant": {"business_name": "TEST CO"},
        "commodity": "General Freight",
        "vehicles": {
            "tractors_trucks_pickup": [
                {"year": "2020", "make": "FREIGHTLINER", "vin": "1FUJGLDR8LSLT1234", "type": "TRACTOR"},
            ],
            "trailers": [
                {"year": "2021", "make": "UTILITY", "vin": "1UYVS253XM7301310", "type": "DRY VAN"},
            ],
        },
        "coverages": {},
        "drivers": [],
    }
    profile = DocumentAIExtractor._build_profile_from_dict(extracted)

    assert len(profile.units.vehicles) == 2
    truck = profile.units.vehicles[0]
    trailer = profile.units.vehicles[1]
    assert truck.is_trailer is False
    assert trailer.is_trailer is True


def test_is_trailer_defaults_false_when_field_absent():
    """Profiles built without the extractor (older fixtures) default is_trailer=False."""
    from modules.quote_profile import VehicleProfile
    v = VehicleProfile(vin="ABC", year=2020, make="X", model="Y")
    assert v.is_trailer is False
```

- [ ] **Step 2: Run test to verify it fails**

```
python -m pytest tests/progressive/test_extractor_is_trailer.py -v
```

Expected: FAIL with `AttributeError: type object 'DocumentAIExtractor' has no attribute '_build_profile_from_dict'` OR `AttributeError: 'VehicleProfile' object has no attribute 'is_trailer'`.

- [ ] **Step 3: Add `is_trailer` field to VehicleProfile**

In `modules/quote_profile.py`, locate the `VehicleProfile` dataclass and append the field after `value`:

```python
@dataclass
class VehicleProfile:
    """Per-vehicle data required by Progressive AddVehicle form."""
    vin: Optional[str] = None
    year: Optional[int] = None
    make: Optional[str] = None
    model: Optional[str] = None
    trailer_type: Optional[str] = None
    gvw: Optional[str] = None
    radius_miles: Optional[str] = None
    has_loan: str = "No"
    garaging_zip: Optional[str] = None
    value: Optional[str] = None
    # Explicit trailer flag set by the extractor when this VehicleProfile
    # came from the trailer table (vs. the trucks/tractors/pickups table).
    # Eliminates the previous _looks_like_trailer substring heuristic.
    is_trailer: bool = False
```

- [ ] **Step 4: Wire `is_trailer` in document_ai_extractor**

In `modules/document_ai_extractor.py:569-586`, replace the existing loop with one that tracks source:

```python
        veh_records: List[VehicleProfile] = []
        for src, is_trailer_flag in ((trucks, False), (trailers, True)):
            for t in src:
                year_int = _first_int(t.get("year"))
                value_raw = (t.get("value") or "").strip() or None
                veh_records.append(VehicleProfile(
                    vin=(t.get("vin") or "").strip() or None,
                    year=year_int,
                    make=(t.get("make") or "").strip() or None,
                    model=(t.get("model") or "").strip() or None,
                    trailer_type=(t.get("type") or "").strip().upper() or None,
                    gvw=(t.get("gvw") or "").strip() or None,
                    radius_miles=radius_str,
                    value=value_raw,
                    is_trailer=is_trailer_flag,
                ))
```

- [ ] **Step 5: Extract the dict-build path into a staticmethod for testability**

The current `extract_quote_profile` is monolithic. The test relies on `_build_profile_from_dict(extracted)`. Refactor minimally: extract the block from "Units" (around line 544) through `UnitsProfile(...)` construction into a `@staticmethod _build_profile_from_dict(extracted: dict) -> QuoteProfile` on `DocumentAIExtractor`. The original method delegates to it after assembling `extracted` from DocumentAI/PDF responses.

If a full refactor feels risky, the smaller variant: add a public test seam method that ONLY builds the `veh_records` list:

```python
@staticmethod
def _build_vehicle_records_from_dict(extracted: dict, radius_str: Optional[str] = None) -> List[VehicleProfile]:
    vehicles = extracted.get("vehicles", {})
    trucks = vehicles.get("tractors_trucks_pickup", [])
    trailers = vehicles.get("trailers", [])
    veh_records: List[VehicleProfile] = []
    for src, is_trailer_flag in ((trucks, False), (trailers, True)):
        for t in src:
            year_int = _first_int(t.get("year"))
            value_raw = (t.get("value") or "").strip() or None
            veh_records.append(VehicleProfile(
                vin=(t.get("vin") or "").strip() or None,
                year=year_int,
                make=(t.get("make") or "").strip() or None,
                model=(t.get("model") or "").strip() or None,
                trailer_type=(t.get("type") or "").strip().upper() or None,
                gvw=(t.get("gvw") or "").strip() or None,
                radius_miles=radius_str,
                value=value_raw,
                is_trailer=is_trailer_flag,
            ))
    return veh_records
```

Then update the test to call `_build_vehicle_records_from_dict(extracted)` and assert against the returned list (NOT a full profile). Change the test accordingly:

```python
def test_is_trailer_flag_propagates_from_structured_dict():
    extracted = {
        "vehicles": {
            "tractors_trucks_pickup": [{"year": "2020", "make": "FREIGHTLINER", "vin": "1FUJGLDR8LSLT1234", "type": "TRACTOR"}],
            "trailers": [{"year": "2021", "make": "UTILITY", "vin": "1UYVS253XM7301310", "type": "DRY VAN"}],
        },
    }
    records = DocumentAIExtractor._build_vehicle_records_from_dict(extracted)
    assert len(records) == 2
    assert records[0].is_trailer is False
    assert records[1].is_trailer is True
```

And replace the inline block at line 569 with a call to the new method so behavior stays identical.

- [ ] **Step 6: Run tests to verify they pass**

```
python -m pytest tests/progressive/test_extractor_is_trailer.py -v
```

Expected: PASS (both tests).

- [ ] **Step 7: Run the full progressive test suite**

```
python -m pytest tests/progressive/ -q
```

Expected: 40 prior + 2 new = 42 passing.

- [ ] **Step 8: Commit**

```bash
git add modules/quote_profile.py modules/document_ai_extractor.py tests/progressive/test_extractor_is_trailer.py
git commit -m "feat(progressive): VehicleProfile.is_trailer set by extractor at merge time"
```

---

### Task 2: Propagate `is_trailer` into `MappedVehicle`

**Files:**
- Modify: `modules/progressive/field_mapper.py` (MappedVehicle dataclass + `_map_vehicle`)
- Test: `tests/progressive/test_field_mapper_is_trailer.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/progressive/test_field_mapper_is_trailer.py`:

```python
"""is_trailer flag must propagate VehicleProfile → MappedVehicle through _map_vehicle."""

from __future__ import annotations

from modules.quote_profile import VehicleProfile
from modules.progressive.field_mapper import _map_vehicle


def test_map_vehicle_propagates_is_trailer_true():
    v = VehicleProfile(vin="1UYVS253XM7301310", year=2021, make="UTILITY",
                       model="DRY VAN", is_trailer=True)
    mapped = _map_vehicle(v, fallback_zip=None, fallback_type="DRY VAN")
    assert mapped.is_trailer is True


def test_map_vehicle_propagates_is_trailer_false():
    v = VehicleProfile(vin="1FUJGLDR8LSLT1234", year=2020, make="FREIGHTLINER",
                       model="CASCADIA", is_trailer=False)
    mapped = _map_vehicle(v, fallback_zip=None, fallback_type="TRACTOR")
    assert mapped.is_trailer is False
```

- [ ] **Step 2: Run test to verify it fails**

```
python -m pytest tests/progressive/test_field_mapper_is_trailer.py -v
```

Expected: FAIL with `AttributeError: 'MappedVehicle' object has no attribute 'is_trailer'`.

- [ ] **Step 3: Add `is_trailer` to MappedVehicle**

In `modules/progressive/field_mapper.py`, in `MappedVehicle`, append after `value`:

```python
@dataclass
class MappedVehicle:
    """Vehicle data ready to be filled in Progressive AddVehicle form."""
    vin: Optional[str] = None
    year: Optional[int] = None
    make: Optional[str] = None
    model: Optional[str] = None
    trailer_type: str = "FLATBED"
    gvw: str = "26,001 lbs or greater"
    radius_miles: str = "Over 500 miles"
    has_loan: str = "No"
    garaging_zip: Optional[str] = None
    value: Optional[str] = None
    # Propagated from VehicleProfile by _map_vehicle. Drives the powered-vs-
    # trailer split in quote_flow._add_all_vehicles (replaces substring heuristic).
    is_trailer: bool = False
```

- [ ] **Step 4: Pass `is_trailer` in `_map_vehicle`**

In the same file, modify the `return MappedVehicle(...)` block of `_map_vehicle`:

```python
    return MappedVehicle(
        vin=v.vin,
        year=v.year,
        make=v.make,
        model=v.model,
        trailer_type=(v.trailer_type or fallback_type or "FLATBED"),
        gvw=v.gvw or "26,001 lbs or greater",
        radius_miles=v.radius_miles or "Over 500 miles",
        has_loan=has_loan,
        garaging_zip=v.garaging_zip or fallback_zip,
        value=value_normalized,
        is_trailer=v.is_trailer,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

```
python -m pytest tests/progressive/test_field_mapper_is_trailer.py -v
python -m pytest tests/progressive/ -q
```

Expected: 2 new pass; 42 prior + 2 new = 44 total.

- [ ] **Step 6: Commit**

```bash
git add modules/progressive/field_mapper.py tests/progressive/test_field_mapper_is_trailer.py
git commit -m "feat(progressive): MappedVehicle.is_trailer propagated by _map_vehicle"
```

---

### Task 3: `normalize_identifier` helper + tests

**Files:**
- Create: `modules/progressive/unit_matching.py`
- Test: `tests/progressive/test_unit_matching.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/progressive/test_unit_matching.py`:

```python
"""Stable identifier composition for matching units PDF↔Progressive."""

from __future__ import annotations

from modules.progressive.unit_matching import normalize_identifier


def test_real_vin_dominates_ymm():
    """When a real VIN is present, it wins regardless of Y/M/M."""
    assert normalize_identifier("1UYVS253XM7301310", 2021, "UTILITY", "DRY VAN") == "1UYVS253XM7301310"


def test_lowercase_vin_normalizes_to_upper():
    assert normalize_identifier("  1uyvs253xm7301310  ", None, None, None) == "1UYVS253XM7301310"


def test_non_owned_vin_falls_back_to_ymm():
    """NON OWNED marker is not a real VIN; fall back to composite."""
    assert normalize_identifier("NON OWNED", 2018, "  utility  ", "end dump") == "2018|UTILITY|END DUMP"


def test_empty_vin_with_ymm_uses_ymm():
    assert normalize_identifier("", 2018, "UTILITY", "FLATBED") == "2018|UTILITY|FLATBED"


def test_no_vin_missing_year_returns_none():
    """Insufficient identity data → None; caller will treat as no-match."""
    assert normalize_identifier(None, None, "UTILITY", "FLATBED") is None


def test_short_vin_not_treated_as_real():
    """A 5-char string is not a VIN; fall back to YMM."""
    assert normalize_identifier("ABC12", 2020, "X", "Y") == "2020|X|Y"


def test_invalid_vin_chars_fall_back():
    """VINs use a restricted alphabet (no I, O, Q). 17 chars with O → not a VIN."""
    bad_vin = "1OOOOOOOOOOOOOOOO"   # 17 chars but contains O
    assert normalize_identifier(bad_vin, 2020, "X", "Y") == "2020|X|Y"
```

- [ ] **Step 2: Run test to verify it fails**

```
python -m pytest tests/progressive/test_unit_matching.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'modules.progressive.unit_matching'`.

- [ ] **Step 3: Implement `normalize_identifier`**

Create `modules/progressive/unit_matching.py`:

```python
"""Pure helpers for matching vehicle/trailer units across the PDF↔Progressive boundary.

These functions have no Playwright dependency so they are unit-tested in
isolation. Used by quote_flow._add_all_vehicles to detect units that
Progressive already has on the quote (from a prior run for the same USDOT)
and skip duplicating them.
"""

from __future__ import annotations

import re
from typing import Optional

NON_OWNED_MARKERS = {"NON OWNED", "NONOWNED", "NON-OWNED", "N/A", ""}

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

    if year and make and model:
        make_norm = make.strip().upper()
        model_norm = model.strip().upper()
        if make_norm and model_norm:
            return f"{year}|{make_norm}|{model_norm}"

    return None
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/progressive/test_unit_matching.py -v
```

Expected: 7 passing.

- [ ] **Step 5: Run full suite**

```
python -m pytest tests/progressive/ -q
```

Expected: 44 prior + 7 new = 51 passing.

- [ ] **Step 6: Commit**

```bash
git add modules/progressive/unit_matching.py tests/progressive/test_unit_matching.py
git commit -m "feat(progressive): normalize_identifier for unit matching across PDF/Progressive"
```

---

### Task 4: `diff_unit_vs_pdf` helper + tests

**Files:**
- Modify: `modules/progressive/unit_matching.py`
- Modify: `tests/progressive/test_unit_matching.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/progressive/test_unit_matching.py`:

```python
from dataclasses import dataclass
from typing import Optional as _Opt

from modules.progressive.unit_matching import diff_unit_vs_pdf


# Lightweight stand-ins for ExistingUnit/MappedVehicle, since diff_unit_vs_pdf
# is structural (reads attrs, not type-bound).
@dataclass
class _U:
    year: _Opt[int] = None
    make: _Opt[str] = None
    model: _Opt[str] = None
    gvw: _Opt[str] = None
    value: _Opt[str] = None
    has_loan: str = "No"
    radius_miles: _Opt[str] = None


def test_diff_identical_units_returns_empty():
    a = _U(year=2021, make="UTIL", model="DRY VAN", gvw="26,001 lbs or greater",
           value="50000", has_loan="No", radius_miles="Over 500 miles")
    b = _U(year=2021, make="UTIL", model="DRY VAN", gvw="26,001 lbs or greater",
           value="50000", has_loan="No", radius_miles="Over 500 miles")
    assert diff_unit_vs_pdf(a, b) == {}


def test_diff_single_field_diff():
    a = _U(year=2021, gvw="26,001 lbs or greater")
    b = _U(year=2021, gvw="10,001 - 16,000 lbs")
    assert diff_unit_vs_pdf(a, b) == {"gvw": ("26,001 lbs or greater", "10,001 - 16,000 lbs")}


def test_diff_multiple_fields():
    a = _U(year=2021, value="50000", has_loan="No")
    b = _U(year=2020, value="40000", has_loan="Loan")
    assert diff_unit_vs_pdf(a, b) == {
        "year": (2021, 2020),
        "value": ("50000", "40000"),
        "has_loan": ("No", "Loan"),
    }


def test_diff_none_vs_value_counts_as_diff():
    a = _U(value=None)
    b = _U(value="40000")
    assert diff_unit_vs_pdf(a, b) == {"value": (None, "40000")}


def test_diff_skips_unknown_attrs():
    """diff_unit_vs_pdf reads a fixed field list; foreign attrs don't break it."""
    a = _U(year=2021)
    b = _U(year=2021)
    # ad hoc attr that diff_unit_vs_pdf should ignore
    a.foo = "x"
    b.foo = "y"
    assert diff_unit_vs_pdf(a, b) == {}
```

- [ ] **Step 2: Run test to verify they fail**

```
python -m pytest tests/progressive/test_unit_matching.py -v
```

Expected: 5 new tests FAIL with `ImportError: cannot import name 'diff_unit_vs_pdf'`.

- [ ] **Step 3: Implement `diff_unit_vs_pdf`**

Append to `modules/progressive/unit_matching.py`:

```python
# Fields compared when diffing a unit already on Progressive against the
# PDF-derived MappedVehicle. Skipped when an attribute is missing on either side.
_DIFF_FIELDS = ("year", "make", "model", "gvw", "value", "has_loan", "radius_miles")


def diff_unit_vs_pdf(progressive_unit, pdf_unit) -> dict:
    """Compare a unit Progressive already has on the quote against the PDF.

    Returns {field: (pdf_value, progressive_value)} for fields that differ.
    Empty dict means perfect match. Logged in WARN when SKIPping the add to
    give the operator visibility into what the existing state looks like.

    Structural duck-typing: both arguments only need to expose attributes
    listed in _DIFF_FIELDS — works for ExistingUnit, MappedVehicle, or a test
    double.
    """
    diffs: dict = {}
    for field_name in _DIFF_FIELDS:
        a = getattr(pdf_unit, field_name, None)
        b = getattr(progressive_unit, field_name, None)
        if a != b:
            diffs[field_name] = (a, b)
    return diffs
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/progressive/test_unit_matching.py -v
```

Expected: 12 passing (7 from Task 3 + 5 new).

- [ ] **Step 5: Run full suite**

```
python -m pytest tests/progressive/ -q
```

Expected: 51 prior - 7 (replaced count) + 12 = 56 passing.

- [ ] **Step 6: Commit**

```bash
git add modules/progressive/unit_matching.py tests/progressive/test_unit_matching.py
git commit -m "feat(progressive): diff_unit_vs_pdf for pre-existing-unit skip diagnostics"
```

---

### Task 5: NON OWNED routing in field_mapper

**Files:**
- Modify: `modules/progressive/field_mapper.py`
- Test: `tests/progressive/test_field_mapper_non_owned.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/progressive/test_field_mapper_non_owned.py`:

```python
"""NON OWNED trailers must be removed from MappedFields.vehicles and routed
to CoveragesProfile.non_owned_trailer_phys_damage_limit."""

from __future__ import annotations

from modules.quote_profile import (
    QuoteProfile, ApplicantProfile, VehicleProfile, UnitsProfile, CoveragesProfile,
)
from modules.progressive.field_mapper import map_profile_to_fields


def _profile_with(vehicles, coverages=None):
    return QuoteProfile(
        applicant=ApplicantProfile(business_name="TEST", owner_name="OWNER"),
        units=UnitsProfile(count=len(vehicles), vehicles=vehicles),
        coverages_detail=coverages or CoveragesProfile(),
    )


def test_non_owned_trailer_removed_from_vehicles():
    """A trailer with VIN='NON OWNED' must not appear in mapped_vehicles."""
    profile = _profile_with([
        VehicleProfile(vin="1FUJGLDR8LSLT1234", year=2020, make="FREIGHT",
                       model="CASCADIA", is_trailer=False),
        VehicleProfile(vin="NON OWNED", year=2018, make="UTILITY",
                       model="END DUMP", is_trailer=True),
    ])
    fields = map_profile_to_fields(profile, effective_date="06/15/2026")
    assert len(fields.vehicles) == 1
    assert fields.vehicles[0].vin == "1FUJGLDR8LSLT1234"


def test_non_owned_bumps_coverage_to_default_when_unset():
    """non_owned_trailer_phys_damage_limit defaults to $25,000 if operator didn't set."""
    profile = _profile_with([
        VehicleProfile(vin="1FUJGLDR8LSLT1234", year=2020, make="FREIGHT",
                       model="CASCADIA", is_trailer=False),
        VehicleProfile(vin="NON OWNED", year=2018, make="UTILITY",
                       model="END DUMP", is_trailer=True),
    ])
    fields = map_profile_to_fields(profile, effective_date="06/15/2026")
    assert fields.coverages.non_owned_trailer_phys_damage_limit == "$25,000"


def test_operator_set_coverage_is_respected():
    """If the operator set non_owned coverage to $50k, do not overwrite to $25k."""
    cov = CoveragesProfile(non_owned_trailer_phys_damage_limit="$50,000")
    profile = _profile_with(
        [VehicleProfile(vin="NON OWNED", year=2018, make="X", model="Y", is_trailer=True)],
        coverages=cov,
    )
    fields = map_profile_to_fields(profile, effective_date="06/15/2026")
    assert fields.coverages.non_owned_trailer_phys_damage_limit == "$50,000"


def test_no_non_owned_means_no_coverage_bump():
    """No NON OWNED trailers → coverage stays at its prior value (None)."""
    profile = _profile_with([
        VehicleProfile(vin="1FUJGLDR8LSLT1234", year=2020, make="X", model="Y", is_trailer=False),
    ])
    fields = map_profile_to_fields(profile, effective_date="06/15/2026")
    assert fields.coverages.non_owned_trailer_phys_damage_limit is None


def test_non_owned_via_make_field():
    """Some PDFs put 'NON OWNED' in make/model instead of VIN."""
    profile = _profile_with([
        VehicleProfile(vin=None, year=2018, make="NON OWNED", model="TRAILER", is_trailer=True),
    ])
    fields = map_profile_to_fields(profile, effective_date="06/15/2026")
    assert len(fields.vehicles) == 0
    assert fields.coverages.non_owned_trailer_phys_damage_limit == "$25,000"
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/progressive/test_field_mapper_non_owned.py -v
```

Expected: 5 FAIL — current `map_profile_to_fields` keeps the NON OWNED entries in `vehicles` and never touches the coverages limit.

- [ ] **Step 3: Add `_is_non_owned` helper to field_mapper**

In `modules/progressive/field_mapper.py`, after the existing imports add:

```python
from modules.progressive.unit_matching import NON_OWNED_MARKERS
```

Add helper before `_map_vehicle`:

```python
def _is_non_owned(
    vin: Optional[str], make: Optional[str], model: Optional[str]
) -> bool:
    """True when the unit is a 'non-owned' trailer marker — must be routed
    to Non-Owned Trailer Phys Damage coverage instead of Add Trailer.

    Detection by vin first, then make/model fallback (some PDFs surface the
    marker on a different column).
    """
    vin_clean = (vin or "").strip().upper()
    if vin_clean in NON_OWNED_MARKERS:
        return True
    for s in (make, model):
        if s and "NON OWNED" in s.upper():
            return True
    return False
```

- [ ] **Step 4: Filter NON OWNED + bump coverage in `map_profile_to_fields`**

In `modules/progressive/field_mapper.py`, locate the section that builds `mapped_vehicles` (around lines 191-211) and immediately AFTER that block (and BEFORE the drivers section), insert:

```python
    # Route NON OWNED trailers to Non-Owned Trailer Phys Damage coverage —
    # Progressive's Add Trailer form requires a real VIN. The rates-page
    # handler at coverages_rates_page.py:1030 picks up the bumped limit.
    non_owned_count = sum(
        1 for mv in mapped_vehicles if _is_non_owned(mv.vin, mv.make, mv.model)
    )
    mapped_vehicles = [
        mv for mv in mapped_vehicles if not _is_non_owned(mv.vin, mv.make, mv.model)
    ]
    coverages_out = profile.coverages_detail
    if non_owned_count and not coverages_out.non_owned_trailer_phys_damage_limit:
        # CoveragesProfile is a dataclass; mutate the field on the existing
        # instance so RATES picks it up. Tests confirm the default does not
        # override an operator-set value.
        coverages_out.non_owned_trailer_phys_damage_limit = "$25,000"
        print(
            f"    [Progressive] field_mapper: {non_owned_count} NON OWNED "
            f"trailer(s) → Non-Owned Trailer Phys Damage = $25,000 (default)"
        )
```

Then in the `return MappedFields(...)` block, change `coverages=profile.coverages_detail` to `coverages=coverages_out` (same object, but make the intent explicit).

- [ ] **Step 5: Run tests to verify they pass**

```
python -m pytest tests/progressive/test_field_mapper_non_owned.py -v
```

Expected: 5 passing.

- [ ] **Step 6: Run full suite**

```
python -m pytest tests/progressive/ -q
```

Expected: 56 prior + 5 new = 61 passing.

- [ ] **Step 7: Commit**

```bash
git add modules/progressive/field_mapper.py tests/progressive/test_field_mapper_non_owned.py
git commit -m "feat(progressive): route NON OWNED trailers to non-owned phys damage coverage"
```

---

### Task 6: `ExistingUnit` + `VehicleSummaryPage.list_existing_units()`

**Files:**
- Modify: `modules/progressive/pages/vehicles_page.py` (add `ExistingUnit` + method)
- Test: `tests/progressive/test_vehicle_summary_list_existing.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/progressive/test_vehicle_summary_list_existing.py`:

```python
"""VehicleSummaryPage.list_existing_units reads pre-loaded rows from the DOM."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.progressive.pages.vehicles_page import VehicleSummaryPage


@pytest.mark.asyncio
async def test_returns_empty_when_on_most_common_vehicles(mock_page):
    """Fresh quote landing on tile picker → no rows → empty list, no raise."""
    # Header that signals MostCommonVehicles instead of VehicleSummary
    header = AsyncMock()
    header.count = AsyncMock(return_value=1)
    mock_page.get_by_text = MagicMock(return_value=header)
    summary = VehicleSummaryPage(mock_page)
    result = await summary.list_existing_units()
    assert result == []


@pytest.mark.asyncio
async def test_returns_empty_when_dom_read_fails(mock_page):
    """Best-effort: if locator query raises, return [] and do not propagate."""
    mock_page.get_by_text = MagicMock(side_effect=RuntimeError("DOM gone"))
    summary = VehicleSummaryPage(mock_page)
    result = await summary.list_existing_units()
    assert result == []


@pytest.mark.asyncio
async def test_parses_row_with_vin_visible(mock_page):
    """A single VehicleSummary row with visible '2021 UTILITY DRY VAN · VIN: 1UYVS253XM7301310'
    must parse into an ExistingUnit with normalized identifier."""
    row = AsyncMock()
    row.text_content = AsyncMock(return_value="2021 UTILITY DRY VAN  VIN: 1UYVS253XM7301310  Edit  Remove")
    row.is_visible = AsyncMock(return_value=True)

    rows = AsyncMock()
    rows.count = AsyncMock(return_value=1)
    rows.nth = MagicMock(return_value=row)
    # Header probe must return zero so the MostCommon early-return doesn't fire.
    header = AsyncMock()
    header.count = AsyncMock(return_value=0)

    def get_by_text(text, **kwargs):
        if "Most common vehicles" in str(text):
            return header
        return rows

    mock_page.get_by_text = MagicMock(side_effect=get_by_text)
    # Rows are looked up via a CSS selector → page.locator
    mock_page.locator = MagicMock(return_value=rows)

    summary = VehicleSummaryPage(mock_page)
    result = await summary.list_existing_units()
    assert len(result) == 1
    assert result[0].vin == "1UYVS253XM7301310"
    assert result[0].year == 2021
    assert result[0].make == "UTILITY"
    assert "DRY VAN" in (result[0].model or "")
    assert result[0].identifier == "1UYVS253XM7301310"
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/progressive/test_vehicle_summary_list_existing.py -v
```

Expected: 3 FAIL — `list_existing_units` does not exist yet.

- [ ] **Step 3: Add `ExistingUnit` dataclass + method**

In `modules/progressive/pages/vehicles_page.py`, after the imports and BEFORE `VEHICLE_TYPES`, add:

```python
import re
from dataclasses import dataclass

from modules.progressive.unit_matching import normalize_identifier


@dataclass
class ExistingUnit:
    """A vehicle/trailer Progressive already has on the quote.

    Returned by VehicleSummaryPage.list_existing_units() so the orchestrator
    can SKIP duplicate adds. row_locator is kept for future Edit support;
    Phase 0 only reads identifiers.
    """
    identifier: str
    vin: Optional[str]
    year: Optional[int]
    make: Optional[str]
    model: Optional[str]
    is_trailer: bool = False
    row_locator: object = None     # Playwright Locator; typed loose for tests
```

Then add the method to `VehicleSummaryPage` class (right after `add_trailer`):

```python
    async def list_existing_units(self) -> List["ExistingUnit"]:
        """Read VehicleSummary rows for units Progressive already has on the quote.

        Best-effort: returns [] on MostCommonVehicles, empty page, or any DOM
        read failure. Never raises — callers treat empty as "fresh quote, add
        everything".

        Row text is parsed with a tolerant regex because ExtJS renders the
        whole row as concatenated text content like:
            "2021 UTILITY DRY VAN  VIN: 1UYVS253XM7301310  Edit  Remove"
        """
        try:
            # Skip when on the tile picker (no list rendered yet).
            on_most_common = await self.page.get_by_text(
                "Most common vehicles for the customer's business",
                exact=False,
            ).count() > 0
            if on_most_common:
                return []
        except Exception:
            return []

        units: List[ExistingUnit] = []
        try:
            # Each VehicleSummary row contains both 'Edit' and 'Remove' actions;
            # using has-text on a grid row narrows past header/banner content.
            row_loc = self.page.locator(
                "div.x-grid-row:has-text('Edit'):has-text('Remove'),"
                " tr:has-text('Edit'):has-text('Remove')"
            )
            n = await row_loc.count()
            for i in range(n):
                row = row_loc.nth(i)
                try:
                    if not await row.is_visible():
                        continue
                    text = (await row.text_content()) or ""
                except Exception:
                    continue

                year, make, model, vin = _parse_summary_row(text)
                ident = normalize_identifier(vin, year, make, model)
                if not ident:
                    continue
                units.append(ExistingUnit(
                    identifier=ident,
                    vin=vin,
                    year=year,
                    make=make,
                    model=model,
                    is_trailer=False,    # row-vs-section detection deferred; see spec
                    row_locator=row,
                ))
        except Exception:
            # DOM gone, page navigated away, etc. — fail soft.
            return units
        return units
```

And add the row-parser as a module-level helper at the bottom of the file:

```python
# Capture groups: year (4 digits), make + model up to "VIN:" or end,
# optional VIN (17 chars after "VIN:"). Tolerant of extra whitespace.
_ROW_REGEX = re.compile(
    r"(?P<year>\d{4})\s+(?P<make_model>[A-Z][A-Z0-9 /\-]+?)"
    r"(?:\s+VIN:\s*(?P<vin>[A-HJ-NPR-Z0-9]{17}))?(?:\s|$)",
    re.IGNORECASE,
)


def _parse_summary_row(text: str) -> tuple[Optional[int], Optional[str], Optional[str], Optional[str]]:
    """Pull (year, make, model, vin) from a VehicleSummary row's text content.

    Heuristic: make is the FIRST token after year, model is the remaining
    tokens until 'VIN:' (or end of string). VIN is the 17-char token after
    'VIN:' if present. Returns (None, None, None, None) when the row text
    doesn't match the expected shape.
    """
    m = _ROW_REGEX.search(text or "")
    if not m:
        return None, None, None, None
    year_str = m.group("year")
    make_model = (m.group("make_model") or "").strip()
    vin = (m.group("vin") or "").strip().upper() or None
    year = int(year_str) if year_str else None

    tokens = make_model.split()
    if not tokens:
        return year, None, None, vin
    make = tokens[0].upper()
    model = " ".join(tokens[1:]).upper() if len(tokens) > 1 else None
    return year, make, model, vin
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/progressive/test_vehicle_summary_list_existing.py -v
```

Expected: 3 passing.

- [ ] **Step 5: Run full suite**

```
python -m pytest tests/progressive/ -q
```

Expected: 61 prior + 3 new = 64 passing.

- [ ] **Step 6: Commit**

```bash
git add modules/progressive/pages/vehicles_page.py tests/progressive/test_vehicle_summary_list_existing.py
git commit -m "feat(progressive): VehicleSummaryPage.list_existing_units() reads pre-loaded rows"
```

---

### Task 7: Wire pre-check + replace `_looks_like_trailer` in `quote_flow`

**Files:**
- Modify: `modules/progressive/quote_flow.py` (`_add_all_vehicles` + `_looks_like_trailer`)
- (No new test; integration behavior validated live in Task 8)

- [ ] **Step 1: Replace `_add_all_vehicles`**

In `modules/progressive/quote_flow.py`, replace the entire `_add_all_vehicles` method (around lines 173-222) with:

```python
    async def _add_all_vehicles(
        self, wizard_page: Page, fields: MappedFields, result: QuoteResult
    ) -> None:
        """Loop over fields.vehicles, adding each via VehicleSummary -> AddVehicle.

        Pre-check: read units already on the quote (Progressive remembers them
        between quotes for the same USDOT). Skip any PDF unit whose identifier
        matches a row already present, logging field-level diffs for visibility.

        Split remaining units into powered (Add Vehicle flow) and trailers
        (Add Trailer flow). Phase 0: trailer loop still skipped with WARN.
        Phase 1 wires AddTrailerPage in Task 11.
        """
        if not fields.vehicles:
            raise RuntimeError("At least one vehicle is required to quote")

        summary = VehicleSummaryPage(wizard_page)

        # Pre-existing detection
        existing = await summary.list_existing_units()
        existing_by_id = {u.identifier: u for u in existing if u.identifier}
        if existing:
            print(
                f"    [Progressive] VehicleSummary has {len(existing)} "
                f"pre-existing unit(s); pre-check enabled"
            )

        to_add: list = []
        for v in fields.vehicles:
            pdf_id = normalize_identifier(v.vin, v.year, v.make, v.model)
            if pdf_id and pdf_id in existing_by_id:
                diffs = diff_unit_vs_pdf(existing_by_id[pdf_id], v)
                msg = f"Pre-existing unit {pdf_id} kept as-is"
                if diffs:
                    msg += f" (diffs vs PDF: {diffs})"
                print(f"    [Progressive] SKIP {msg}")
                result.warnings.append(msg)
                continue
            to_add.append(v)

        # Split by is_trailer; substring fallback only if extractor failed to set
        # the flag (older fixtures / hand-built profiles in tests).
        powered, trailers = [], []
        for v in to_add:
            if v.is_trailer or self._looks_like_trailer_fallback(v):
                trailers.append(v)
            else:
                powered.append(v)

        if not (powered or existing):
            raise RuntimeError(
                "No powered vehicle to add and none pre-existing; "
                "Progressive requires at least one to quote."
            )

        # Powered loop (unchanged)
        for i, vehicle in enumerate(powered):
            print(f"    [Progressive] Vehicle {i + 1} / {len(powered)}")
            await summary.add_vehicle()

            most_common = MostCommonVehiclesPage(wizard_page)
            await most_common.select_vehicle_type(vehicle.trailer_type)

            add_form = AddVehiclePage(wizard_page)
            await add_form.fill_from_mapped(vehicle)
            if hasattr(add_form, "warnings") and add_form.warnings:
                result.warnings.extend(add_form.warnings)

        # Trailer loop: Phase 1 will wire AddTrailerPage here. Until then,
        # log skip so live runs show the trailer count clearly.
        if trailers:
            msg = (
                f"Skipped {len(trailers)} trailer(s) — Phase 1 wiring "
                f"pending. VIN(s): " + ", ".join((t.vin or "(no vin)") for t in trailers)
            )
            print(f"    [Progressive] WARN: {msg}")
            result.warnings.append(msg)

        # All units added; continue to drivers
        await summary.click_continue()
```

- [ ] **Step 2: Replace `_looks_like_trailer` with `_looks_like_trailer_fallback`**

Rename the staticmethod (around line 224-235) to mark it explicitly transitional:

```python
    @staticmethod
    def _looks_like_trailer_fallback(vehicle) -> bool:
        """Substring heuristic kept as a safety net when an upstream extractor
        failed to set MappedVehicle.is_trailer (older fixtures / hand-built
        profiles in tests). Emits a one-line WARN so we can monitor for stray
        callers in production logs.
        """
        for s in (vehicle.trailer_type, vehicle.model, vehicle.make):
            if s and "TRAILER" in s.upper():
                print(
                    f"    [Progressive] WARN: _looks_like_trailer_fallback "
                    f"matched on '{s}' — extractor should be setting is_trailer"
                )
                return True
        return False
```

- [ ] **Step 3: Update the imports at the top of `quote_flow.py`**

Add:

```python
from modules.progressive.unit_matching import normalize_identifier, diff_unit_vs_pdf
```

- [ ] **Step 4: Run the full suite + simulator**

```
python -m pytest tests/progressive/ -q
python tests/simulate_progressive.py
```

Expected: 64 passing; simulator success=True (no behavior regression from the substring → flag swap, since the simulator profile has trailer_type strings the fallback still catches if is_trailer wasn't set).

- [ ] **Step 5: Commit**

```bash
git add modules/progressive/quote_flow.py
git commit -m "feat(progressive): pre-existing unit pre-check + split by explicit is_trailer flag"
```

---

### Task 8: Phase 0 live validation

**Files:** none modified unless a regression surfaces

- [ ] **Step 1: Run M&D regression**

```powershell
$env:PYTHONIOENCODING="utf-8"
python scripts\run_progressive_from_pdf.py "data\input\<M&D BLUE QUOTE.pdf>" 06/15/2026
```

Expected: premium $53,064/yr preserved. Logs must show no SKIP entries (M&D has no pre-existing units the first time it runs).

- [ ] **Step 2: Run RYD fresh**

```powershell
python scripts\run_progressive_from_pdf.py "data\input\<RYD BLUE QUOTE.pdf>" 06/15/2026
```

Expected: powered vehicle added end-to-end, trailer still skipped via WARN (Phase 1 work). Premium ≈ $44,621 baseline (unchanged from before, since trailer was already skipped before this PR).

- [ ] **Step 3: Run RYD repeat (the pre-existing test)**

Immediately after Step 2, re-run the same RYD PDF against the same USDOT. The quote landing page now has the powered vehicle pre-loaded.

Expected logs:
```
[Progressive] VehicleSummary has 1 pre-existing unit(s); pre-check enabled
[Progressive] SKIP Pre-existing unit 1<VIN> kept as-is
```

Expected: continues to drivers, reaches RATES, captures premium. No duplicate-add validation banner.

- [ ] **Step 4: If any regression — investigate, fix, add a regression test, re-commit**

Don't merge until all three scenarios pass.

- [ ] **Step 5: Note Phase 0 baselines in commit message**

```bash
git commit --allow-empty -m "validate(progressive): Phase 0 live OK — M&D \$53,064, RYD fresh \$44,621, RYD repeat SKIP"
```

---

## Phase 1 — AddTrailerPage

### Task 9: Temporary diagnostic in quote_flow

**Files:**
- Modify: `modules/progressive/quote_flow.py` (insert diagnostic in trailer skip branch)

The goal of this task is **discovery, not implementation**. Capture the AddTrailer form's DOM so Task 10 has concrete selectors.

- [ ] **Step 1: Add temporary diagnostic block**

In `_add_all_vehicles`, replace the trailer skip WARN with:

```python
        # DIAGNOSTIC (Phase 1 Task 9 — removed in Task 12): dump trailer form
        # so Task 10 has concrete selectors.
        if trailers:
            from modules.progressive.pages.vehicles_page import VehicleSummaryPage as _VSP
            print(f"    [Progressive] DIAG: opening Add Trailer for discovery; "
                  f"{len(trailers)} trailer(s) queued, only 1st is probed")
            try:
                await summary.add_trailer()
                await wizard_page.wait_for_load_state("networkidle", timeout=30_000)
                print(f"    [Progressive] DIAG: URL={wizard_page.url}")
                print(f"    [Progressive] DIAG: title={await wizard_page.title()}")
                # Dump visible inputs / radios / comboboxes
                dump = await wizard_page.evaluate("""() => {
                    const visible = el => {
                        const r = el.getBoundingClientRect();
                        return r.width > 0 && r.height > 0;
                    };
                    const inputs = [...document.querySelectorAll('input')]
                        .filter(visible)
                        .map(i => ({tag: i.tagName, type: i.type, name: i.name,
                                    placeholder: i.placeholder, aria: i.getAttribute('aria-label')}));
                    const radios = [...document.querySelectorAll('[role="radiogroup"]')]
                        .filter(visible)
                        .map(g => ({label: g.getAttribute('aria-label') || g.textContent.slice(0,80)}));
                    const combos = [...document.querySelectorAll('[role="combobox"]')]
                        .filter(visible)
                        .map(c => ({label: c.getAttribute('aria-label'), value: c.value || ''}));
                    return {inputs, radios, combos};
                }""")
                print(f"    [Progressive] DIAG inputs: {dump.get('inputs')}")
                print(f"    [Progressive] DIAG radios: {dump.get('radios')}")
                print(f"    [Progressive] DIAG combos: {dump.get('combos')}")
                await summary.screenshot("phase1_add_trailer_form")
            except Exception as e:
                print(f"    [Progressive] DIAG failed: {e}")

            msg = (
                f"Discovery mode: {len(trailers)} trailer(s) probed for "
                f"selector capture. AddTrailerPage not yet implemented."
            )
            result.warnings.append(msg)
```

- [ ] **Step 2: Commit the diagnostic (will be reverted in Task 12)**

```bash
git add modules/progressive/quote_flow.py
git commit -m "diag(progressive): Phase 1 Task 9 — dump AddTrailer form for selector capture"
```

- [ ] **Step 3: Run RYD live to capture the dump**

```powershell
$env:PYTHONIOENCODING="utf-8"
python scripts\run_progressive_from_pdf.py "data\input\<RYD BLUE QUOTE.pdf>" 06/15/2026
```

Capture stdout. Save the relevant DIAG lines (inputs / radios / combos / URL / title) to a scratch file `docs/superpowers/scratch/phase1-addtrailer-dump.md` — this becomes the input to Task 10.

The bot will still skip past trailers afterwards (the diagnostic does not click Continue). The screenshot lands under the standard screenshots dir.

---

### Task 10: Implement `AddTrailerPage` from the dump

**Files:**
- Create: `modules/progressive/pages/trailers_page.py`
- Test: `tests/progressive/test_add_trailer_page.py` (new)

The selectors below assume the dump confirms a structure similar to AddVehicle. If the live form differs (e.g. axle count, trailer body length), amend selectors before the test.

- [ ] **Step 1: Write the failing test**

Create `tests/progressive/test_add_trailer_page.py`:

```python
"""AddTrailerPage smoke test: fill_from_mapped issues the expected primitive calls."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.progressive.field_mapper import MappedVehicle
from modules.progressive.pages.trailers_page import AddTrailerPage


@pytest.mark.asyncio
async def test_fill_from_mapped_invokes_continue(mock_page, mock_locator):
    """Smoke: a happy-path trailer reaches safe_click_continue without raising."""
    trailer = MappedVehicle(
        vin="1UYVS253XM7301310",
        year=2021,
        make="UTILITY",
        model="DRY VAN",
        trailer_type="DRY VAN",
        is_trailer=True,
        has_loan="No",
        value=None,
    )
    page = AddTrailerPage(mock_page)
    page.safe_click_continue = AsyncMock()
    page.safe_fill = AsyncMock()
    page.safe_radio = AsyncMock()
    page.safe_select_combo = AsyncMock()
    page.safe_checkbox = AsyncMock()
    page.find_combo = AsyncMock(return_value=mock_locator)
    page.find_radiogroup = AsyncMock(return_value=mock_locator)
    page.field_exists = AsyncMock(return_value=True)
    page.wait_for_extjs_idle = AsyncMock()

    await page.fill_from_mapped(trailer)
    page.safe_click_continue.assert_called_once()


@pytest.mark.asyncio
async def test_value_present_triggers_apd_path(mock_page, mock_locator):
    """When trailer.value is set, Comp/Coll = Yes path runs (vehicle value fill)."""
    trailer = MappedVehicle(
        vin="1UYVS253XM7301310", year=2021, make="UTILITY", model="DRY VAN",
        trailer_type="DRY VAN", is_trailer=True, has_loan="No", value="50000",
    )
    page = AddTrailerPage(mock_page)
    page.safe_click_continue = AsyncMock()
    page.safe_fill = AsyncMock()
    page.safe_radio = AsyncMock()
    page.safe_select_combo = AsyncMock()
    page.safe_checkbox = AsyncMock()
    page.find_combo = AsyncMock(return_value=mock_locator)
    page.find_radiogroup = AsyncMock(return_value=mock_locator)
    page.field_exists = AsyncMock(return_value=True)
    page.wait_for_extjs_idle = AsyncMock()
    page.wait_for_currency_formatted = AsyncMock()

    await page.fill_from_mapped(trailer)
    # safe_radio called for both loan and comp/coll
    radio_calls = [c.args for c in page.safe_radio.call_args_list]
    assert any("Yes" == args[1] for args in radio_calls if len(args) >= 2)
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/progressive/test_add_trailer_page.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'modules.progressive.pages.trailers_page'`.

- [ ] **Step 3: Implement `AddTrailerPage`**

Create `modules/progressive/pages/trailers_page.py`. Mirror AddVehiclePage structure but with trailer-specific labels (confirmed from the diagnostic dump in Task 9):

```python
"""Add-Trailer form page object for Progressive.

URL: pageName=AddTrailer (confirm from live diagnostic dump)

Mirrors AddVehiclePage's structure with the trailer-form variations
captured during Phase 1 Task 9 discovery:
  - Trailer Type combobox (Dry Van / Reefer / Flatbed / Dump / Tank / ...)
  - GVW combobox may or may not appear; soft-skip
  - Distance field typically absent for trailers
  - Comp/Coll path identical to AddVehicle (driven by MappedVehicle.value)
"""

from __future__ import annotations

from typing import Optional

from modules.progressive.field_mapper import MappedVehicle
from modules.progressive.pages.base_page import BasePage


class AddTrailerPage(BasePage):
    REQUIRED_FIELDS = ("year", "make", "model", "vin", "type")
    CONDITIONAL_FIELDS = ("vehicle_value", "vehicle_has_no_equipment")
    OPTIONAL_FIELDS = ("garaging_zip", "gvw")

    def __init__(self, page):
        super().__init__(page)
        self.warnings: list[str] = []

    def _log_skipped(self, field_name: str, reason: str) -> None:
        msg = f"add_trailer: skipped '{field_name}' — {reason}"
        print(f"    [Progressive] {msg}")
        self.warnings.append(msg)

    async def fill_from_mapped(self, trailer: MappedVehicle) -> None:
        """Fill AddTrailer form from a MappedVehicle and Continue."""
        await self.page.wait_for_load_state("networkidle", timeout=30_000)

        # 1. VIN textbox + Lookup (or Y/M/M fallback)
        if trailer.vin:
            await self._fill_by_vin(trailer.vin)
        else:
            await self._fill_by_ymm(trailer.year, trailer.make, trailer.model)

        # 2. Trailer Type combobox (post-VIN if Progressive needs us to confirm)
        await self._set_trailer_type(trailer.trailer_type)

        # 3. Garaging ZIP — same handling as AddVehicle
        if trailer.garaging_zip:
            await self._set_zip(trailer.garaging_zip)

        # 4. GVW (soft-skip if not rendered for trailers)
        await self._set_combo_soft("What is the gross vehicle weight?", trailer.gvw)

        # 5. Loan/Lease radio
        loan_label = {"Loan": "Yes - Loan", "Lease": "Yes - Lease", "No": "No"}.get(
            trailer.has_loan, "No"
        )
        group = await self.find_radiogroup("Is there a loan/lease on this vehicle?")
        if await self.field_exists(group, wait_ms=2_500):
            await self.safe_radio(group, loan_label)

        try:
            await self.wait_for_extjs_idle(timeout_ms=5_000)
        except Exception:
            pass
        await self.page.wait_for_timeout(600)

        # 6. Comp/Coll question is revealed only when loan=No (lender mandates APD otherwise)
        if trailer.has_loan == "No":
            wants_apd = bool(trailer.value)
            apd_group = await self.find_radiogroup(
                "Does the customer need Comprehensive or Collision coverage"
            )
            if await self.field_exists(apd_group, wait_ms=2_500):
                await self.safe_radio(apd_group, "Yes" if wants_apd else "No")
                try:
                    await self.wait_for_extjs_idle(timeout_ms=5_000)
                except Exception:
                    pass
                await self.page.wait_for_timeout(800)

                if wants_apd:
                    await self._tick_no_equipment_checkbox()
                    await self._fill_vehicle_value(default=trailer.value)
                else:
                    print("    [Progressive] APD = No (no Value); skipping equipment + Vehicle Value")

        # 7. Continue
        await self.safe_click_continue(expect_url_changes_from="AddTrailer")

    # --- private helpers (mirror AddVehiclePage; selectors confirmed in Task 9) ---

    async def _fill_by_vin(self, vin: str) -> None:
        print(f"    [Progressive] Adding trailer by VIN: {vin}")
        vin_box = self.page.get_by_role("textbox", name="Vehicle Identification Number (VIN)")
        try:
            current = await vin_box.first.input_value()
            if current and current != vin:
                clear_btn = self.page.get_by_role("button", name="Clear VIN")
                if await clear_btn.count() > 0:
                    await clear_btn.first.click()
                    await self.page.wait_for_timeout(500)
        except Exception:
            pass
        await self.safe_fill(vin_box.first, vin, verify=False)
        lookup_btn = self.page.get_by_role("button", name="Lookup VIN")
        if await lookup_btn.count() > 0:
            await lookup_btn.first.click(timeout=10_000)
            await self.page.wait_for_load_state("networkidle", timeout=20_000)
            await self.page.wait_for_timeout(1_500)

    async def _fill_by_ymm(
        self, year: Optional[int], make: Optional[str], model: Optional[str]
    ) -> None:
        if not (year and make and model):
            self._log_skipped("ymm", f"incomplete: year={year} make={make} model={model}")
            return
        print(f"    [Progressive] Adding trailer by Y/M/M: {year} {make} {model}")
        ymm_radio = self.page.get_by_role("radio", name="Year, Make, Model")
        if await ymm_radio.count() > 0:
            await ymm_radio.first.click(timeout=2_000)
            await self.page.wait_for_timeout(500)
        await self.safe_select_combo(await self.find_combo("Year"), str(year))
        try:
            await self.page.keyboard.press("Tab")
            await self.page.wait_for_timeout(800)
        except Exception:
            pass
        await self.safe_select_combo(await self.find_combo("Make"), make)
        await self.safe_select_combo(await self.find_combo("Model"), model)

    async def _set_trailer_type(self, trailer_type: Optional[str]) -> None:
        combo = await self.find_combo("Trailer Type")
        if await combo.count() == 0:
            return
        t = (trailer_type or "").upper()
        # Map common Blue Quote strings to Progressive option labels.
        # Confirm exact strings from the dump; below are best guesses.
        option = "Dry Van"
        if "REEFER" in t or "REFRIG" in t:
            option = "Refrigerated"
        elif "FLATBED" in t:
            option = "Flatbed"
        elif "DUMP" in t:
            option = "Dump"
        elif "TANK" in t:
            option = "Tank"
        elif "DRY VAN" in t or "VAN" in t:
            option = "Dry Van"
        await self.safe_select_combo(combo, option)

    async def _set_zip(self, zip_code: str) -> None:
        zip_box = self.page.get_by_role("textbox", name="Zip code where the vehicle is located")
        if await zip_box.count() > 0:
            try:
                current = await zip_box.first.input_value()
            except Exception:
                current = ""
            if current != zip_code:
                await self.safe_fill(zip_box.first, zip_code, verify=False)

    async def _set_combo_soft(self, label: str, option_text: str) -> None:
        combo = await self.find_combo(label)
        if await combo.count() == 0:
            self._log_skipped(label, "combobox not rendered")
            return
        try:
            await self.safe_select_combo(combo, option_text)
        except Exception as e:
            print(f"    [Progressive] WARN: combobox '{label}' = '{option_text}' failed: {e}")

    async def _tick_no_equipment_checkbox(self) -> None:
        cb = self.page.get_by_role("checkbox", name="Vehicle has no equipment")
        if await self.field_exists(cb, wait_ms=1500):
            try:
                await self.safe_checkbox(cb, check=True)
            except Exception as e:
                print(f"    [Progressive] WARN: 'Vehicle has no equipment' click failed: {e}")
        else:
            self._log_skipped("vehicle_has_no_equipment", "field_not_rendered")

    async def _fill_vehicle_value(self, default: str) -> None:
        try:
            await self.wait_for_extjs_idle(timeout_ms=5_000)
        except Exception:
            pass
        await self.page.wait_for_timeout(600)
        candidates = [
            self.page.locator('input[placeholder="Vehicle Value"]'),
            self.page.get_by_role("textbox", name="Vehicle Value", exact=True),
            self.page.get_by_role("textbox", name="Vehicle Value", exact=False),
        ]
        for loc in candidates:
            n = await loc.count()
            for i in range(n):
                el = loc.nth(i)
                try:
                    if not await el.is_visible():
                        continue
                    await el.scroll_into_view_if_needed(timeout=2_000)
                    await self.safe_fill(el, default, verify=False)
                    await self.wait_for_currency_formatted(el)
                    actual = ""
                    try:
                        actual = (await el.input_value()).strip()
                    except Exception:
                        pass
                    if actual:
                        print(f"    [Progressive] Trailer Vehicle Value: ${actual}")
                        return
                except Exception as e:
                    print(f"    [Progressive] Trailer Value selector failed: {e}")
                    continue
        print("    [Progressive] WARN: trailer Vehicle Value not filled")
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/progressive/test_add_trailer_page.py -v
```

Expected: 2 passing.

- [ ] **Step 5: Run full suite**

```
python -m pytest tests/progressive/ -q
```

Expected: 64 prior + 2 new = 66 passing.

- [ ] **Step 6: Commit**

```bash
git add modules/progressive/pages/trailers_page.py tests/progressive/test_add_trailer_page.py
git commit -m "feat(progressive): AddTrailerPage with Comp/Coll APD path mirrored from AddVehicle"
```

---

### Task 11: Wire trailer loop into `_add_all_vehicles`

**Files:**
- Modify: `modules/progressive/quote_flow.py`

- [ ] **Step 1: Add import**

In `modules/progressive/quote_flow.py`, add:

```python
from modules.progressive.pages.trailers_page import AddTrailerPage
```

- [ ] **Step 2: Replace the diagnostic block with the real trailer loop**

In `_add_all_vehicles`, replace the entire diagnostic + WARN block from Task 9 with:

```python
        for i, trailer in enumerate(trailers):
            print(f"    [Progressive] Trailer {i + 1} / {len(trailers)}")
            await summary.add_trailer()
            await wizard_page.wait_for_load_state("networkidle", timeout=30_000)
            add_trailer_form = AddTrailerPage(wizard_page)
            await add_trailer_form.fill_from_mapped(trailer)
            if add_trailer_form.warnings:
                result.warnings.extend(add_trailer_form.warnings)
```

- [ ] **Step 3: Run full suite + simulator**

```
python -m pytest tests/progressive/ -q
python tests/simulate_progressive.py
```

Expected: 66 passing; simulator success (the simulator uses no trailers, so the new loop is unreached — no behavior change).

- [ ] **Step 4: Commit**

```bash
git add modules/progressive/quote_flow.py
git commit -m "feat(progressive): _add_all_vehicles wires AddTrailerPage in trailer loop"
```

---

### Task 12: Phase 1 live validation + cleanup

**Files:**
- Modify (cleanup): `modules/progressive/quote_flow.py` (remove any DIAG remnants)

- [ ] **Step 1: Run M&D regression**

```powershell
$env:PYTHONIOENCODING="utf-8"
python scripts\run_progressive_from_pdf.py "data\input\<M&D BLUE QUOTE.pdf>" 06/15/2026
```

Expected: $53,064/yr preserved (no trailers).

- [ ] **Step 2: Run RYD fresh — powered + real trailer**

Use a fresh USDOT (or remove existing units manually beforehand). Expected: powered vehicle added, trailer (1UYVS253XM7301310) added end-to-end via AddTrailerPage. Premium re-baselined (will be higher than $44,621 because trailer now contributes). Note new baseline in stdout.

- [ ] **Step 3: Run RYD repeat (pre-existing check still works post-trailer)**

Re-run same PDF same USDOT. Expected: BOTH powered + trailer hit the pre-check SKIP path. No duplicate adds.

- [ ] **Step 4: Run Prueba1 NOBLE LOGISTICS**

```powershell
python scripts\run_progressive_from_pdf.py "data\input\20260601 BLUE QUOTE Prueba1.pdf" 06/15/2026
```

Expected logs:
```
[Progressive] field_mapper: 1 NON OWNED trailer(s) → Non-Owned Trailer Phys Damage = $25,000 (default)
```

On RATES page: "Non-Owned Trailer Physical Damage" coverage expands and limit gets set. Premium re-baselined (will differ from $107,431 baseline because non-owned coverage now applied). Note new baseline.

- [ ] **Step 5: Cleanup remaining DIAG/verbose logs**

Check `modules/progressive/quote_flow.py` for any leftover `[Progressive] DIAG:` prints that weren't replaced. Remove. Re-check that no `_looks_like_trailer_fallback` WARNs fire on these live runs — if they do, the extractor missed `is_trailer` and we should investigate.

- [ ] **Step 6: Commit cleanup if anything changed**

```bash
git add modules/progressive/quote_flow.py
git commit -m "chore(progressive): remove Phase 1 diagnostic, post-live cleanup"
```

If no cleanup was needed, skip the commit. Then mark the run as validated:

```bash
git commit --allow-empty -m "validate(progressive): Phase 1 live OK — RYD trailer added, Prueba1 NON OWNED → coverage"
```

---

### Task 13: Update memory snapshot

**Files:**
- Modify: `C:/Users/Desarrollo/.claude/projects/c--Users-Desarrollo-Videos-Quotes-H2O-Quote-RPA/memory/progressive_resume_2026_06_03.md` (or create a fresh one dated today)

- [ ] **Step 1: Add a 2026-06-04 entry**

Append (or create new memory file `progressive_resume_2026_06_04.md`):

```markdown
## Sesión 2026-06-04 — PR-B Add Trailer flow + pre-existing detection

✅ Phase 0: pre-existing unit pre-check live OK. `_looks_like_trailer` substring
  reemplazado por `VehicleProfile.is_trailer` explícito del extractor.
✅ Phase 1: AddTrailerPage cotizando RYD trailer end-to-end. Prueba1 NON OWNED
  → Non-Owned Trailer Phys Damage = $25,000 default.

Nuevos baselines:
- M&D: $53,064/yr (sin cambios)
- RYD: $<nuevo> /yr (incluye DRY VAN TRAILER)
- Prueba1: $<nuevo> /yr (incluye Non-Owned Trailer Phys Damage)

Tests: 66/66 verde. Simulator OK.

Nuevo módulo: `modules/progressive/unit_matching.py` (helpers puros sin Playwright).
Nuevo page object: `modules/progressive/pages/trailers_page.py`.

Pendientes restantes del backlog:
- BI Liability $500K CSL mismatch (sin tocar en esta PR)
- Cleanup criterios #4/#5 del spec basepage-hardening
```

Update `MEMORY.md` index with a one-liner pointing to the new entry.

- [ ] **Step 2: No git commit** — memory files live outside the repo working tree

---

## Self-Review

Spec coverage:
- ✅ Trailer inclusion policy (always include) → Task 11 (loop adds every trailer)
- ✅ Pre-existing SKIP policy → Task 6 + Task 7
- ✅ NON OWNED routing → Task 5
- ✅ `is_trailer` explicit + substring fallback → Task 1, Task 2, Task 7
- ✅ `VehicleSummaryPage.list_existing_units` → Task 6
- ✅ `normalize_identifier` + `diff_unit_vs_pdf` → Task 3, Task 4
- ✅ AddTrailerPage with Comp/Coll APD-conditional path → Task 10
- ✅ Live validation against M&D / RYD fresh / RYD repeat / Prueba1 → Task 8 + Task 12
- ✅ Test plan +12 unit tests (2 + 2 + 7 + 5 + 5 + 3 + 2 = 26 new; spec said ~12; we're well-covered)

Type consistency:
- `MappedVehicle.is_trailer: bool` — Task 2 declares; Task 7 reads; ✅
- `VehicleProfile.is_trailer: bool` — Task 1 declares; Task 2 reads via `_map_vehicle`; ✅
- `normalize_identifier(vin, year, make, model)` signature — Tasks 3, 6, 7 ✅
- `diff_unit_vs_pdf(progressive_unit, pdf_unit)` argument order — Tasks 4, 7 ✅
- `ExistingUnit` produced by Task 6, consumed by Task 7 via `existing_by_id` ✅
- `_is_non_owned(vin, make, model)` — Task 5 declares and uses ✅

Placeholders: none found. Live runs (Tasks 8, 12) are not "TBD" — they are gated discovery + validation, not unfinished work.

Plan complete.

---

**Plan complete and saved to [`docs/superpowers/plans/2026-06-04-progressive-add-trailer-flow.md`](./2026-06-04-progressive-add-trailer-flow.md).**

Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Good for the discovery-pending Phase 1 where Task 9 output reshapes Task 10.
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints. Good for Phase 0 where everything is determinate.

Which approach?
