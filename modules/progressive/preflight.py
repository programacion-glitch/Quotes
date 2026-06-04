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
        if is_generic:
            rep.assumptions.append(
                Resolution("Business type", opt, "MATCHED", commodity, "generic")
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
