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
from modules.progressive.mappings import VEHICLE_TILE_MAP
from modules.progressive.business_type_classifier import (
    resolve_commodity_to_business_type,
    unit_type_hints,
)
from modules.progressive.vehicle_amounts import resolve_vehicle_value
from modules.progressive.amounts import parse_amount
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
    label, note = resolve_commodity_to_business_type(
        commodity, unit_hints=unit_type_hints(mapped.vehicles)
    )
    if label is not None:
        # 'generic' (table catch-all) and 'ai' (LLM classification) are both
        # assumptions worth surfacing; a specific 'mapping' hit is silent.
        if note in ("generic", "ai"):
            rep.assumptions.append(
                Resolution("Business type", label, "MATCHED", commodity, note)
            )
        return
    rep.blockers.append(Blocker(
        field="Business type",
        source_value=commodity,
        available_options=list(cat.options),
        suggestion="No table match and AI classifier could not map it — add a "
                   "mapping or fix the Blue Quote.",
    ))


def _check_vehicle_tiles(mapped: MappedFields, rep: PreflightReport) -> None:
    cat = load_catalog("vehicle_tiles")
    for i, v in enumerate(mapped.vehicles):
        if v.is_trailer:
            continue  # trailers use the Add Trailer flow, not the tile picker
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


def _check_gvw(mapped: MappedFields, rep: PreflightReport) -> None:
    # Offline, the catalog may be PARTIAL (only the heavy ranges captured from a
    # live run). The LIVE GVW combo is authoritative for bucketing, so the only
    # reliably-detectable problem here is an UNPARSEABLE value (garbage) — NOT a
    # parseable weight that simply falls outside the partial catalog (e.g. a
    # light 8000-lb pickup, which the live combo would bucket fine).
    cat = load_catalog("gvw")
    for i, v in enumerate(mapped.vehicles):
        if v.is_trailer:
            continue  # trailers use the Add Trailer flow (separate GVW field)
        if not (v.gvw or "").strip():
            continue  # absent GVW — fine, handled downstream by default bucket
        if parse_amount(v.gvw) is None:
            rep.blockers.append(Blocker(
                field="Gross vehicle weight",
                source_value=f"vehicle[{i}]: {v.gvw}",
                available_options=list(cat.options),
                suggestion="GVW present but not a parseable number — fix the Blue Quote.",
            ))


def _check_value(mapped: MappedFields, rep: PreflightReport) -> None:
    for i, v in enumerate(mapped.vehicles):
        if v.is_trailer:
            continue  # trailers use the Add Trailer flow (separate value field)
        try:
            resolve_vehicle_value(v.value)
        except UnmappableValueError as e:
            rep.blockers.append(Blocker(
                field="Vehicle value",
                source_value=f"vehicle[{i}]: {e.source_value}",
                available_options=list(e.available_options),
                suggestion="Vehicle value present but unusable (< $100 or garbage) — fix the Blue Quote.",
            ))


def run_preflight(mapped: MappedFields) -> PreflightReport:
    rep = PreflightReport()
    _check_commodity(mapped, rep)
    _check_vehicle_tiles(mapped, rep)
    _check_gvw(mapped, rep)
    _check_value(mapped, rep)
    return rep


def format_report(rep: PreflightReport, business: str) -> str:
    lines = [f"PREFLIGHT - {business}"]
    if rep.blockers:
        lines.append(f"BLOCKERS ({len(rep.blockers)}) - resolver antes de re-correr:")
        for b in rep.blockers:
            lines.append(f"  - {b.field}: {b.source_value!r} no matchea.")
            lines.append(f"      Opciones: {', '.join(b.available_options[:8])}...")
            lines.append(f"      Accion: {b.suggestion}")
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
