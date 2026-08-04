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
from modules.progressive.learned_mappings import learned_lookup, learned_remember

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


def ai_pick_from_options(
    commodity: Optional[str],
    options: List[str],
    *,
    classifier=None,
    decision_type: Optional[str] = None,
    store=None,
) -> Optional[str]:
    """Map a free-text value to exactly ONE of `options` via the project's AI
    classifier. Generic — used for the MTC cargo category/commodity pickers, the
    vehicle/trailer tile fallback, and the trailer-make fallback. Returns the
    chosen option (must be in `options`) or None.

    When `decision_type` is given, the result is cached in the learned-mappings
    Excel (so a repeated input is served without an AI call) AND a cache hit is
    reused only if it's still a current option. (Business Type caches separately
    in resolve_commodity_to_business_type, so it passes no decision_type here.)
    """
    text = (commodity or "").strip()
    opts = [o for o in (options or []) if o and o.strip()]
    if not text or not opts:
        return None
    if decision_type:
        cached = learned_lookup(decision_type, text, store=store)
        if cached and cached in opts:
            return cached
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
    if result and result in opts:
        if decision_type:
            learned_remember(decision_type, text, result, store=store)
        return result
    return None


def classify_business_type_ai(
    commodity: Optional[str],
    *,
    classifier=None,
    options: Optional[List[str]] = None,
) -> Optional[str]:
    """Map `commodity` to one Progressive Business Type via the AI classifier,
    restricted to the trucking option subset (or `options` if given)."""
    opts = list(options) if options is not None else list(load_trucking_business_types())
    return ai_pick_from_options(commodity, opts, classifier=classifier)


def _enrich_commodity(commodity: Optional[str], unit_hints=None) -> str:
    """Append the quote's vehicle/trailer types to the commodity text so the AI
    can weigh how the goods are actually hauled. E.g. 'FRESH PRODUCE 100%' with
    a Refrigerated Trailer should classify as refrigerated hauling, not generic
    farm-produce hauling (whose tiles then lack a refrigerated trailer)."""
    text = (commodity or "").strip()
    if not unit_hints:
        return text
    hints = ", ".join(dict.fromkeys(
        h.strip() for h in unit_hints if h and h.strip()
    ))
    return f"{text} (transported with: {hints})" if hints else text


def resolve_commodity_to_business_type(
    commodity: Optional[str], *, unit_hints=None, classifier=None, store=None
) -> Tuple[Optional[str], str]:
    """Return (Progressive Business-Type label | None, note).

    Order: keyword table -> learned cache -> AI (remember the result) -> HALT.
    note is one of: 'mapping' (specific table hit), 'generic' (general-freight /
    Trucker sentinel), 'learned' (cache hit — no AI call), 'ai' (AI classifier),
    'unmapped' (caller HALTs). `unit_hints` enrich the AI input. `classifier`
    and `store` (cache file) are injectable for tests.
    """
    opt, is_generic = map_commodity(commodity)
    if opt is not None:
        return opt, ("generic" if is_generic else "mapping")

    cached = learned_lookup("business_type", commodity or "", store=store)
    if cached:
        return cached, "learned"

    enriched = _enrich_commodity(commodity, unit_hints)
    ai_opt = classify_business_type_ai(enriched, classifier=classifier)
    if ai_opt:
        learned_remember("business_type", commodity or "", ai_opt, store=store)
        return ai_opt, "ai"

    # Diana 2026-08-04 (R-013): si tabla + AI no mapean, el TIPO DE TRAILER
    # decide — cualquier señal de unidad rutea al path genérico 'Trucker' y
    # el subtipo Type-of-Trucker refina (dry van/flatbed → General Freight,
    # reefer → Refrigerated, dump → S&G/Scrap según commodity, etc.).
    # Caso JUAREZ: 'PACKED CHARCOAL' en dry van → General Freight (antes: HALT).
    from modules.progressive.mappings import subtype_from_unit_hints
    hint_label, hint_src = subtype_from_unit_hints(unit_hints, commodity=commodity)
    if hint_label:
        return "Trucker", f"trailer-fallback:{hint_src}"

    return None, "unmapped"


def unit_type_hints(vehicles) -> list:
    """Distinct, order-preserving vehicle/trailer type strings from a list of
    objects exposing `.trailer_type` (MappedVehicle). Used to enrich commodity
    classification with how the goods are hauled."""
    hints = []
    for v in (vehicles or []):
        t = (getattr(v, "trailer_type", None) or "").strip()
        if t and t not in hints:
            hints.append(t)
    return hints
