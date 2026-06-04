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
