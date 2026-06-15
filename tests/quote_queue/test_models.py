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
