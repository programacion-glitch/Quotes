"""Decision Ledger — el bot como notario de sus propias decisiones.

Registro en memoria (thread-local) de cada decisión que el bot toma durante
una corrida de cotización: qué campo, qué eligió, entre qué opciones, y por
qué (regla de negocio con rule_id del Excel config/mga_decision_rules.xlsx,
default técnico, matching, AI). El worker lo serializa al terminar el job y
el correo de análisis lo muestra a negocios ("Decisiones tomadas").

Thread-local porque el runner corre UN worker-thread por MGA en el mismo
proceso: cada thread tiene su ledger y no se contaminan entre MGAs.

Best-effort SIEMPRE: registrar jamás puede romper una cotización.
"""

from __future__ import annotations

import threading
from typing import List, Optional

_state = threading.local()


def start_run(mga: str) -> None:
    """Arranca (o resetea) el ledger de la corrida del thread actual."""
    _state.mga = mga
    _state.entries = []


def record(field: str, chosen, *, page: Optional[str] = None,
           options=None, source: str = "HARDCODED",
           rule_id: Optional[str] = None, note: str = "") -> None:
    """Registra una decisión. No-op si no hubo start_run en este thread.

    NUNCA lanza: una falla de registro jamás rompe una cotización.
    """
    try:
        entries = getattr(_state, "entries", None)
        if entries is None:
            return
        entries.append({
            "mga": getattr(_state, "mga", "?"),
            "page": page,
            "field": str(field),
            "chosen": str(chosen),
            "options": [str(o) for o in options] if options else None,
            "source": str(source),
            "rule_id": rule_id,
            "note": str(note) if note else "",
        })
    except Exception:
        pass  # best-effort: el ledger nunca tumba el flujo


def entries() -> List[dict]:
    """Las decisiones registradas en el thread actual (lista vacía si no hay)."""
    return list(getattr(_state, "entries", []) or [])


def restore(saved: Optional[List[dict]]) -> None:
    """Re-siembra el ledger del thread actual con entradas ya capturadas
    (p.ej. las del field-mapper, tomadas ANTES del retry loop del wizard).

    Uso típico: `start_run(mga)` seguido de `restore(base)` al tope de CADA
    intento de un retry loop, para que las entradas del intento anterior
    (fallido) no sobrevivan a un intento posterior exitoso — sin este reset,
    `entries()` acumula filas duplicadas/contradictorias entre intentos.

    No-op si no hubo start_run en este thread. Best-effort SIEMPRE: igual
    que record(), jamás lanza — un fallo acá deja el ledger como estaba
    (posiblemente vacío) en vez de romper la cotización.
    """
    try:
        entries = getattr(_state, "entries", None)
        if entries is None:
            return
        entries.extend(dict(e) for e in (saved or []))
    except Exception:
        pass  # best-effort: el ledger nunca tumba el flujo
