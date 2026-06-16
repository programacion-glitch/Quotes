"""
QuoteQueueStore — almacén durable de jobs de cotización sobre SQLite (WAL).

Único punto de coordinación entre el productor (orquestador / inbox) y los
workers (uno por MGA). Thread-safe vía un threading.Lock: el bot corre en un
solo proceso, así que el lock serializa claim/update sin transacciones
cross-process. Si algún día se va multi-proceso, cambiar a BEGIN IMMEDIATE.
"""

import sqlite3
import threading
import time
from pathlib import Path
from typing import List, Optional

from modules.quote_queue.models import QuoteJob, JobStatus, TERMINAL_STATUSES


class QuoteQueueStore:
    def __init__(self, db_path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._create_tables()

    def _create_tables(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS quote_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    submission_id TEXT NOT NULL,
                    mga TEXT NOT NULL,
                    profile_json TEXT NOT NULL,
                    effective_date TEXT,
                    usdot TEXT,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    lease_until REAL,
                    retry_after REAL,
                    premium TEXT,
                    quote_number TEXT,
                    pdf_path TEXT,
                    screenshot_path TEXT,
                    error TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS submissions (
                    submission_id TEXT PRIMARY KEY,
                    context_json TEXT,
                    email_sent INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_mga_status ON quote_jobs(mga, status);
                CREATE INDEX IF NOT EXISTS idx_jobs_submission ON quote_jobs(submission_id);
                CREATE INDEX IF NOT EXISTS idx_jobs_usdot ON quote_jobs(mga, usdot);
                """
            )
            self._conn.commit()

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> QuoteJob:
        return QuoteJob(
            id=row["id"],
            submission_id=row["submission_id"],
            mga=row["mga"],
            profile_json=row["profile_json"],
            effective_date=row["effective_date"],
            usdot=row["usdot"],
            status=row["status"],
            attempts=row["attempts"],
            lease_until=row["lease_until"],
            retry_after=row["retry_after"],
            premium=row["premium"],
            quote_number=row["quote_number"],
            pdf_path=row["pdf_path"],
            screenshot_path=row["screenshot_path"],
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _get_job_locked(self, job_id: int) -> Optional[QuoteJob]:
        row = self._conn.execute(
            "SELECT * FROM quote_jobs WHERE id=?", (job_id,)
        ).fetchone()
        return self._row_to_job(row) if row else None

    def enqueue(self, submission_id, mga, profile_json, effective_date, usdot) -> int:
        now = time.time()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO quote_jobs (submission_id, mga, profile_json, "
                "effective_date, usdot, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (submission_id, mga, profile_json, effective_date, usdot,
                 JobStatus.PENDING.value, now, now),
            )
            self._conn.commit()
            return cur.lastrowid

    def get_jobs(self, submission_id) -> List[QuoteJob]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM quote_jobs WHERE submission_id=? ORDER BY id",
                (submission_id,),
            ).fetchall()
            return [self._row_to_job(r) for r in rows]

    def claim_next(self, mga, lease_seconds: float = 900) -> Optional[QuoteJob]:
        """Reclama atómicamente el job más viejo elegible para `mga`.

        Elegible = pending, o deferred cuyo retry_after ya venció. Marca
        claimed, fija lease_until e incrementa attempts. None si no hay.
        """
        now = time.time()
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM quote_jobs WHERE mga=? AND ("
                "  status=? OR (status=? AND (retry_after IS NULL OR retry_after<=?))"
                ") ORDER BY created_at ASC, id ASC LIMIT 1",
                (mga, JobStatus.PENDING.value, JobStatus.DEFERRED.value, now),
            ).fetchone()
            if row is None:
                return None
            self._conn.execute(
                "UPDATE quote_jobs SET status=?, lease_until=?, "
                "attempts=attempts+1, updated_at=? WHERE id=?",
                (JobStatus.CLAIMED.value, now + lease_seconds, now, row["id"]),
            )
            self._conn.commit()
            return self._get_job_locked(row["id"])

    def mark_running(self, job_id, lease_seconds: float = 900) -> None:
        """Marca running y extiende el lease mientras corre el quote."""
        now = time.time()
        with self._lock:
            self._conn.execute(
                "UPDATE quote_jobs SET status=?, lease_until=?, updated_at=? WHERE id=?",
                (JobStatus.RUNNING.value, now + lease_seconds, now, job_id),
            )
            self._conn.commit()

    def mark_terminal(self, job_id, status, premium=None, quote_number=None,
                      pdf_path=None, screenshot_path=None, error=None) -> None:
        """Marca un estado terminal (quoted/failed/halted) y guarda resultado."""
        status = JobStatus(status)
        if status not in TERMINAL_STATUSES:
            raise ValueError(f"{status} no es un estado terminal")
        now = time.time()
        with self._lock:
            self._conn.execute(
                "UPDATE quote_jobs SET status=?, premium=?, quote_number=?, "
                "pdf_path=?, screenshot_path=?, error=?, lease_until=NULL, "
                "updated_at=? WHERE id=?",
                (status.value, premium, quote_number, pdf_path,
                 screenshot_path, error, now, job_id),
            )
            self._conn.commit()

    def mark_deferred(self, job_id, retry_after: float) -> None:
        """Marca deferred (re-encolable) con un retry_after (epoch)."""
        now = time.time()
        with self._lock:
            self._conn.execute(
                "UPDATE quote_jobs SET status=?, retry_after=?, "
                "lease_until=NULL, updated_at=? WHERE id=?",
                (JobStatus.DEFERRED.value, retry_after, now, job_id),
            )
            self._conn.commit()

    def reclaim_stale(self, now: Optional[float] = None) -> int:
        """Devuelve a pending los jobs claimed/running con lease vencido.

        Se llama al arrancar el runner para recuperar de un crash a mitad de
        quote. Devuelve cuántos jobs reclamó.
        """
        now = now if now is not None else time.time()
        with self._lock:
            cur = self._conn.execute(
                "UPDATE quote_jobs SET status=?, lease_until=NULL, updated_at=? "
                "WHERE status IN (?, ?) AND lease_until IS NOT NULL AND lease_until < ?",
                (JobStatus.PENDING.value, now, JobStatus.CLAIMED.value,
                 JobStatus.RUNNING.value, now),
            )
            self._conn.commit()
            return cur.rowcount

    def close(self) -> None:
        with self._lock:
            self._conn.close()
