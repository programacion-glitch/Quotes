"""Resolve a free-text Blue-Quote commodity to a Progressive Business Type.

Strategy (table -> AI -> None), so the free-text commodity scales to ANY client
without hand-maintaining a mapping for every new commodity:

  1. The curated keyword table (mappings.map_commodity) — fast, deterministic,
     free. Preserves the exact behaviour of the already-validated quotes.
  2. If the table doesn't match, the project's existing AI classifier
     (ai_commodity_classifier.AICommodityClassifier, the same one the upstream
     MGA-eligibility pipeline uses) maps the commodity against Progressive's
     REAL Business-Type taxonomy — restricted to the trucking-relevant subset
     captured live from the 'Business type list' combobox.
  3. If neither matches, return None and the caller HALTs (fail-loud) — never a
     silent wrong guess.

The AI step makes a network call via the configured OpenAI proxy; if that proxy
is unavailable (e.g. offline/headless without config) it degrades to None, so
behaviour falls back to exactly today's fail-loud HALT.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Tuple

from modules.progressive.mappings import map_commodity

_SUBSET_PATH = Path(__file__).parent / "catalogs" / "business_types_trucking.json"


@lru_cache(maxsize=1)
def load_trucking_business_types() -> tuple:
    """The trucking-relevant subset of Progressive's live Business-Type list
    (haulers / truckers / distributors / delivery / transport). Cached source of
    truth for the AI prompt; refresh by re-enumerating the live combobox."""
    try:
        data = json.loads(_SUBSET_PATH.read_text(encoding="utf-8"))
        return tuple(o for o in data if isinstance(o, str) and o.strip())
    except Exception:
        return tuple()


def classify_business_type_ai(
    commodity: Optional[str],
    *,
    classifier=None,
    options: Optional[List[str]] = None,
) -> Optional[str]:
    """Map `commodity` to one Progressive Business Type via the AI classifier,
    restricted to the trucking option subset. Returns the exact Progressive
    label or None. Defensive: any failure (no config, network, off-list answer)
    returns None so the caller fail-loud HALTs."""
    text = (commodity or "").strip()
    if not text:
        return None
    opts = list(options) if options is not None else list(load_trucking_business_types())
    if not opts:
        return None
    if classifier is None:
        # Opt-out switch for offline/test runs (the real classifier hits a
        # network proxy). Default on. An explicitly injected classifier always
        # runs — this guard only governs constructing the real one.
        if os.getenv("PROGRESSIVE_AI_COMMODITY", "1") == "0":
            return None
        try:
            from modules.ai_commodity_classifier import AICommodityClassifier
            classifier = AICommodityClassifier()
        except Exception as e:  # missing config / import / network client init
            print(f"    [Progressive] AI commodity classifier unavailable: {e}")
            return None
    try:
        result = classifier.classify_commodity(text, opts)
    except Exception as e:
        print(f"    [Progressive] AI commodity classify failed: {e}")
        return None
    return result or None


def resolve_commodity_to_business_type(
    commodity: Optional[str], *, classifier=None
) -> Tuple[Optional[str], str]:
    """Return (Progressive Business-Type label | None, note).

    note is one of: 'mapping' (specific table hit), 'generic' (general-freight /
    Trucker sentinel), 'ai' (AI classifier), 'unmapped' (caller HALTs).
    `classifier` is injectable for tests.
    """
    opt, is_generic = map_commodity(commodity)
    if opt is not None:
        return opt, ("generic" if is_generic else "mapping")

    ai_opt = classify_business_type_ai(commodity, classifier=classifier)
    if ai_opt:
        return ai_opt, "ai"

    return None, "unmapped"
