"""Limites de Auto Liability: como se llaman y quien los ofrece (R-097).

Cuando el agente pide mas de un limite de AL, el bot cotiza cada uno por
separado (un job por MGA y limite). Este modulo es el vocabulario compartido
de esa operacion, y responde dos preguntas:

* **Como se llama** — `al_label` da la etiqueta corta que desambigua los
  archivos ('AL 1M', 'AL 750K'). Sin ella, dos indicaciones del mismo carrier
  el mismo dia colisionan por nombre y Drive descarta la segunda.
* **Quien lo ofrece** — `mga_supports` evita encolar un limite que el MGA no
  tiene. GEICO no ofrece $750K: su mapper cae al default de $1M, asi que el
  job cotizaria un millon y el PDF saldria etiquetado '750K'.

Dependency-free (solo stdlib): lo importan el orquestador, la cola y los
nombradores de PDF, ninguno de los cuales debe arrastrar Playwright.

Los sets de abajo dicen QUE se puede cotizar; traducir cada limite al texto
que muestra la UI sigue siendo tarea de cada MGA
(`CoveragesRatesPage._BI_LIMIT_PROGRESSIVE_LABEL`, `_bi_limits_to_geico`).
tests/test_al_limits.py verifica que no se separen.
"""

from __future__ import annotations

import re
from typing import FrozenSet, Optional

# Forma canonica de un limite: '$750K CSL'. La Blue Quote y el cuerpo del
# correo escriben lo mismo de varias maneras ('$750,000 CSL', '750K').
_AMOUNT_RE = re.compile(r"(\d[\d,\.]*)\s*([MK])?", re.IGNORECASE)


def _amount_label(limit: str) -> Optional[str]:
    """'750,000' → '750K'; '1000000' → '1M'; '1M' → '1M'. None si no hay cifra."""
    m = _AMOUNT_RE.search(limit.replace(" ", ""))
    if not m:
        return None
    raw, suffix = m.group(1), (m.group(2) or "").upper()
    if suffix:
        return f"{raw.rstrip('.')}{suffix}"
    try:
        value = int(raw.replace(",", "").replace(".", ""))
    except ValueError:
        return None
    if value >= 1_000_000 and value % 1_000_000 == 0:
        return f"{value // 1_000_000}M"
    if value >= 1_000 and value % 1_000 == 0:
        return f"{value // 1_000}K"
    return str(value)


def al_label(limit: Optional[str]) -> str:
    """Etiqueta corta para nombres de archivo: '$750,000 CSL' → 'AL 750K'.

    Nunca levanta y nunca devuelve caracteres invalidos en un nombre de
    archivo: un limite raro produce una etiqueta fea, no una excepcion que
    tumbe la subida a Drive.
    """
    if not limit:
        return ""
    label = _amount_label(str(limit))
    if not label:
        return ""
    return f"AL {re.sub(r'[^A-Za-z0-9.]', '', label)}"


def canonical(limit: Optional[str]) -> Optional[str]:
    """Forma canonica comparable: '$750,000 CSL' → '$750K CSL'."""
    if not limit:
        return None
    label = _amount_label(str(limit))
    return f"${label} CSL" if label else None


# Que limite de AL cotiza cada MGA con RPA. Solo las MGAs que el bot cotiza
# solo: las que van por correo las arma una persona y no nos toca filtrarlas.
_SUPPORTED = {
    # Fuente: CoveragesRatesPage._BI_LIMIT_PROGRESSIVE_LABEL
    "PROGRESSIVE": frozenset({"$500K CSL", "$750K CSL", "$1M CSL"}),
    # Fuente: _bi_limits_to_geico. NO incluye $750K — GEICO no lo ofrece.
    "GEICO": frozenset({"$100K CSL", "$300K CSL", "$500K CSL", "$1M CSL"}),
}


def supported_by(mga: str) -> FrozenSet[str]:
    """Limites que `mga` cotiza. Vacio si el MGA no se cotiza con RPA."""
    return _SUPPORTED.get((mga or "").strip().upper(), frozenset())


def mga_supports(mga: str, limit: Optional[str]) -> bool:
    """¿Puede `mga` cotizar `limit`?

    Fail-open a proposito en los dos casos en que no hay nada que decidir:
    sin limite pedido, y en MGAs que no cotiza el bot.
    """
    if not limit:
        return True
    known = supported_by(mga)
    if not known:
        return True
    return canonical(limit) in known
