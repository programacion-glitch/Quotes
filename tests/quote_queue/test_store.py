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
