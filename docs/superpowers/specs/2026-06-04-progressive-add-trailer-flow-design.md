# Progressive — Add Trailer Flow + Pre-existing Unit Detection

**Date:** 2026-06-04
**Status:** Design — Approved
**Branch:** `progressive-basepage-hardening` (continuation; new sub-branch TBD at implementation time)
**Related:** `2026-06-02-progressive-basepage-hardening-design.md`

## Problem

The Progressive RPA currently SKIPS all trailers with a WARN log (`quote_flow._add_all_vehicles`, gated by `_looks_like_trailer` substring heuristic). Two operational consequences:

1. Quotes with trailer-only coverage requirements (e.g. RYD LLC's 2021 UTIL DRY VAN TRAILER with explicit Value) under-cover the customer's actual exposure.
2. Quotes for non-owned trailer scenarios (e.g. Prueba1 NOBLE LOGISTICS with VIN="NON OWNED" End Dump Trailer) silently drop the coverage entirely.

A second, parallel issue surfaced during the basepage-hardening refactor: Progressive remembers vehicles+trailers between quotes for the same USDOT. When we re-quote a previously-attempted USDOT, those units appear in VehicleSummary pre-loaded with Edit/Remove buttons. Today the bot does not detect pre-existing units and would attempt to add duplicates, which Progressive rejects with confusing validation banners.

## Goal

End-to-end coverage for the trailer flow:

- Cargo trailers with real VINs get added through Progressive's separate "Add Trailer" form, mirroring the existing AddVehicle path.
- Non-owned trailers get routed to Non-Owned Trailer Physical Damage coverage on the RATES page (which already exists at `coverages_rates_page.py:1030`), not added as units.
- Pre-existing units in VehicleSummary are detected and skipped on the second pass, with a WARN listing field-level diffs between PDF data and the unit Progressive remembers.

## Non-Goals

- EDIT flow for pre-existing units with diffs (decision: SKIP, log diffs, do not mutate Progressive's remembered state).
- Trailer add-on coverages beyond Non-Owned Trailer Phys Damage (e.g. trailer interchange) — out of scope for PR-B.
- Strategy/inheritance abstraction over Vehicle vs Trailer adders — YAGNI; only two unit types exist.

## Business Decisions (locked-in)

1. **Trailer inclusion policy:** include every trailer extracted from the PDF, with or without a Value column. Trailers without Value → liability-only (Comp/Coll = No), mirroring the PR-A APD-conditional pattern already established for powered vehicles.
2. **Pre-existing conflict policy:** SKIP. Log WARN with field-level diffs (PDF value vs Progressive value). Operator decides whether to re-run with a clean USDOT or accept the existing state. No automatic Edit.
3. **NON OWNED handling:** filter out of the unit list at field_mapper time, bump `CoveragesProfile.non_owned_trailer_phys_damage_limit` to `$25,000` if the operator hasn't set it. The existing rates-page handler does the rest.

## Architecture

Three components, in line with the module's existing separation (Page Object owns DOM, field_mapper owns data normalization, quote_flow owns orchestration):

```
EXTRACTOR (modules/pdf_extractor.py + document_ai_extractor.py)
  └─ NEW: sets VehicleProfile.is_trailer = True for entries that came
     from the trailer table. Eliminates the substring heuristic.

QUOTE_PROFILE (modules/quote_profile.py)
  └─ NEW: VehicleProfile.is_trailer: bool = False
  └─ (no other schema changes)

FIELD_MAPPER (modules/progressive/field_mapper.py)
  └─ NEW: MappedVehicle.is_trailer: bool = False (propagated from VehicleProfile)
  └─ map_profile_to_fields():
      - iterates vehicles, maps as today; propagates is_trailer
      - NEW: detects NON OWNED markers in vin/make/model (post-map filter)
        ├─ removes them from mapped_vehicles list
        └─ if coverages.non_owned_trailer_phys_damage_limit is None
             → sets default "$25,000"
      - returns MappedFields with vehicles pre-filtered

QUOTE_FLOW (modules/progressive/quote_flow.py::_add_all_vehicles)
  └─ summary.list_existing_units() → set of identifiers in the quote
  └─ pre-check: for v in fields.vehicles, SKIP+WARN if identifier already
     present in VehicleSummary
  └─ split remaining (to_add) into powered vs trailers via v.is_trailer
     (replaces the current _looks_like_trailer substring heuristic)
  └─ powered loop → add_vehicle() → MostCommonVehicles → AddVehiclePage
  └─ trailer loop  → summary.add_trailer() → AddTrailerPage
  └─ summary.click_continue()

PAGES (modules/progressive/pages/vehicles_page.py + new trailers_page.py)
  └─ VehicleSummaryPage.list_existing_units() — NEW
  └─ AddTrailerPage — NEW (selectors filled during Phase 1 diagnostic)
```

The existing `_looks_like_trailer` substring helper in `quote_flow.py` becomes redundant once `is_trailer` is explicit and gets removed in the same PR. As a safety net during the transition, `is_trailer` defaults to `False` and the field_mapper falls back to the substring check ONLY when the extractor failed to set the flag (older cached fixtures, hand-built profiles in tests). The fallback prints a one-line WARN so we notice if it ever fires in production.

The work splits into two phases:

- **Phase 0** — pre-existing detection + NON OWNED routing. Mergeable independently; validates against any quote with previously-loaded units.
- **Phase 1** — AddTrailerPage implementation. Blocked on a live diagnostic dump of Progressive's trailer form, since we don't have the selectors yet.

## Phase 0 — Pre-existing Unit Detection

### `VehicleSummaryPage.list_existing_units()`

```python
@dataclass
class ExistingUnit:
    identifier: str           # normalize_identifier output
    vin: Optional[str]
    year: Optional[int]
    make: Optional[str]
    model: Optional[str]
    is_trailer: bool          # detected from row/section, fallback False
    row_locator: Locator      # kept for future Edit support; unused in Phase 0

async def list_existing_units(self) -> List[ExistingUnit]:
    """Read VehicleSummary DOM and return units already in the quote.

    Returns [] when:
      - landing on MostCommonVehicles (fresh quote, no list rendered)
      - empty VehicleSummary
      - DOM read fails (best-effort; logs WARN, never raises)
    """
```

Wait for `wait_for_extjs_idle` + short poll (~3s max) for at least one row when the page header reads "Here are the vehicles on the quote:". Tentative selectors (confirmed during Phase 0 live test):

- Rows: filter `[role="row"]` by presence of an "Edit" or "Remove" button
- Trailer vs vehicle: section header text or row badge. If we cannot reliably distinguish, fall back to identifier-only matching and let routing decide later.

### `normalize_identifier()`

Pure helper, no Playwright dependency.

```python
def normalize_identifier(
    vin: Optional[str],
    year: Optional[int],
    make: Optional[str],
    model: Optional[str],
) -> Optional[str]:
    """Compose a stable identifier for matching units across PDF↔Progressive.

    Priority:
      1. real VIN (17 alphanumeric chars, not "NON OWNED" / "N/A" / "")
      2. f"{year}|{make_upper}|{model_upper}" if all three present
      3. None — cannot match; the unit will be added (no skip).
    All inputs whitespace-stripped, case-normalized.
    """
```

### Pre-check loop in `_add_all_vehicles`

```python
existing = await summary.list_existing_units()
existing_by_id = {u.identifier: u for u in existing if u.identifier}

to_add = []
for v in fields.vehicles:
    pdf_id = normalize_identifier(v.vin, v.year, v.make, v.model)
    if pdf_id and pdf_id in existing_by_id:
        diffs = _diff_unit_vs_pdf(existing_by_id[pdf_id], v)
        msg = f"Pre-existing unit {pdf_id} kept as-is"
        if diffs:
            msg += f" (diffs vs PDF: {diffs})"
        print(f"    [Progressive] SKIP {msg}")
        result.warnings.append(msg)
        continue
    to_add.append(v)

# Split to_add into powered vs trailers and process as today.
```

`_diff_unit_vs_pdf` compares year, make, model, gvw, value, has_loan, radius_miles — returns a dict of `{field: (pdf_value, progressive_value)}` for keys that differ. Empty dict when identical.

### Phase 0 unit tests

- `test_normalize_identifier_real_vin` — real VIN dominates Y/M/M
- `test_normalize_identifier_non_owned` — "NON OWNED" → falls back to Y/M/M
- `test_normalize_identifier_only_ymm` — no VIN, all 3 fields → composite
- `test_normalize_identifier_insufficient` — no VIN, missing year → None
- `test_normalize_identifier_whitespace_case` — leading/trailing whitespace, mixed case normalize
- `test_diff_unit_vs_pdf_no_diffs` — identical units → empty dict
- `test_diff_unit_vs_pdf_single_field` — single field diff captured
- `test_diff_unit_vs_pdf_multiple` — multiple diffs captured
- `test_diff_unit_vs_pdf_missing_on_one_side` — None vs value treated as diff

### Phase 0 live validation

1. RYD LLC fresh quote against a clean USDOT → all PDF vehicles enter as today; logs show "no pre-existing units".
2. RYD LLC re-run against the same USDOT → pre-check SKIPs the powered vehicle with WARN. Premium re-computed against existing units.
3. M&D CUSTOM FREIGHT regression → still cotiza $53,064 (no trailers, no pre-existing).

## Phase 1 — AddTrailerPage

### Discovery

Before writing the page object, dump Progressive's trailer form live. Temporary diagnostic added to `_add_all_vehicles` (removed in the same PR after capture):

- URL token after clicking `summary.add_trailer()`
- Full page heading text
- DOM dump filtered to inputs (placeholder + accessible name)
- DOM dump filtered to radios (group label + values)
- DOM dump filtered to comboboxes (label + visible value)
- Screenshot of the loaded form

### `AddTrailerPage` API

```python
class AddTrailerPage(BasePage):
    REQUIRED_FIELDS = ("year", "make", "model", "vin", "type")
    CONDITIONAL_FIELDS = ("vehicle_value", "vehicle_has_no_equipment")
    OPTIONAL_FIELDS = ("garaging_zip", "gvw")

    async def fill_from_mapped(self, trailer: MappedVehicle) -> None:
        # mirrors AddVehiclePage.fill_from_mapped structure:
        # 1. VIN radio default + VIN textbox + Lookup VIN
        #    (fallback to Y/M/M cascade — fragile, as today)
        # 2. Trailer Type combobox (Dry Van / Reefer / Flatbed / Dump / Tank …)
        # 3. Garaging ZIP overwrite if differs
        # 4. GVW combobox (if present — trailers may not ask)
        # 5. Loan/Lease radio:
        #      has_loan != "No" → Comp/Coll auto-required; skip the question
        #      has_loan == "No" → if trailer.value → Comp/Coll Yes + fill Vehicle Value
        #                       → else Comp/Coll No (liability-only)
        # 6. safe_click_continue(expect_url_changes_from="AddTrailer")
```

Selector mappings get filled after the live diagnostic. Until then, this section of the spec describes the expected shape, not the executable code.

### Routing

When `_add_all_vehicles` reaches the trailer loop, the bot is guaranteed to be on VehicleSummary (powered loop completed with AddVehicle Continue, which lands back here). Trailer entry point:

```python
await summary.add_trailer()      # existing in vehicles_page.py:127
await wizard_page.wait_for_load_state("networkidle")
add_trailer_form = AddTrailerPage(wizard_page)
await add_trailer_form.fill_from_mapped(trailer)
```

The MostCommonVehicles "Add a trailer instead" link is not used by `_add_all_vehicles` because we always have at least one powered vehicle by the time trailers are processed — but kept in the page object for fresh-quote-trailer-only edge cases.

### Phase 1 live validation

1. RYD LLC fresh quote → powered ($44,621 baseline preserved or improved with trailer) + 1 trailer real (DRY VAN TRAILER). Capture new baseline.
2. RYD LLC re-run → both units skip via Phase 0 pre-check.
3. Prueba1 NOBLE LOGISTICS → NON OWNED trailer filtered at field_mapper, $25k non-owned coverage applied on RATES, premium re-baselined.

## NON OWNED Routing (cross-phase)

Implemented in `field_mapper.map_profile_to_fields` as a post-map filter. A single helper `_is_non_owned()` operates on the input struct (VehicleProfile in pre-map paths, MappedVehicle in post-map paths) by reading the same three fields — `vin`, `make`, `model` — which exist on both. No duplication:

```python
NON_OWNED_MARKERS = {"NON OWNED", "NONOWNED", "NON-OWNED", "N/A", ""}

def _is_non_owned(vin: Optional[str], make: Optional[str], model: Optional[str]) -> bool:
    vin_clean = (vin or "").strip().upper()
    if vin_clean in NON_OWNED_MARKERS:
        return True
    for s in (make, model):
        if s and "NON OWNED" in s.upper():
            return True
    return False

# In map_profile_to_fields, after the vehicle loop:
non_owned = [v for v in mapped_vehicles if _is_non_owned(v.vin, v.make, v.model)]
mapped_vehicles = [v for v in mapped_vehicles if not _is_non_owned(v.vin, v.make, v.model)]

if non_owned and not profile.coverages_detail.non_owned_trailer_phys_damage_limit:
    profile.coverages_detail.non_owned_trailer_phys_damage_limit = "$25,000"
```

The existing `CoveragesRatesPage._configure_non_owned_trailer_phys_damage` at `coverages_rates_page.py:1030` already handles the RATES-side activation when the limit is truthy. No rates-page changes needed.

Edge cases:

- PDF has NON OWNED + operator pre-set `non_owned_trailer_phys_damage_limit = "$50,000"` → respect operator, do not overwrite.
- PDF has NON OWNED + a real-VIN trailer → both paths run independently (real trailer goes through Add Trailer, non-owned bumps the coverage).
- PDF has multiple NON OWNED trailers → single coverage bump (coverage is per-policy, not per-unit).

## Test Plan Summary

**Unit tests (+10-12):**

- `test_normalize_identifier.py` — 5 cases
- `test_diff_unit_vs_pdf.py` — 4 cases
- `test_field_mapper_non_owned.py` — 3 cases
- `test_field_mapper_is_trailer.py` — 2 cases

Target: 40 → ~52 passing.

**Live validation (4 scenarios in order):**

1. M&D CUSTOM FREIGHT — regression, $53,064 preserved.
2. RYD LLC fresh — powered + real trailer added end-to-end; new baseline captured.
3. RYD LLC re-run — pre-check SKIPs both units with clean WARN.
4. Prueba1 NOBLE LOGISTICS — NON OWNED filtered, $25k non-owned coverage applied; new baseline captured.

**Success criteria:**

- ✅ All 4 live scenarios reach RATES with `success=True`
- ✅ All unit tests pass
- ✅ `tests/simulate_progressive.py` remains success
- ✅ No verbose regression in happy-path logs (diagnostic only on failure paths)

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| `list_existing_units()` returns empty before ExtJS hydration completes → bot attempts duplicate add | `wait_for_extjs_idle` + 3s poll for first row when header indicates a list is expected |
| Cannot distinguish trailer rows from vehicle rows in DOM | Fall back to identifier-only matching; routing decides flow based on `MappedVehicle.is_trailer` from extractor |
| Trailer form has fields not present in AddVehicle (e.g. axle count, body length) | Diagnostic dump captures unknown fields; spec amended before implementation |
| Trailer VIN lookup fails for uncommon makes | Inherit AddVehicle's Y/M/M fallback path (also fragile, but the failure mode is the same) |
| Operator-set non_owned coverage limit gets overwritten by the default bump | Guard with `not profile.coverages_detail.non_owned_trailer_phys_damage_limit` before defaulting |

## Open Questions

- None blocking. Phase 1 form details get resolved by the live diagnostic.

## References

- Previous spec: `docs/superpowers/specs/2026-06-02-progressive-basepage-hardening-design.md`
- PR-A APD-conditional pattern: commit `1835fcd` (Vehicle Value triggered by Blue Quote `value` column)
- Existing trailer entry points: `VehicleSummaryPage.add_trailer()` (`vehicles_page.py:127`), `MostCommonVehiclesPage.click_add_trailer_instead()` (`vehicles_page.py:204`)
- Existing non-owned RATES handler: `CoveragesRatesPage._configure_non_owned_trailer_phys_damage` (`coverages_rates_page.py:1030`)
- Memory snapshot: `progressive_resume_2026_06_03.md` (PR-B pending #1)
