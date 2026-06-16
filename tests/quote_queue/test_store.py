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
