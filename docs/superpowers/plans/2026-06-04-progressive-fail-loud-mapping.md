# Progressive Fail-Loud Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the Progressive RPA from silently guessing a catch-all when a Blue Quote value doesn't map to a Progressive option; instead HALT with a diagnostic (preflight batch offline + fail-fast in-flight), so a new client fails loudly with a fixable report instead of producing a wrong quote.

**Architecture:** A central `resolve_choice()` resolver is the single point through which every "pick a Progressive option" decision flows. It returns a `Resolution` (`MATCHED` / `DEFAULTED`) or raises `UnmappableValueError`. Option catalogs (seeded from confirmed in-code lists) live as JSON and drive an offline `run_preflight()` that batches all static blockers before the browser opens. The three highest-pain guess-sites (commodity, type-of-trucker, vehicle tiles) are refactored to delegate to the resolver, enumerating real options live so the diagnostic shows what was actually on screen.

**Tech Stack:** Python 3, dataclasses, pytest (async via existing test setup), Playwright (async). No new dependencies.

---

## File Structure

- **Create** `modules/progressive/choice_resolver.py` — `Resolution` dataclass + `resolve_choice()`. Pure logic, no Playwright.
- **Create** `modules/progressive/mappings.py` — shared synonym→option tables (`VEHICLE_TILE_MAP`) and the commodity matcher wrapper, imported by both pages and preflight (DRY).
- **Create** `modules/progressive/catalogs/` — `README.md`, `business_type.json`, `type_of_trucker.json`, `vehicle_tiles.json`.
- **Create** `modules/progressive/catalogs.py` — JSON loader + cache.
- **Create** `modules/progressive/preflight.py` — `Blocker`, `PreflightReport`, `run_preflight()`.
- **Modify** `modules/progressive/pages/_exceptions.py` — add `UnmappableValueError`.
- **Modify** `modules/progressive/pages/vehicles_page.py` — `MostCommonVehiclesPage.select_vehicle_type` → resolver + live tile enumeration.
- **Modify** `modules/progressive/pages/business_info_page.py` — commodity last-resort → HALT; type-of-trucker → resolver.
- **Modify** `modules/progressive/quote_flow.py` — run preflight before browser; add `assumptions` to `QuoteResult`; catch `UnmappableValueError`.
- **Create** tests: `tests/progressive/test_choice_resolver.py`, `test_catalogs.py`, `test_preflight.py`, `test_vehicle_tile_resolution.py`, `test_commodity_resolution.py`.

---

## Task 1: `UnmappableValueError` exception

**Files:**
- Modify: `modules/progressive/pages/_exceptions.py`
- Test: `tests/progressive/test_choice_resolver.py` (created here, extended in Task 2)

- [ ] **Step 1: Write the failing test**

```python
# tests/progressive/test_choice_resolver.py
from modules.progressive.pages._exceptions import (
    UnmappableValueError,
    ExtJSInteractionError,
)


def test_unmappable_value_error_carries_context():
    err = UnmappableValueError(
        field="Business type",
        source_value="PACKED CHARCOAL",
        available_options=["Coal Hauling", "Garbage & Trash Hauling/Removal"],
    )
    assert isinstance(err, ExtJSInteractionError)   # integrates with existing except
    assert err.field == "Business type"
    assert err.source_value == "PACKED CHARCOAL"
    assert "Coal Hauling" in err.available_options
    assert err.screenshot_path is None              # offline use
    assert "PACKED CHARCOAL" in str(err)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/progressive/test_choice_resolver.py::test_unmappable_value_error_carries_context -v`
Expected: FAIL with `ImportError: cannot import name 'UnmappableValueError'`

- [ ] **Step 3: Add the exception**

Append to `modules/progressive/pages/_exceptions.py`:

```python
class UnmappableValueError(ExtJSInteractionError):
    """A Blue Quote value was present but matched no Progressive option with
    confidence, OR a critical field was absent with no default. Raised by
    resolve_choice; used both offline (preflight, screenshot_path=None) and
    in-flight (with screenshot)."""

    def __init__(
        self,
        *,
        field: str,
        source_value: Optional[str],
        available_options: list,
        screenshot_path: Optional[Path] = None,
        debug_context: Optional[dict] = None,
    ) -> None:
        super().__init__(
            f"Cannot map {field!r}: value {source_value!r} has no confident "
            f"match among {len(available_options)} options",
            primitive="resolve_choice",
            field=field,
            attempts=1,
            screenshot_path=screenshot_path,
            debug_context=debug_context,
        )
        self.source_value = source_value
        self.available_options = list(available_options)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/progressive/test_choice_resolver.py::test_unmappable_value_error_carries_context -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/progressive/pages/_exceptions.py tests/progressive/test_choice_resolver.py
git commit -m "feat(progressive): UnmappableValueError for fail-loud mapping"
```

---

## Task 2: `resolve_choice()` core resolver

**Files:**
- Create: `modules/progressive/choice_resolver.py`
- Test: `tests/progressive/test_choice_resolver.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/progressive/test_choice_resolver.py`:

```python
import pytest
from modules.progressive.choice_resolver import resolve_choice, Resolution

OPTS = ["Coal Hauling", "Beverage Distributor", "General Freight / Other",
        "Dirt, Sand and Gravel"]


def test_exact_match_returns_matched():
    r = resolve_choice("Business type", "Coal Hauling", OPTS)
    assert r.kind == "MATCHED" and r.value == "Coal Hauling" and r.note == "exact"


def test_mapping_table_match():
    r = resolve_choice("Business type", "BEER", OPTS,
                       mapping={"BEER": "Beverage Distributor"})
    assert r.kind == "MATCHED" and r.value == "Beverage Distributor"
    assert r.note == "mapping"


def test_generic_alias_routes_to_catch_all():
    r = resolve_choice("Business type", "general freight", OPTS,
                       generic_aliases=frozenset({"general freight"}))
    assert r.kind == "MATCHED" and r.value == "General Freight / Other"
    assert r.note == "generic"


def test_unique_token_match():
    r = resolve_choice("Business type", "Beverage", OPTS)
    assert r.kind == "MATCHED" and r.value == "Beverage Distributor"
    assert r.note.startswith("token")


def test_present_but_no_match_raises():
    from modules.progressive.pages._exceptions import UnmappableValueError
    with pytest.raises(UnmappableValueError) as exc:
        resolve_choice("Business type", "PACKED CHARCOAL", OPTS)
    assert exc.value.source_value == "PACKED CHARCOAL"
    assert exc.value.available_options == OPTS


def test_ambiguous_token_raises_not_guesses():
    # "hauling" appears in 2 options -> not confident -> HALT, no guess
    from modules.progressive.pages._exceptions import UnmappableValueError
    with pytest.raises(UnmappableValueError):
        resolve_choice("Business type", "hauling stuff", OPTS)


def test_absent_field_with_default_returns_defaulted():
    r = resolve_choice("GVW", None, [], default="26,001 lbs or greater")
    assert r.kind == "DEFAULTED" and r.value == "26,001 lbs or greater"
    assert r.source_value is None and r.note == "default"


def test_absent_critical_field_raises():
    from modules.progressive.pages._exceptions import UnmappableValueError
    with pytest.raises(UnmappableValueError):
        resolve_choice("vehicle tile", None, ["Pickup Truck"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/progressive/test_choice_resolver.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'modules.progressive.choice_resolver'`

- [ ] **Step 3: Implement the resolver**

Create `modules/progressive/choice_resolver.py`:

```python
"""Central decision resolver for Progressive option selection.

Single point through which every 'pick a Progressive option' decision flows.
Pure logic, no Playwright — testable offline. Returns a Resolution
(MATCHED/DEFAULTED) or raises UnmappableValueError (HALT). NEVER falls back to
a silent catch-all: a present-but-unmatchable value stops the flow with a
diagnostic instead of producing a wrong quote.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from modules.progressive.pages._exceptions import UnmappableValueError


@dataclass
class Resolution:
    field: str
    value: str
    kind: str                       # "MATCHED" | "DEFAULTED"
    source_value: Optional[str]
    note: str = ""                  # exact | mapping | generic | token:<t> | default


def _norm(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def resolve_choice(
    field: str,
    source_value: Optional[str],
    options: list,
    *,
    mapping: Optional[dict] = None,
    default: Optional[str] = None,
    generic_aliases: frozenset = frozenset(),
    screenshot_path=None,
    debug_context: Optional[dict] = None,
) -> Resolution:
    """Resolve `source_value` to one of `options`.

    source_value present  -> mapping / exact / generic-alias / unique-token,
                             else HALT (UnmappableValueError).
    source_value absent    -> default if provided, else HALT (critical).
    """
    def _halt() -> None:
        raise UnmappableValueError(
            field=field,
            source_value=source_value,
            available_options=list(options),
            screenshot_path=screenshot_path,
            debug_context=debug_context,
        )

    if source_value is None or not str(source_value).strip():
        if default is not None:
            return Resolution(field, default, "DEFAULTED", None, "default")
        _halt()

    sv = str(source_value).strip()
    sv_n = _norm(sv)
    opts_norm = {_norm(o): o for o in options}

    # 1. explicit mapping table (synonym -> option)
    if mapping:
        for k, v in mapping.items():
            if _norm(k) == sv_n:
                return Resolution(field, v, "MATCHED", sv, "mapping")

    # 2. exact option match
    if sv_n in opts_norm:
        return Resolution(field, opts_norm[sv_n], "MATCHED", sv, "exact")

    # 3. generic alias -> catch-all option (one containing 'other'/'general')
    if sv_n in {_norm(a) for a in generic_aliases}:
        catch = next(
            (o for o in options
             if "other" in o.lower() or "general" in o.lower()),
            None,
        )
        if catch is not None:
            return Resolution(field, catch, "MATCHED", sv, "generic")

    # 4. strong UNIQUE token (>=3 chars, appears in exactly one option)
    for tok in [t for t in re.findall(r"[a-z0-9]+", sv_n) if len(t) >= 3]:
        hits = [o for o in options if tok in o.lower()]
        if len(hits) == 1:
            return Resolution(field, hits[0], "MATCHED", sv, f"token:{tok}")

    # nothing confident -> HALT (never a silent catch-all)
    _halt()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/progressive/test_choice_resolver.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add modules/progressive/choice_resolver.py tests/progressive/test_choice_resolver.py
git commit -m "feat(progressive): resolve_choice central resolver"
```

---

## Task 3: Option catalogs + loader

**Files:**
- Create: `modules/progressive/catalogs/README.md`
- Create: `modules/progressive/catalogs/type_of_trucker.json`
- Create: `modules/progressive/catalogs/vehicle_tiles.json`
- Create: `modules/progressive/catalogs/business_type.json`
- Create: `modules/progressive/catalogs.py`
- Test: `tests/progressive/test_catalogs.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/progressive/test_catalogs.py
import pytest
from modules.progressive.catalogs import load_catalog, Catalog

NAMES = ["type_of_trucker", "vehicle_tiles", "business_type"]


@pytest.mark.parametrize("name", NAMES)
def test_catalog_loads_with_options_and_metadata(name):
    cat = load_catalog(name)
    assert isinstance(cat, Catalog)
    assert cat.options, f"{name} has empty options"
    assert cat.captured, f"{name} missing capture date"
    assert all(isinstance(o, str) and o for o in cat.options)


def test_catalog_is_cached():
    assert load_catalog("vehicle_tiles") is load_catalog("vehicle_tiles")


def test_generic_aliases_present_for_business_type():
    assert "general freight" in load_catalog("business_type").generic_aliases
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/progressive/test_catalogs.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'modules.progressive.catalogs'`

- [ ] **Step 3: Create the JSON catalogs**

`modules/progressive/catalogs/type_of_trucker.json` (seeded from `TRUCKER_SUBTYPES` in business_info_page.py, confirmed live 2026-06-04 JUAREZ DIAG):

```json
{
  "field": "Type of Trucker",
  "captured": "2026-06-04",
  "source": "business_info_page.TRUCKER_SUBTYPES + DIAG JUAREZ run",
  "options": [
    "Agricultural", "Auto Hauler", "Coal", "Containers", "Debris Removal",
    "Dirt, Sand and Gravel", "Escort Vehicles", "Expediters",
    "Fracking, Sand or Water", "Freight Forwarder", "Garbage & Trash",
    "General Freight / Other", "Hazardous Materials / Placards",
    "Hotshot Transport", "Household Goods Mover", "Livestock",
    "Logging / Wood Chips", "Machinery & Heavy Equipment",
    "Mobile Home Toter", "Oilfield Materials", "Refrigerated Goods"
  ],
  "generic_aliases": ["general freight", "mixed", "other", "trucker"]
}
```

`modules/progressive/catalogs/vehicle_tiles.json` (seeded from `VEHICLE_TYPES` in vehicles_page.py; `Dump Truck` confirmed live on the picker. Note: live enumeration is authoritative in-flight — this catalog is only for offline preflight):

```json
{
  "field": "Vehicle tile",
  "captured": "2026-06-04",
  "source": "vehicles_page.VEHICLE_TYPES + live picker (Dump Truck)",
  "options": [
    "Truck Tractor", "Box Truck", "Pickup Truck", "Flatbed Truck",
    "Cargo Van", "Dump Truck", "Other / Not Listed"
  ],
  "generic_aliases": ["other"]
}
```

`modules/progressive/catalogs/business_type.json` (seeded from the option targets in `_map_commodity_to_option` table + General Freight Hauler):

```json
{
  "field": "Business type",
  "captured": "2026-06-04",
  "source": "business_info_page._map_commodity_to_option table targets",
  "options": [
    "Dirt Sand & Gravel (For A Fee)", "Fracking Sand Hauling", "Coal Hauling",
    "Auto Hauler (For Hire Trucking)", "Livestock Hauling (For A Fee)",
    "Logging Trucker", "Garbage & Trash Hauling/Removal",
    "Hazardous Materials Hauling", "Container Hauling",
    "Agricultural Hauling (For A Fee)", "Dairy Products Hauling (For A Fee)",
    "Frozen Foods Hauling", "Beverage Distributor", "General Freight Hauler"
  ],
  "generic_aliases": ["general freight", "mixed", "other", "freight"]
}
```

`modules/progressive/catalogs/README.md`:

```markdown
# Progressive option catalogs

Each JSON lists the valid Progressive options for one field, used by
`preflight.py` to validate a Blue Quote OFFLINE before opening the browser.

In-flight, pages enumerate the REAL on-screen options (live is authoritative);
these catalogs are the offline pre-check only.

## Refreshing a catalog (when Progressive changes its options)

1. Run a quote live with the DIAG dump enabled for the field.
2. Copy the `[Progressive] DIAG combos/options: [...]` line from the log.
3. Replace `options` in the JSON and bump `captured` to today.
4. `python -m pytest tests/progressive/test_catalogs.py -v` must stay green.
```

- [ ] **Step 4: Create the loader**

`modules/progressive/catalogs.py`:

```python
"""Loader + cache for Progressive option catalogs (catalogs/*.json)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).parent / "catalogs"


@dataclass(frozen=True)
class Catalog:
    field: str
    captured: str
    options: tuple
    generic_aliases: frozenset = field(default_factory=frozenset)


@lru_cache(maxsize=None)
def load_catalog(name: str) -> Catalog:
    """Load catalogs/<name>.json. Cached; same name returns the same object."""
    path = _DIR / f"{name}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return Catalog(
        field=data["field"],
        captured=data["captured"],
        options=tuple(data["options"]),
        generic_aliases=frozenset(
            a.lower() for a in data.get("generic_aliases", [])
        ),
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/progressive/test_catalogs.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
git add modules/progressive/catalogs modules/progressive/catalogs.py tests/progressive/test_catalogs.py
git commit -m "feat(progressive): option catalogs seeded from in-code lists + loader"
```

---

## Task 4: Shared mapping tables (`mappings.py`)

**Files:**
- Create: `modules/progressive/mappings.py`
- Test: `tests/progressive/test_commodity_resolution.py` (created here)

Rationale: the commodity matcher and the vehicle-tile map are used by BOTH the
page objects and preflight. Centralize them so the offline pre-check and the
live run agree.

- [ ] **Step 1: Write the failing test**

```python
# tests/progressive/test_commodity_resolution.py
from modules.progressive.mappings import (
    VEHICLE_TILE_MAP,
    map_commodity,
)


def test_map_commodity_specific_hit():
    opt, generic = map_commodity("BEVERAGE DISTRIBUTION")
    assert opt == "Beverage Distributor" and generic is False


def test_map_commodity_general_freight_is_generic():
    opt, generic = map_commodity("DRY VAN FREIGHT")
    assert opt == "General Freight Hauler" and generic is True


def test_map_commodity_packed_charcoal_does_not_hit_coal():
    opt, generic = map_commodity("PACKED CHARCOAL")
    assert opt is None and generic is False    # -> caller HALTs


def test_vehicle_tile_map_has_core_types():
    assert VEHICLE_TILE_MAP["FLATBED"] == "Flatbed Truck"
    assert VEHICLE_TILE_MAP["DUMP"] == "Dump Truck"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/progressive/test_commodity_resolution.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'modules.progressive.mappings'`

- [ ] **Step 3: Implement `mappings.py`**

Move the existing matcher logic out of `business_info_page._map_commodity_to_option` into a shared, side-effect-free function. `map_commodity` returns `(option_or_None, is_generic)`:

```python
"""Shared Blue-Quote -> Progressive option mappings (used by pages + preflight)."""

from __future__ import annotations

import re
from typing import Optional, Tuple

# Vehicle-tile synonyms (token -> Progressive tile label).
VEHICLE_TILE_MAP = {
    "FLATBED": "Flatbed Truck",
    "BOX": "Box Truck",
    "PICKUP": "Pickup Truck",
    "CARGO": "Cargo Van",
    "VAN": "Cargo Van",
    "TRACTOR": "Truck Tractor",
    "DUMP": "Dump Truck",
}

# Commodity table: (synonym keys, Progressive Business-type option).
_COMMODITY_TABLE = [
    (("DIRT", "SAND", "GRAVEL"), "Dirt Sand & Gravel (For A Fee)"),
    (("FRACK", "FRACKING"), "Fracking Sand Hauling"),
    (("COAL",), "Coal Hauling"),
    (("AUTO HAUL", "CAR HAUL", "AUTO HAULER", "CAR HAULER"),
     "Auto Hauler (For Hire Trucking)"),
    (("LIVESTOCK",), "Livestock Hauling (For A Fee)"),
    (("LOG", "LOGGING", "WOOD CHIP", "WOOD CHIPS"), "Logging Trucker"),
    (("GARBAGE", "TRASH"), "Garbage & Trash Hauling/Removal"),
    (("HAZARD", "HAZMAT", "HAZARDOUS"), "Hazardous Materials Hauling"),
    (("CONTAINER", "CONTAINERS"), "Container Hauling"),
    (("AGRICULTUR", "AGRICULTURAL", "AGRICULTURE", "FARM PRODUCE"),
     "Agricultural Hauling (For A Fee)"),
    (("DAIRY",), "Dairy Products Hauling (For A Fee)"),
    (("REFRIG", "REFRIGERATED", "REEFER", "FROZEN"), "Frozen Foods Hauling"),
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
    return (None, False)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/progressive/test_commodity_resolution.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add modules/progressive/mappings.py tests/progressive/test_commodity_resolution.py
git commit -m "feat(progressive): shared mappings.py (commodity matcher + vehicle tiles)"
```

---

## Task 5: Preflight batch check

**Files:**
- Create: `modules/progressive/preflight.py`
- Test: `tests/progressive/test_preflight.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/progressive/test_preflight.py
from modules.progressive.field_mapper import MappedFields, MappedVehicle
from modules.progressive.preflight import run_preflight, PreflightReport


def _fields(commodity, vehicle_type):
    return MappedFields(
        usdot="123", business_name="X LLC", effective_date="06/15/2026",
        owner_name="Owner", commodity=commodity,
        vehicles=[MappedVehicle(trailer_type=vehicle_type)],
    )


def test_clean_fields_no_blockers():
    rep = run_preflight(_fields("BEVERAGE DISTRIBUTION", "FLATBED"))
    assert isinstance(rep, PreflightReport)
    assert rep.ok() and rep.blockers == []


def test_unmappable_commodity_blocks():
    rep = run_preflight(_fields("PACKED CHARCOAL", "FLATBED"))
    assert not rep.ok()
    assert any(b.field == "Business type" and b.source_value == "PACKED CHARCOAL"
               for b in rep.blockers)


def test_collects_all_blockers_in_one_pass():
    rep = run_preflight(_fields("PACKED CHARCOAL", "MONORAIL SLED"))
    # both commodity AND vehicle fail, both reported (NOT fail-fast)
    fields = {b.field for b in rep.blockers}
    assert "Business type" in fields and "Vehicle tile" in fields


def test_generic_commodity_is_assumption_not_blocker():
    rep = run_preflight(_fields("DRY VAN FREIGHT", "FLATBED"))
    assert rep.ok()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/progressive/test_preflight.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'modules.progressive.preflight'`

- [ ] **Step 3: Implement preflight**

Create `modules/progressive/preflight.py`:

```python
"""Offline batch pre-check: validate a MappedFields against option catalogs
BEFORE opening the browser. Collects ALL static blockers in one pass (not
fail-fast) so the operator fixes everything before re-running."""

from __future__ import annotations

import json
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import List, Optional

from modules.progressive.field_mapper import MappedFields
from modules.progressive.catalogs import load_catalog
from modules.progressive.choice_resolver import Resolution
from modules.progressive.mappings import map_commodity, VEHICLE_TILE_MAP
from modules.progressive.pages._exceptions import UnmappableValueError


@dataclass
class Blocker:
    field: str
    source_value: Optional[str]
    available_options: list
    suggestion: str = ""


@dataclass
class PreflightReport:
    blockers: List[Blocker] = dc_field(default_factory=list)
    assumptions: List[Resolution] = dc_field(default_factory=list)

    def ok(self) -> bool:
        return not self.blockers


def _check_commodity(mapped: MappedFields, rep: PreflightReport) -> None:
    cat = load_catalog("business_type")
    commodity = (mapped.commodity or "").strip()
    if not commodity:
        return  # absence handled by field_mapper defaults (Trucker)
    opt, is_generic = map_commodity(commodity)
    if opt is not None:
        rep.assumptions.append(
            Resolution("Business type", opt, "MATCHED", commodity,
                       "generic" if is_generic else "mapping")
        )
        return
    rep.blockers.append(Blocker(
        field="Business type",
        source_value=commodity,
        available_options=list(cat.options),
        suggestion="Add a mapping in mappings._COMMODITY_TABLE or fix the Blue Quote.",
    ))


def _check_vehicle_tiles(mapped: MappedFields, rep: PreflightReport) -> None:
    cat = load_catalog("vehicle_tiles")
    for i, v in enumerate(mapped.vehicles):
        src = (v.trailer_type or "").strip()
        if not src:
            continue
        token = next((k for k in VEHICLE_TILE_MAP if k in src.upper()), None)
        if token is not None:
            continue
        rep.blockers.append(Blocker(
            field="Vehicle tile",
            source_value=f"vehicle[{i}]: {src}",
            available_options=list(cat.options),
            suggestion="Add a token to mappings.VEHICLE_TILE_MAP or fix the Blue Quote.",
        ))


def run_preflight(mapped: MappedFields) -> PreflightReport:
    rep = PreflightReport()
    _check_commodity(mapped, rep)
    _check_vehicle_tiles(mapped, rep)
    return rep


def format_report(rep: PreflightReport, business: str) -> str:
    lines = [f"PREFLIGHT — {business}"]
    if rep.blockers:
        lines.append(f"BLOCKERS ({len(rep.blockers)}) — resolvé antes de re-correr:")
        for b in rep.blockers:
            lines.append(f"  - {b.field}: {b.source_value!r} no matchea.")
            lines.append(f"      Opciones: {', '.join(b.available_options[:8])}...")
            lines.append(f"      Acción: {b.suggestion}")
    if rep.assumptions:
        lines.append(f"ASSUMPTIONS ({len(rep.assumptions)}):")
        for a in rep.assumptions:
            lines.append(f"  - {a.field} = {a.value} ({a.note})")
    return "\n".join(lines)


def write_report(rep: PreflightReport, business: str, output_dir: str = "logs") -> Path:
    safe = "".join(ch if ch.isalnum() else "_" for ch in business)[:40]
    path = Path(output_dir) / f"progressive_preflight_{safe}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "business": business,
        "blockers": [vars(b) for b in rep.blockers],
        "assumptions": [vars(a) for a in rep.assumptions],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/progressive/test_preflight.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add modules/progressive/preflight.py tests/progressive/test_preflight.py
git commit -m "feat(progressive): offline preflight batch check"
```

---

## Task 6: Gate `quote_flow.run` on preflight + add `assumptions` to result

**Files:**
- Modify: `modules/progressive/quote_flow.py:50-56` (QuoteResult) and `:80-92` (run head)
- Test: `tests/progressive/test_preflight.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/progressive/test_preflight.py`:

```python
import asyncio
from modules.progressive.quote_flow import QuoteFlow, QuoteResult


def test_quoteresult_has_assumptions_field():
    r = QuoteResult()
    assert hasattr(r, "assumptions") and r.assumptions == []


def test_run_halts_before_browser_on_blocker(monkeypatch):
    # PACKED CHARCOAL blocks at preflight; run() must return WITHOUT login.
    flow = QuoteFlow.__new__(QuoteFlow)          # bypass __init__/browser
    flow.dry_run = True

    called = {"login": False}

    async def _boom(*a, **k):
        called["login"] = True
        raise AssertionError("browser should not open on preflight blocker")

    monkeypatch.setattr("modules.progressive.quote_flow.LoginPage", _boom)

    fields = MappedFields(
        usdot="1", business_name="JUAREZ LLC", effective_date="06/15/2026",
        owner_name="O", commodity="PACKED CHARCOAL",
        vehicles=[MappedVehicle(trailer_type="FLATBED")],
    )
    result = asyncio.get_event_loop().run_until_complete(flow.run(fields))
    assert not result.success
    assert "preflight" in (result.error or "").lower()
    assert called["login"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/progressive/test_preflight.py::test_quoteresult_has_assumptions_field tests/progressive/test_preflight.py::test_run_halts_before_browser_on_blocker -v`
Expected: FAIL (`assumptions` attribute missing / browser opens)

- [ ] **Step 3: Add `assumptions` to QuoteResult**

In `modules/progressive/quote_flow.py`, modify the `QuoteResult` dataclass (around line 56):

```python
@dataclass
class QuoteResult:
    """Result of a Progressive quote attempt."""
    success: bool = False
    step_reached: str = ""
    error: Optional[str] = None
    screenshot_path: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)   # DEFAULTED resolutions
    # Quote details (when success)
    price: Optional[QuotePrice] = None
```

- [ ] **Step 4: Add the preflight gate at the top of `run`**

Add near the top of `quote_flow.py` imports:

```python
from modules.progressive.preflight import run_preflight, format_report, write_report
```

In `run()`, immediately after `result = QuoteResult()` (line ~82) and BEFORE the `try`/login:

```python
        # Preflight: validate against catalogs offline. If any blocker, do NOT
        # open the browser — hand back a batched report so the operator fixes
        # everything before re-running (kills the fix-rerun-break cycle).
        report = run_preflight(fields)
        result.assumptions = [f"{a.field} = {a.value}" for a in report.assumptions]
        if not report.ok():
            business = fields.business_name or "unknown"
            text = format_report(report, business)
            path = write_report(report, business)
            print(text)
            print(f"    [Progressive] preflight report written to {path}")
            result.step_reached = "preflight"
            result.error = (
                f"preflight: {len(report.blockers)} blocker(s) — "
                f"see {path}"
            )
            return result
```

- [ ] **Step 5: Catch `UnmappableValueError` in the run except block**

In `run()`, modify the trailing except handlers (around line 162-170) so an in-flight HALT is reported with its screenshot:

```python
        except UnmappableValueError as e:
            result.error = (
                f"HALT at '{result.step_reached}': {e.field} value "
                f"{e.source_value!r} matched no option. Options: "
                f"{', '.join(map(str, e.available_options[:8]))}"
            )
            result.screenshot_path = (
                str(e.screenshot_path) if e.screenshot_path
                else await self._take_error_screenshot(result.step_reached)
            )
            return result
        except RuntimeError as e:
            result.error = str(e)
            result.screenshot_path = await self._take_error_screenshot(result.step_reached)
            return result
        except Exception as e:
            result.error = f"Unexpected error at step '{result.step_reached}': {e}"
            result.screenshot_path = await self._take_error_screenshot(result.step_reached)
            return result
```

Add the import near the top of `quote_flow.py`:

```python
from modules.progressive.pages._exceptions import UnmappableValueError
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/progressive/test_preflight.py -v`
Expected: PASS (6 tests)

- [ ] **Step 7: Commit**

```bash
git add modules/progressive/quote_flow.py tests/progressive/test_preflight.py
git commit -m "feat(progressive): gate quote_flow on preflight + assumptions + in-flight HALT"
```

---

## Task 7: Refactor vehicle-tile selection to resolve_choice (live enumeration)

**Files:**
- Modify: `modules/progressive/pages/vehicles_page.py:271-311` (`MostCommonVehiclesPage`)
- Test: `tests/progressive/test_vehicle_tile_resolution.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/progressive/test_vehicle_tile_resolution.py
import pytest
from modules.progressive.pages.vehicles_page import MostCommonVehiclesPage
from modules.progressive.pages._exceptions import UnmappableValueError


class _FakePage:
    def __init__(self): self.clicked = None


def _mk(tiles):
    obj = MostCommonVehiclesPage.__new__(MostCommonVehiclesPage)

    async def _enum():
        return tiles
    obj._enumerate_tiles = _enum            # stub live enumeration
    return obj


@pytest.mark.asyncio
async def test_resolve_tile_matches_flatbed():
    page = _mk(["Truck Tractor", "Flatbed Truck", "Pickup Truck"])
    res = await page.resolve_tile("FLATBED DRY VAN")
    assert res.value == "Flatbed Truck"


@pytest.mark.asyncio
async def test_resolve_tile_halts_when_absent():
    # sand & gravel: no matching tile on screen -> HALT, NOT 'Other / Not Listed'
    page = _mk(["Truck Tractor", "Pickup Truck", "Dump Truck"])
    with pytest.raises(UnmappableValueError) as exc:
        await page.resolve_tile("MONORAIL SLED")
    assert "Dump Truck" in exc.value.available_options
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/progressive/test_vehicle_tile_resolution.py -v`
Expected: FAIL (`AttributeError: ... has no attribute 'resolve_tile'`)

- [ ] **Step 3: Refactor `MostCommonVehiclesPage`**

In `modules/progressive/pages/vehicles_page.py`, replace `_map_to_button` and update `select_vehicle_type`. Add imports at top of file:

```python
from modules.progressive.choice_resolver import resolve_choice, Resolution
from modules.progressive.mappings import VEHICLE_TILE_MAP
```

Replace the body of `MostCommonVehiclesPage.select_vehicle_type` and the old `_map_to_button`:

```python
    async def _enumerate_tiles(self) -> list:
        """Read the vehicle-type tile labels actually rendered on screen."""
        try:
            return await self.page.evaluate(
                """() => Array.from(document.querySelectorAll(
                    '.x-btn-inner, [role=button], .tile, button'
                )).filter(el => el.offsetParent !== null)
                  .map(el => (el.innerText || '').trim())
                  .filter(t => t.length > 0)"""
            )
        except Exception:
            return list(VEHICLE_TILE_MAP.values())   # offline/test fallback

    async def resolve_tile(self, trailer_type: str) -> Resolution:
        """Resolve the Blue-Quote vehicle string to a tile actually on screen.
        Raises UnmappableValueError (HALT) instead of guessing a catch-all."""
        options = await self._enumerate_tiles()
        # Convert the synonym map into a {source-string: tile} mapping for any
        # token present in trailer_type, so 'FLATBED DRY VAN' -> 'Flatbed Truck'.
        t = (trailer_type or "").upper()
        token = next((k for k in VEHICLE_TILE_MAP if k in t), None)
        mapping = {trailer_type: VEHICLE_TILE_MAP[token]} if token else None
        screenshot = await self.screenshot("vehicle_tile_unmapped")
        return resolve_choice(
            "Vehicle tile", trailer_type, options,
            mapping=mapping, screenshot_path=screenshot,
        )

    async def select_vehicle_type(self, trailer_type: str) -> None:
        """Pick the most appropriate tile for the trailer string, or HALT."""
        res = await self.resolve_tile(trailer_type)
        print(f"    [Progressive] Selecting vehicle type: {res.value} ({res.note})")
        tile = self.page.get_by_text(res.value, exact=True).first
        await tile.click(force=True)
        await self.wait_for_extjs_idle()
```

Note: `resolve_tile` takes the screenshot before resolving so a HALT carries
the on-screen state; on the success path the unused screenshot is harmless.
Remove the now-unused `VEHICLE_TYPES` constant only if nothing else imports it
(grep first; `field_mapper`/tests may reference it — leave it if so).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/progressive/test_vehicle_tile_resolution.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add modules/progressive/pages/vehicles_page.py tests/progressive/test_vehicle_tile_resolution.py
git commit -m "feat(progressive): vehicle-tile selection via resolve_choice (HALT not catch-all)"
```

---

## Task 8: Refactor commodity + type-of-trucker to fail loud

**Files:**
- Modify: `modules/progressive/pages/business_info_page.py` — `_select_business_type` (~L432), `_map_commodity_to_option` (~L490, now delegates to `mappings.map_commodity`), `_answer_type_of_trucker` (~L565)
- Test: `tests/progressive/test_commodity_resolution.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/progressive/test_commodity_resolution.py`:

```python
import pytest
from modules.progressive.pages.business_info_page import BusinessInfoPage
from modules.progressive.pages._exceptions import UnmappableValueError


def _biz():
    return BusinessInfoPage.__new__(BusinessInfoPage)


def test_unmappable_commodity_raises_instead_of_trucker():
    biz = _biz()
    # PACKED CHARCOAL no longer silently routes to 'Trucker'
    with pytest.raises(UnmappableValueError) as exc:
        biz.resolve_business_type("PACKED CHARCOAL")
    assert exc.value.source_value == "PACKED CHARCOAL"


def test_specific_commodity_resolves():
    biz = _biz()
    res = biz.resolve_business_type("BEVERAGE DISTRIBUTION")
    assert res.value == "Beverage Distributor"


def test_general_freight_resolves_generic():
    biz = _biz()
    res = biz.resolve_business_type("DRY VAN FREIGHT")
    assert res.value == "General Freight Hauler"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/progressive/test_commodity_resolution.py -v`
Expected: FAIL (`AttributeError: ... has no attribute 'resolve_business_type'`)

- [ ] **Step 3: Add `resolve_business_type` and wire `_select_business_type`**

In `modules/progressive/pages/business_info_page.py`, add imports at top:

```python
from modules.progressive.choice_resolver import resolve_choice, Resolution
from modules.progressive.mappings import map_commodity
from modules.progressive.catalogs import load_catalog
```

Add a pure resolver method and rewrite `_map_commodity_to_option`'s caller. Replace `_map_commodity_to_option` body to delegate to the shared matcher, and add `resolve_business_type`:

```python
    def resolve_business_type(self, commodity: Optional[str]) -> Resolution:
        """Resolve commodity -> Business type option, or HALT (no silent Trucker).

        Specific hit -> MATCHED. General-freight family -> MATCHED (generic).
        Anything else present-but-unmapped -> UnmappableValueError.
        """
        cat = load_catalog("business_type")
        opt, is_generic = map_commodity(commodity)
        if opt is not None:
            note = "generic" if is_generic else "mapping"
            return Resolution("Business type", opt, "MATCHED", commodity, note)
        # present but no confident match -> HALT (was: silent 'Trucker')
        raise UnmappableValueError(
            field="Business type",
            source_value=commodity,
            available_options=list(cat.options),
        )
```

Then update `_select_business_type` (~L432) to use it. Replace the `search_term, preferred = self._map_commodity_to_option(commodity)` block and the unmappable→Trucker fallback (lines ~444-488) with:

```python
        if not commodity:
            print("    [Progressive] WARN: no commodity provided, skipping")
            return
        # Resolve up front — raises UnmappableValueError (HALT) for a present
        # but unmappable commodity instead of silently selecting 'Trucker'.
        res = self.resolve_business_type(commodity)
        print(f"    [Progressive] Business type: '{commodity}' -> '{res.value}' ({res.note})")
        combo = await self._business_type_combo()       # existing locator helper
        await self.safe_select_combo(combo, res.value)
```

Keep the existing `_business_type_combo()` locator logic (extract it from the
current `_select_business_type` if it is inline). Delete the dead
`_map_commodity_to_option` method and its `_TYPE_OF_TRUCKER_DEFAULT`-via-fallback
path.

- [ ] **Step 4: Make `_answer_type_of_trucker` fail loud**

Replace `_answer_type_of_trucker` (~L565) so it enumerates the live options and
resolves the commodity against them, HALTing instead of clicking the first
non-empty option. The Type-of-Trucker sub-classification uses the commodity as
its source, `General Freight / Other` only as the generic catch-all:

```python
    async def _answer_type_of_trucker(self, commodity: Optional[str]) -> None:
        """Conditional combobox (business type = Trucker). Resolve commodity to
        a subtype; HALT if present-but-unmatched (was: click first non-empty)."""
        await self.page.wait_for_timeout(800)   # let ExtJS render the conditional
        combo = self.find_combo("Type of Trucker")    # existing finder pattern
        if not await self.field_exists(combo, wait_ms=1500):
            return                                    # CONDITIONAL absent — fine
        await combo.click(timeout=5_000)
        await self.page.wait_for_timeout(300)
        raw = await self.page.get_by_role("option").all_inner_texts()
        options = [o.strip() for o in raw
                   if o.strip() and o.strip() not in self._TYPE_OF_TRUCKER_HEADERS]
        screenshot = await self.screenshot("type_of_trucker_unmapped")
        res = resolve_choice(
            "Type of Trucker", commodity, options,
            default=self._TYPE_OF_TRUCKER_DEFAULT,    # used only when commodity absent
            generic_aliases=frozenset({"general freight", "mixed", "other", "trucker"}),
            screenshot_path=screenshot,
        )
        await self.page.get_by_role("option", name=res.value, exact=True).first.click(timeout=5_000)
        await self.page.wait_for_timeout(800)
        print(f"    [Progressive] Type of Trucker = {res.value!r} ({res.note})")
```

Update the call site of `_answer_type_of_trucker()` to pass the commodity
(`await self._answer_type_of_trucker(fields.commodity)`).

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/progressive/test_commodity_resolution.py -v`
Expected: PASS (7 tests)

- [ ] **Step 6: Commit**

```bash
git add modules/progressive/pages/business_info_page.py tests/progressive/test_commodity_resolution.py
git commit -m "feat(progressive): commodity + type-of-trucker fail loud (HALT not silent Trucker)"
```

---

## Task 9: Full no-regression pass + live validation

**Files:** none (verification only)

- [ ] **Step 1: Run the full unit suite**

Run: `python -m pytest tests/progressive/ -q`
Expected: PASS — the prior 81 tests plus the new ones (no regressions).

- [ ] **Step 2: Run the simulator**

Run: `python tests/simulate_progressive.py`
Expected: `success=True $53,064/yr` — M&D (Trucker, mappable commodity) path unchanged.

- [ ] **Step 3: Live validation — mappable client (baseline preserved)**

Run:
```bash
$env:PYTHONIOENCODING="utf-8"
python -u scripts\run_progressive_from_pdf.py "data\input\20260601 BLUE QUOTE Prueba1.pdf" 06/15/2026
```
Expected: reaches RATES with a premium; `assumptions` listed at the end (GVW, radius); NO preflight blockers.

- [ ] **Step 4: Live validation — unmappable client (HALT works)**

Use a Blue Quote whose commodity is unmappable (e.g. REPUBLIC AGGREGATE sand & gravel, or JUAREZ if its commodity falls through). Expected: preflight prints a BLOCKER report, writes `logs/progressive_preflight_*.json`, and the browser never opens. Confirm the report names the field + value + suggested options.

- [ ] **Step 5: Commit any fixups**

```bash
git add -A
git commit -m "test(progressive): no-regression + live validation of fail-loud mapping"
```

---

## Self-Review notes

- **Spec coverage:** S1 resolver → Tasks 1-2. S2 catalogs+preflight → Tasks 3,5. Shared mappings (DRY) → Task 4. S3 integration (3 sites + assumption log + in-flight HALT) → Tasks 6,7,8. S4 testing → embedded per task + Task 9.
- **Type consistency:** `Resolution(field, value, kind, source_value, note)` positional order is identical in choice_resolver, preflight, business_info_page. `resolve_choice(field, source_value, options, *, mapping, default, generic_aliases, screenshot_path, debug_context)` signature matches every call site. `UnmappableValueError(field=, source_value=, available_options=, screenshot_path=, debug_context=)` keyword-only, matches every raise.
- **Out of scope (per spec):** other 5 pages, catalog crawler, non-owned-trailer UI bug, trailer flow Phase 1.
- **Known integration risk to confirm during execution:** `_business_type_combo()` and `find_combo("Type of Trucker")` assume existing locator helpers in business_info_page.py — extract/rename as needed when implementing Task 8; the existing inline locator code is the source of truth.
```