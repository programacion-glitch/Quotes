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

    def close(self) -> None:
        with self._lock:
            self._conn.close()
