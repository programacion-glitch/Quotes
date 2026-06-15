# Cola de Cotización RPA — Parte 1: Core de la cola durable (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir el almacén durable de jobs en SQLite (store + modelos + serialización de `QuoteProfile`) que desacopla la recepción de correos del quoting RPA.

**Architecture:** Un paquete nuevo `modules/quote_queue/` con `models.py` (dataclass `QuoteJob` + enum `JobStatus`) y `store.py` (`QuoteQueueStore` sobre SQLite/WAL, único punto de coordinación). Se agrega `QuoteProfile.from_dict` para round-trip JSON. El store es thread-safe (un `threading.Lock` serializa operaciones; el bot corre en un solo proceso con un worker-thread por MGA). Todo es unit-testeable sin browser ni red.

**Tech Stack:** Python 3.12, stdlib `sqlite3`, `threading`, `json`, `time`, `dataclasses`, `enum`; `pytest` para tests.

**Spec de referencia:** `docs/superpowers/specs/2026-06-15-rpa-quote-queue-design.md`

**Intérprete Python:** `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe` (no está en PATH).

---

## File Structure

- **Create** `modules/quote_queue/__init__.py` — paquete vacío (marcador).
- **Create** `modules/quote_queue/models.py` — `JobStatus` (str-Enum), `TERMINAL_STATUSES`, `QuoteJob` dataclass.
- **Modify** `modules/quote_profile.py` — agregar `QuoteProfile.from_dict` (reconstruye dataclasses anidadas desde el dict de `to_dict()`).
- **Create** `modules/quote_queue/store.py` — `QuoteQueueStore`.
- **Create** `tests/quote_queue/__init__.py` — paquete de tests.
- **Create** `tests/quote_queue/test_profile_serialization.py`
- **Create** `tests/quote_queue/test_models.py`
- **Create** `tests/quote_queue/test_store.py`

Responsabilidad por archivo: `models.py` solo define tipos (dependency-free, igual que `modules/geico/quote_result_types.py`); `store.py` solo persiste/coordina; la serialización vive en `quote_profile.py` junto al modelo que serializa.

---

## Task 1: `QuoteProfile.from_dict` (round-trip JSON)

El store guarda el profile como JSON (`json.dumps(profile.to_dict())`) y el worker lo reconstruye. `to_dict()` ya existe (vía `asdict`); falta el inverso, que debe reconstruir las dataclasses anidadas (`ApplicantProfile`, `CoveragesProfile`, `UnitsProfile` con su lista de `VehicleProfile`, listas de `DriverProfile`, `LossRunProfile`, `IftasProfile`, `AppProfile`, `ExtractionConfidence` con su lista de `ConfidenceFlag`).

**Files:**
- Modify: `modules/quote_profile.py` (agregar método a `QuoteProfile`, al final de la clase, después de `to_dict`)
- Test: `tests/quote_queue/test_profile_serialization.py`

- [ ] **Step 1: Crear el paquete de tests**

Create `tests/quote_queue/__init__.py` con contenido vacío (un solo salto de línea).

- [ ] **Step 2: Escribir el test que falla**

Create `tests/quote_queue/test_profile_serialization.py`:

```python
import json

from modules.quote_profile import (
    QuoteProfile, ApplicantProfile, VehicleProfile, UnitsProfile,
    DriverProfile, ConfidenceFlag, ExtractionConfidence,
)


def _sample_profile() -> QuoteProfile:
    return QuoteProfile(
        applicant=ApplicantProfile(
            business_name="RYD LLC", owner_name="Jane Doe", usdot="1234567",
            state="TX", zip_code="77001", is_new_venture=False,
        ),
        commodity="Food & Beverage",
        coverages=["AL", "MTC"],
        units=UnitsProfile(
            count=2,
            trailer_types=["DRY VAN"],
            vehicles=[
                VehicleProfile(vin="1FUJGLDR4CLBP8834", year=2012, make="FREIGHTLINER"),
                VehicleProfile(is_trailer=True, trailer_type="DRY VAN"),
            ],
        ),
        drivers=[DriverProfile(name="Jane Doe", cdl_years=5, cdl_present=True)],
        documents_present=["BLUE QUOTE", "CDL"],
        extraction_confidence=ExtractionConfidence(
            overall="high",
            flags=[ConfidenceFlag(field="commodity", reason="inferred")],
        ),
    )


def test_roundtrip_through_json_preserves_data():
    original = _sample_profile()
    blob = json.dumps(original.to_dict())
    restored = QuoteProfile.from_dict(json.loads(blob))

    assert restored == original
    assert restored.applicant.business_name == "RYD LLC"
    assert restored.units.count == 2
    assert len(restored.units.vehicles) == 2
    assert restored.units.vehicles[0].vin == "1FUJGLDR4CLBP8834"
    assert restored.units.vehicles[1].is_trailer is True
    assert restored.drivers[0].cdl_years == 5
    assert restored.extraction_confidence.flags[0].field == "commodity"


def test_from_dict_on_empty_defaults():
    restored = QuoteProfile.from_dict({})
    assert restored.applicant.business_name == ""
    assert restored.units.count == 0
    assert restored.drivers == []
    assert restored.extraction_confidence.overall == "high"
```

- [ ] **Step 3: Correr el test y verificar que falla**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/quote_queue/test_profile_serialization.py -v`
Expected: FAIL con `AttributeError: type object 'QuoteProfile' has no attribute 'from_dict'`.

- [ ] **Step 4: Implementar `from_dict`**

En `modules/quote_profile.py`, dentro de la clase `QuoteProfile`, justo después de `to_dict` (línea ~192), agregar:

```python
    @classmethod
    def from_dict(cls, data: dict) -> "QuoteProfile":
        """Reconstruct a QuoteProfile from the dict produced by to_dict().

        Inverse of to_dict(): rebuilds every nested dataclass. Tolerates
        missing keys (falls back to dataclass defaults) so an empty dict
        yields a default profile.
        """
        data = dict(data or {})

        units_data = dict(data.get("units", {}) or {})
        units = UnitsProfile(
            count=units_data.get("count", 0),
            trailer_types=list(units_data.get("trailer_types", []) or []),
            vehicles=[VehicleProfile(**v) for v in units_data.get("vehicles", []) or []],
        )

        conf_data = dict(data.get("extraction_confidence", {}) or {})
        extraction_confidence = ExtractionConfidence(
            overall=conf_data.get("overall", "high"),
            flags=[ConfidenceFlag(**f) for f in conf_data.get("flags", []) or []],
        )

        return cls(
            applicant=ApplicantProfile(**(data.get("applicant", {}) or {})),
            commodity=data.get("commodity", ""),
            coverages=list(data.get("coverages", []) or []),
            coverages_detail=CoveragesProfile(**(data.get("coverages_detail", {}) or {})),
            units=units,
            drivers=[DriverProfile(**d) for d in data.get("drivers", []) or []],
            loss_run=LossRunProfile(**(data.get("loss_run", {}) or {})),
            iftas=IftasProfile(**(data.get("iftas", {}) or {})),
            app=AppProfile(**(data.get("app", {}) or {})),
            documents_present=list(data.get("documents_present", []) or []),
            extraction_confidence=extraction_confidence,
        )
```

- [ ] **Step 5: Correr el test y verificar que pasa**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/quote_queue/test_profile_serialization.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Pasar pyflakes (atrapa NameError de imports)**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pyflakes modules/quote_profile.py`
Expected: sin salida (exit 0).

- [ ] **Step 7: Commit**

```bash
git add modules/quote_profile.py tests/quote_queue/__init__.py tests/quote_queue/test_profile_serialization.py
git commit -m "feat(quote-queue): QuoteProfile.from_dict para round-trip JSON"
```

---

## Task 2: Modelos de la cola (`JobStatus` + `QuoteJob`)

**Files:**
- Create: `modules/quote_queue/__init__.py`
- Create: `modules/quote_queue/models.py`
- Test: `tests/quote_queue/test_models.py`

- [ ] **Step 1: Crear el marcador de paquete**

Create `modules/quote_queue/__init__.py` con contenido vacío (un solo salto de línea).

- [ ] **Step 2: Escribir el test que falla**

Create `tests/quote_queue/test_models.py`:

```python
from modules.quote_queue.models import JobStatus, TERMINAL_STATUSES, QuoteJob


def test_jobstatus_values():
    assert JobStatus.PENDING.value == "pending"
    assert JobStatus.QUOTED.value == "quoted"
    assert JobStatus.DEFERRED.value == "deferred"


def test_terminal_statuses_set():
    assert JobStatus.QUOTED in TERMINAL_STATUSES
    assert JobStatus.FAILED in TERMINAL_STATUSES
    assert JobStatus.HALTED in TERMINAL_STATUSES
    # transitorios NO son terminales
    assert JobStatus.PENDING not in TERMINAL_STATUSES
    assert JobStatus.DEFERRED not in TERMINAL_STATUSES
    assert JobStatus.RUNNING not in TERMINAL_STATUSES


def test_quotejob_defaults():
    job = QuoteJob(
        id=1, submission_id="sub-1", mga="PROGRESSIVE",
        profile_json="{}", effective_date="06/15/2026", usdot="1234567",
        status="pending",
    )
    assert job.attempts == 0
    assert job.premium is None
    assert job.pdf_path is None
```

- [ ] **Step 3: Correr el test y verificar que falla**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/quote_queue/test_models.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'modules.quote_queue.models'`.

- [ ] **Step 4: Implementar los modelos**

Create `modules/quote_queue/models.py`:

```python
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
```

- [ ] **Step 5: Correr el test y verificar que pasa**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/quote_queue/test_models.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add modules/quote_queue/__init__.py modules/quote_queue/models.py tests/quote_queue/test_models.py
git commit -m "feat(quote-queue): modelos JobStatus + QuoteJob"
```

---

## Task 3: Store — init, schema, `enqueue`, `get_jobs`, `_get_job`

`QuoteQueueStore` abre una conexión SQLite (WAL, `check_same_thread=False`) y serializa todas las operaciones con un `threading.Lock` (el bot corre en un solo proceso con un worker-thread por MGA, así que el lock garantiza atomicidad sin necesidad de transacciones cross-process).

**Files:**
- Create: `modules/quote_queue/store.py`
- Test: `tests/quote_queue/test_store.py`

- [ ] **Step 1: Escribir el test que falla**

Create `tests/quote_queue/test_store.py`:

```python
import pytest

from modules.quote_queue.models import JobStatus
from modules.quote_queue.store import QuoteQueueStore


@pytest.fixture()
def store(tmp_path):
    s = QuoteQueueStore(tmp_path / "queue.db")
    yield s
    s.close()


def test_enqueue_returns_id_and_persists_pending(store):
    job_id = store.enqueue(
        submission_id="sub-1", mga="PROGRESSIVE",
        profile_json='{"applicant": {}}', effective_date="06/15/2026",
        usdot="1234567",
    )
    assert isinstance(job_id, int) and job_id > 0

    jobs = store.get_jobs("sub-1")
    assert len(jobs) == 1
    assert jobs[0].mga == "PROGRESSIVE"
    assert jobs[0].status == JobStatus.PENDING.value
    assert jobs[0].usdot == "1234567"
    assert jobs[0].attempts == 0


def test_get_jobs_empty_for_unknown_submission(store):
    assert store.get_jobs("nope") == []
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/quote_queue/test_store.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'modules.quote_queue.store'`.

- [ ] **Step 3: Implementar el esqueleto del store + enqueue/get_jobs**

Create `modules/quote_queue/store.py`:

```python
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
```

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/quote_queue/test_store.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add modules/quote_queue/store.py tests/quote_queue/test_store.py
git commit -m "feat(quote-queue): store SQLite/WAL con enqueue + get_jobs"
```

---

## Task 4: Store — `claim_next` (atómico) + `mark_running` + `mark_terminal`

**Files:**
- Modify: `modules/quote_queue/store.py`
- Test: `tests/quote_queue/test_store.py` (agregar tests)

- [ ] **Step 1: Escribir los tests que fallan**

Agregar al final de `tests/quote_queue/test_store.py`:

```python
def test_claim_next_marks_claimed_and_increments_attempts(store):
    store.enqueue("sub-1", "PROGRESSIVE", "{}", "06/15/2026", "111")
    claimed = store.claim_next("PROGRESSIVE")
    assert claimed is not None
    assert claimed.status == JobStatus.CLAIMED.value
    assert claimed.attempts == 1
    assert claimed.lease_until is not None


def test_claim_next_isolates_by_mga(store):
    store.enqueue("sub-1", "GEICO", "{}", None, "111")
    assert store.claim_next("PROGRESSIVE") is None
    assert store.claim_next("GEICO") is not None


def test_claim_next_returns_none_when_empty(store):
    assert store.claim_next("PROGRESSIVE") is None


def test_claim_next_does_not_double_claim(store):
    store.enqueue("sub-1", "PROGRESSIVE", "{}", None, "111")
    first = store.claim_next("PROGRESSIVE")
    second = store.claim_next("PROGRESSIVE")
    assert first is not None
    assert second is None  # ya no hay pending


def test_mark_terminal_sets_results_and_clears_lease(store):
    job_id = store.enqueue("sub-1", "PROGRESSIVE", "{}", None, "111")
    store.claim_next("PROGRESSIVE")
    store.mark_terminal(
        job_id, JobStatus.QUOTED, premium="$44,621",
        quote_number="CA117054124", pdf_path="data/quote_pdfs/x.pdf",
    )
    job = store.get_jobs("sub-1")[0]
    assert job.status == JobStatus.QUOTED.value
    assert job.premium == "$44,621"
    assert job.quote_number == "CA117054124"
    assert job.pdf_path == "data/quote_pdfs/x.pdf"
    assert job.lease_until is None


def test_mark_terminal_rejects_non_terminal_status(store):
    job_id = store.enqueue("sub-1", "PROGRESSIVE", "{}", None, "111")
    with pytest.raises(ValueError):
        store.mark_terminal(job_id, JobStatus.RUNNING)
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/quote_queue/test_store.py -v`
Expected: FAIL con `AttributeError: 'QuoteQueueStore' object has no attribute 'claim_next'`.

- [ ] **Step 3: Implementar claim_next / mark_running / mark_terminal**

Agregar estos métodos a `QuoteQueueStore` (antes de `close`):

```python
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
```

- [ ] **Step 4: Correr y verificar que pasan**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/quote_queue/test_store.py -v`
Expected: PASS (todos).

- [ ] **Step 5: Commit**

```bash
git add modules/quote_queue/store.py tests/quote_queue/test_store.py
git commit -m "feat(quote-queue): claim_next atomico + mark_running + mark_terminal"
```

---

## Task 5: Store — `mark_deferred` + `reclaim_stale`

**Files:**
- Modify: `modules/quote_queue/store.py`
- Test: `tests/quote_queue/test_store.py` (agregar tests)

- [ ] **Step 1: Escribir los tests que fallan**

Agregar al final de `tests/quote_queue/test_store.py`:

```python
def test_deferred_not_claimable_until_retry_after(store):
    job_id = store.enqueue("sub-1", "GEICO", "{}", None, "111")
    store.claim_next("GEICO")
    future = __import__("time").time() + 9999
    store.mark_deferred(job_id, retry_after=future)
    # todavía no vence → no se reclama
    assert store.claim_next("GEICO") is None


def test_deferred_claimable_once_retry_after_passed(store):
    job_id = store.enqueue("sub-1", "GEICO", "{}", None, "111")
    store.claim_next("GEICO")
    past = __import__("time").time() - 1
    store.mark_deferred(job_id, retry_after=past)
    reclaimed = store.claim_next("GEICO")
    assert reclaimed is not None
    assert reclaimed.id == job_id


def test_reclaim_stale_returns_expired_leases_to_pending(store):
    job_id = store.enqueue("sub-1", "PROGRESSIVE", "{}", None, "111")
    store.claim_next("PROGRESSIVE")  # claimed, lease en el futuro
    # forzar un lease vencido: reclamar con now muy adelantado
    count = store.reclaim_stale(now=__import__("time").time() + 100000)
    assert count == 1
    job = store.get_jobs("sub-1")[0]
    assert job.status == JobStatus.PENDING.value
    assert job.lease_until is None


def test_reclaim_stale_ignores_live_leases(store):
    store.enqueue("sub-1", "PROGRESSIVE", "{}", None, "111")
    store.claim_next("PROGRESSIVE")
    assert store.reclaim_stale() == 0  # lease todavía vivo
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/quote_queue/test_store.py -v`
Expected: FAIL con `AttributeError: ... 'mark_deferred'`.

- [ ] **Step 3: Implementar mark_deferred / reclaim_stale**

Agregar a `QuoteQueueStore` (antes de `close`):

```python
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
```

- [ ] **Step 4: Correr y verificar que pasan**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/quote_queue/test_store.py -v`
Expected: PASS (todos).

- [ ] **Step 5: Commit**

```bash
git add modules/quote_queue/store.py tests/quote_queue/test_store.py
git commit -m "feat(quote-queue): mark_deferred + reclaim_stale (recuperacion de crash)"
```

---

## Task 6: Store — contexto de submission + `siblings_all_terminal` + `try_claim_submission_email`

**Files:**
- Modify: `modules/quote_queue/store.py`
- Test: `tests/quote_queue/test_store.py` (agregar tests)

- [ ] **Step 1: Escribir los tests que fallan**

Agregar al final de `tests/quote_queue/test_store.py`:

```python
def test_siblings_all_terminal_false_until_all_done(store):
    store.enqueue("sub-1", "PROGRESSIVE", "{}", None, "111")
    j2 = store.enqueue("sub-1", "GEICO", "{}", None, "111")
    assert store.siblings_all_terminal("sub-1") is False
    # uno terminal, el otro no
    store.claim_next("PROGRESSIVE")
    p = store.get_jobs("sub-1")[0]
    store.mark_terminal(p.id, JobStatus.QUOTED, premium="$1")
    assert store.siblings_all_terminal("sub-1") is False
    # ambos terminales
    store.claim_next("GEICO")
    store.mark_terminal(j2, JobStatus.FAILED, error="boom")
    assert store.siblings_all_terminal("sub-1") is True


def test_siblings_all_terminal_false_for_unknown(store):
    assert store.siblings_all_terminal("nope") is False


def test_submission_context_roundtrip(store):
    store.save_submission_context("sub-1", '{"subject": "x"}')
    assert store.get_submission_context("sub-1") == '{"subject": "x"}'
    # upsert: re-guardar sobreescribe
    store.save_submission_context("sub-1", '{"subject": "y"}')
    assert store.get_submission_context("sub-1") == '{"subject": "y"}'


def test_get_submission_context_none_for_unknown(store):
    assert store.get_submission_context("nope") is None


def test_try_claim_submission_email_single_winner(store):
    store.save_submission_context("sub-1", "{}")
    assert store.try_claim_submission_email("sub-1") is True
    # segundo intento pierde
    assert store.try_claim_submission_email("sub-1") is False


def test_try_claim_submission_email_creates_row_if_absent(store):
    # sin save previo: igual debe poder reclamar una vez
    assert store.try_claim_submission_email("sub-2") is True
    assert store.try_claim_submission_email("sub-2") is False
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/quote_queue/test_store.py -v`
Expected: FAIL con `AttributeError: ... 'siblings_all_terminal'`.

- [ ] **Step 3: Implementar los métodos de submission**

Agregar a `QuoteQueueStore` (antes de `close`):

```python
    def siblings_all_terminal(self, submission_id) -> bool:
        """True si TODOS los jobs de la submission están en estado terminal.

        False si no hay jobs, o si alguno sigue pending/claimed/running/deferred.
        El manejo del caso "deferred eterno" (mandar el correo igual tras un
        máximo de espera) vive en el worker, no acá.
        """
        terminal = tuple(s.value for s in TERMINAL_STATUSES)
        placeholders = ",".join("?" * len(terminal))
        with self._lock:
            total = self._conn.execute(
                "SELECT COUNT(*) FROM quote_jobs WHERE submission_id=?",
                (submission_id,),
            ).fetchone()[0]
            if total == 0:
                return False
            non_terminal = self._conn.execute(
                "SELECT COUNT(*) FROM quote_jobs WHERE submission_id=? "
                f"AND status NOT IN ({placeholders})",
                (submission_id, *terminal),
            ).fetchone()[0]
            return non_terminal == 0

    def save_submission_context(self, submission_id, context_json: str) -> None:
        """Guarda (upsert) el contexto opaco para armar el correo más tarde."""
        now = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT INTO submissions (submission_id, context_json, email_sent, created_at) "
                "VALUES (?, ?, 0, ?) "
                "ON CONFLICT(submission_id) DO UPDATE SET context_json=excluded.context_json",
                (submission_id, context_json, now),
            )
            self._conn.commit()

    def get_submission_context(self, submission_id) -> Optional[str]:
        with self._lock:
            row = self._conn.execute(
                "SELECT context_json FROM submissions WHERE submission_id=?",
                (submission_id,),
            ).fetchone()
            return row["context_json"] if row else None

    def try_claim_submission_email(self, submission_id) -> bool:
        """Reclama el derecho a mandar el correo de esta submission.

        Atómico: solo el primer caller gana (True); el resto recibe False.
        Crea la fila si no existía (caso sin save_submission_context previo).
        """
        now = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT INTO submissions (submission_id, email_sent, created_at) "
                "VALUES (?, 0, ?) ON CONFLICT(submission_id) DO NOTHING",
                (submission_id, now),
            )
            cur = self._conn.execute(
                "UPDATE submissions SET email_sent=1 "
                "WHERE submission_id=? AND email_sent=0",
                (submission_id,),
            )
            self._conn.commit()
            return cur.rowcount == 1
```

- [ ] **Step 4: Correr y verificar que pasan**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/quote_queue/test_store.py -v`
Expected: PASS (todos).

- [ ] **Step 5: Commit**

```bash
git add modules/quote_queue/store.py tests/quote_queue/test_store.py
git commit -m "feat(quote-queue): contexto de submission + siblings_all_terminal + claim de email anti-doble-envio"
```

---

## Task 7: Store — `recently_quoted` (idempotencia por USDOT) + smoke test multi-thread

**Files:**
- Modify: `modules/quote_queue/store.py`
- Test: `tests/quote_queue/test_store.py` (agregar tests)

- [ ] **Step 1: Escribir los tests que fallan**

Agregar al final de `tests/quote_queue/test_store.py`:

```python
import threading


def test_recently_quoted_counts_jobs_in_window(store):
    now = __import__("time").time()
    store.enqueue("sub-1", "PROGRESSIVE", "{}", None, "111")
    store.enqueue("sub-2", "PROGRESSIVE", "{}", None, "111")
    store.enqueue("sub-3", "PROGRESSIVE", "{}", None, "999")  # otro USDOT
    # ventana de 24h
    assert store.recently_quoted("PROGRESSIVE", "111", now - 86400) == 2
    assert store.recently_quoted("PROGRESSIVE", "999", now - 86400) == 1
    assert store.recently_quoted("GEICO", "111", now - 86400) == 0
    # ventana en el futuro → nada cuenta
    assert store.recently_quoted("PROGRESSIVE", "111", now + 86400) == 0


def test_concurrent_claims_never_double_claim(store):
    # 50 jobs, 4 threads reclamando: cada job se reclama exactamente una vez.
    for i in range(50):
        store.enqueue(f"sub-{i}", "PROGRESSIVE", "{}", None, str(i))

    claimed_ids = []
    lock = threading.Lock()

    def worker():
        while True:
            job = store.claim_next("PROGRESSIVE")
            if job is None:
                return
            with lock:
                claimed_ids.append(job.id)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(claimed_ids) == 50
    assert len(set(claimed_ids)) == 50  # sin duplicados
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/quote_queue/test_store.py -v`
Expected: FAIL con `AttributeError: ... 'recently_quoted'`.

- [ ] **Step 3: Implementar recently_quoted**

Agregar a `QuoteQueueStore` (antes de `close`):

```python
    def recently_quoted(self, mga, usdot, since_epoch: float) -> int:
        """Cuántos jobs se crearon para (mga, usdot) desde since_epoch.

        Para honrar 'no re-cotizar el mismo USDOT >3x/día': el caller pasa
        since_epoch = now - 86400 y chequea el conteo < 3 antes de encolar.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM quote_jobs "
                "WHERE mga=? AND usdot=? AND created_at>=?",
                (mga, usdot, since_epoch),
            ).fetchone()
            return row[0]
```

- [ ] **Step 4: Correr y verificar que pasan**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/quote_queue/test_store.py -v`
Expected: PASS (todos).

- [ ] **Step 5: Correr toda la suite del paquete + pyflakes**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/quote_queue/ -v`
Expected: PASS (todos los archivos del paquete).

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pyflakes modules/quote_queue/`
Expected: sin salida (exit 0).

- [ ] **Step 6: Commit**

```bash
git add modules/quote_queue/store.py tests/quote_queue/test_store.py
git commit -m "feat(quote-queue): recently_quoted (idempotencia USDOT) + smoke test concurrente"
```

---

## Lo que sigue (planes posteriores)

Este Plan 1 deja el core de la cola listo y testeado. Pendientes (planes propios, a redactar tras leer sus archivos objetivo):

- **Parte 2 — Captura PDF de la página de precio final** (Progressive `coverages_rates_page` + GEICO final details; `pdf_path` en el `QuoteResult` de Progressive; fallback PNG headed). Requiere leer ambos page objects y el `QuoteResult`/cliente de cada MGA.
- **Parte 3 — Integración del pipeline** (`messages.py` catálogo humanizado dirigido al agente; sección RPA en `build_analysis_email` + template; `worker.py`; integración en `workflow_orchestrator._process_submission`; `runner.py`). Requiere leer `email_receiver`, el template `config/templates/analysis_email.html` y el cliente GEICO.

## Notas de diseño verificadas contra el código

- `QuoteProfile.to_dict()` existe (`asdict`); `from_dict` (Task 1) es su inverso.
- El bot corre en un solo proceso con un worker-thread por MGA → el `threading.Lock` del store da atomicidad sin transacciones cross-process. Si se va multi-proceso, migrar `claim_next` a `BEGIN IMMEDIATE`.
- `deferred` cuenta como NO terminal en `siblings_all_terminal`; el "deferred eterno" lo resuelve el worker (Parte 3) con un máximo de espera.
- El contexto de submission se guarda como **string opaco** (`context_json`): el store no necesita conocer su forma; esa decisión (qué serializar, dónde van los adjuntos) es de la Parte 3.
