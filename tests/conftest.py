"""Root-level pytest fixtures shared by the whole suite."""
import pytest

from modules import decision_ledger


@pytest.fixture(autouse=True)
def _reset_decision_ledger_state():
    """decision_ledger is thread-local BY DESIGN (isolates the Progressive and
    GEICO worker threads in production — see modules/decision_ledger.py).
    Pytest runs the whole suite in one OS thread, so without this reset a
    start_run()/record() call in one test file leaks into the next one that
    happens to run afterwards (e.g. a worker test calling start_run("GEICO")
    would otherwise bleed into test_decision_ledger.py's "no start_run yet"
    assertions). Reset before AND after so isolation holds regardless of
    collection order."""
    decision_ledger._state.__dict__.clear()
    yield
    decision_ledger._state.__dict__.clear()
