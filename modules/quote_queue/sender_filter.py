"""Decide si un correo entrante es una submission original de ventas procesable.

Regla (las tres deben cumplirse):
  1. El asunto EMPIEZA con "submission" (excluye "Re:", "Fwd:", "[ANALISIS]", ...).
  2. El remitente pertenece a un grupo de ventas.
  3. El grupo coincide con la variante del asunto:
       - "Submission New Venture ..."  -> new_venture_senders (VENTAS NUEVAS)
       - "Submission ..." (existente)  -> rt_senders (RT)

Los sets de remitentes se pasan YA normalizados en minúscula.
"""
from typing import Set


def is_processable_submission(
    sender_email: str,
    subject: str,
    rt_senders: Set[str],
    new_venture_senders: Set[str],
) -> bool:
    s = (subject or "").strip().lower()
    if not s.startswith("submission"):
        return False
    sender = (sender_email or "").strip().lower()
    if "new venture" in s:
        return sender in new_venture_senders
    return sender in rt_senders
