"""Commodity -> GEICO Business Class resolver (the 1,596-option Select2).

Resolution order (the Progressive self-feeding pattern):

    exact catalog match -> learned cache -> AI over prefiltered candidates
    (remembered on success) -> None (caller fails loud).

The learned cache is the shared data/learned_mappings.xlsx
(modules/progressive/learned_mappings.py — generic by decision_type), so the
H2O team can review/correct AI decisions in one place.

The AI prompt cannot carry all 1,596 options; `_candidate_options` prefilters
to entries sharing a substantive token with the commodity, plus the generic
catch-alls (General Freight / Trucking / Hauling / Delivery / Distributor) so
the model can always fall back to one.
"""

from __future__ import annotations

import os
import re
from typing import List, Optional, Tuple

from modules.progressive.learned_mappings import learned_lookup, learned_remember

_DECISION_TYPE = "geico_business_class"

# Substrings that mark generic/catch-all catalog entries — always offered to
# the AI so a weird commodity can land on a sane default.
_GENERIC_MARKERS = ("TRUCK", "FREIGHT", "HAULING", "DELIVERY", "DISTRIBUT",
                    "GENERAL")

_STOPWORDS = {"WITH", "FROM", "THAT", "THIS", "MISC", "OTHER", "GOODS"}


def _candidate_options(
    commodity: str, catalog: List[str], *, cap: int = 200
) -> List[str]:
    """Catalog entries worth offering to the AI for this commodity: token
    overlap hits first, then the generic catch-alls. Capped to keep the
    prompt small."""
    tokens = {
        t for t in re.split(r"[^A-Za-z]+", (commodity or "").upper())
        if len(t) >= 4 and t not in _STOPWORDS
    }
    hits = [
        c for c in catalog
        if any(t in c.upper() for t in tokens)
    ]
    generics = [
        c for c in catalog
        if any(g in c.upper() for g in _GENERIC_MARKERS)
    ]
    merged = list(dict.fromkeys(hits + generics))
    return merged[:cap] if merged else catalog[:cap]


def _ai_enabled() -> bool:
    return os.getenv("GEICO_AI_BUSINESS_CLASS", "1") != "0"


def _default_classifier():
    """Build the shared AI classifier lazily (network client)."""
    from modules.ai_commodity_classifier import AICommodityClassifier
    return AICommodityClassifier()


def resolve_business_class(
    raw_value: str,
    catalog: List[str],
    *,
    classifier=None,
    store=None,
) -> Tuple[Optional[str], str]:
    """Resolve `raw_value` (mapped label or raw BlueQuote commodity) to an
    exact catalog label.

    Returns (label, source) with source in {'exact', 'learned', 'ai'};
    (None, '') when unresolvable — the caller HALTs the quote loudly.
    """
    if not raw_value or not catalog:
        return None, ""

    want = " ".join(raw_value.upper().split())

    # 1. Exact (case/whitespace-insensitive) catalog match.
    for label in catalog:
        if " ".join(label.upper().split()) == want:
            return label, "exact"

    # 2. Learned cache (reviewable/correctable Excel).
    remembered = learned_lookup(_DECISION_TYPE, raw_value, store=store)
    if remembered:
        for label in catalog:
            if label.strip().upper() == remembered.strip().upper():
                return label, "learned"

    # 3. AI over prefiltered candidates; remember the decision.
    if classifier is None and _ai_enabled():
        try:
            classifier = _default_classifier()
        except Exception as e:
            print(f"    [GEICO] WARN: AI classifier unavailable: {e}")
            classifier = None
    if classifier is not None:
        candidates = _candidate_options(raw_value, catalog)
        try:
            answer = classifier.classify_commodity(raw_value, candidates)
        except Exception as e:
            print(f"    [GEICO] WARN: AI business-class classify failed: {e}")
            answer = None
        if answer:
            for label in catalog:
                if label.strip().upper() == answer.strip().upper():
                    learned_remember(
                        _DECISION_TYPE, raw_value, label,
                        source="ai", store=store,
                    )
                    return label, "ai"

    return None, ""
