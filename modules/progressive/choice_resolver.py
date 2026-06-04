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
    # For confidence, ALL meaningful tokens in the source must be present in the
    # winning candidate — a "leftover" token that doesn't appear in the winner
    # signals the source refers to something else (e.g. "hauling stuff": "stuff"
    # is absent from "Coal Hauling" → not a confident match → HALT).
    all_toks = [t for t in re.findall(r"[a-z0-9]+", sv_n) if len(t) >= 3]
    for tok in all_toks:
        hits = [o for o in options if tok in o.lower()]
        if len(hits) == 1:
            candidate = hits[0]
            candidate_lower = candidate.lower()
            # Every token in the source must appear in the candidate.
            all_present = all(t in candidate_lower for t in all_toks)
            if all_present:
                return Resolution(field, candidate, "MATCHED", sv, f"token:{tok}")

    # nothing confident -> HALT (never a silent catch-all)
    _halt()
