"""
Modelos de la cola de cotización RPA.

Dependency-free (solo stdlib) para que cualquier capa los importe barato,
mismo criterio que modules/geico/quote_result_types.py.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class JobStatus(str, Enum):
    """Estados de un job en la cola.

    pending → claimed → running → (quoted | failed | halted)
    deferred = transitorio re-encolable con backoff (producto no disponible,
    cooldown de OTP).
    """
    PENDING = "pending"
    CLAIMED = "claimed"
    RUNNING = "running"
    QUOTED = "quoted"
    FAILED = "failed"
    HALTED = "halted"
    DEFERRED = "deferred"


# Estados finales: el job no se vuelve a tocar.
TERMINAL_STATUSES = {JobStatus.QUOTED, JobStatus.FAILED, JobStatus.HALTED}


@dataclass
class QuoteJob:
    """Una fila de quote_jobs: una cotización (submission × MGA)."""
    id: int
    submission_id: str
    mga: str
    profile_json: str
    effective_date: Optional[str]
    usdot: str
    status: str
    attempts: int = 0
    lease_until: Optional[float] = None
    retry_after: Optional[float] = None
    premium: Optional[str] = None
    quote_number: Optional[str] = None
    pdf_path: Optional[str] = None
    screenshot_path: Optional[str] = None
    error: Optional[str] = None
    created_at: float = 0.0
    updated_at: float = 0.0
