import threading

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


def test_mark_terminal_coerces_pathlib_screenshot(store):
    """Regresión: Progressive falla → screenshot_path es un pathlib.Path.

    Antes esto crasheaba con "Error binding parameter 4 - probably unsupported
    type" y dejaba el job colgado en RUNNING (no se mandaba el correo). El borde
    de persistencia debe stringificar el Path, no reventar.
    """
    from pathlib import Path

    job_id = store.enqueue("sub-1", "PROGRESSIVE", "{}", None, "4452732")
    store.claim_next("PROGRESSIVE")
    store.mark_terminal(
        job_id, JobStatus.FAILED, error="error",
        screenshot_path=Path("logs/progressive_business_info.png"),
        pdf_path=Path("data/quote_pdfs/x.pdf"),
    )
    job = store.get_jobs("sub-1")[0]
    assert job.status == JobStatus.FAILED.value
    assert isinstance(job.screenshot_path, str)
    assert job.screenshot_path.endswith("progressive_business_info.png")
    assert isinstance(job.pdf_path, str)
    assert job.pdf_path.endswith("x.pdf")
    assert job.lease_until is None


def test_mark_terminal_rejects_non_terminal_status(store):
    job_id = store.enqueue("sub-1", "PROGRESSIVE", "{}", None, "111")
    with pytest.raises(ValueError):
        store.mark_terminal(job_id, JobStatus.RUNNING)


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
    store.enqueue("sub-1", "PROGRESSIVE", "{}", None, "111")
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


def test_save_context_after_claim_preserves_email_sent(store):
    # Invariante anti doble-envío: re-guardar contexto tras reclamar el email
    # NO debe permitir un segundo envío.
    store.save_submission_context("sub-1", "{}")
    assert store.try_claim_submission_email("sub-1") is True
    store.save_submission_context("sub-1", '{"updated": true}')
    assert store.try_claim_submission_email("sub-1") is False
