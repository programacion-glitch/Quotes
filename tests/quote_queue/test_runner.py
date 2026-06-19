"""Unit del runner: un ciclo de monitor procesa+marca-leído cada correo."""
from unittest.mock import MagicMock

from modules.quote_queue import runner


def test_poll_once_processes_and_marks_read():
    gmail = MagicMock()
    gmail.fetch_unread.return_value = [
        {"id": "m1", "subject": "Submission A"},
        {"id": "m2", "subject": "Submission B"},
    ]
    orch = MagicMock()

    n = runner.poll_once(gmail, orch, "Submission")

    assert n == 2
    assert orch.process_email.call_count == 2
    gmail.mark_read.assert_any_call("m1")
    gmail.mark_read.assert_any_call("m2")


def test_poll_once_marks_read_even_if_process_raises():
    gmail = MagicMock()
    gmail.fetch_unread.return_value = [{"id": "m1", "subject": "X"}]
    orch = MagicMock()
    orch.process_email.side_effect = RuntimeError("boom")

    n = runner.poll_once(gmail, orch, "Submission")

    assert n == 1
    gmail.mark_read.assert_called_once_with("m1")


def test_poll_once_passes_after_epoch():
    from unittest.mock import MagicMock
    gmail = MagicMock()
    gmail.fetch_unread.return_value = []
    orch = MagicMock()
    runner.poll_once(gmail, orch, "Submission", after_epoch=1750000000)
    _, kwargs = gmail.fetch_unread.call_args
    assert kwargs.get("after_epoch") == 1750000000


def test_load_or_init_cutoff_persists(tmp_path):
    path = str(tmp_path / "cut.txt")
    first = runner._load_or_init_cutoff(path, now=1750000000.0)
    assert first == 1750000000.0
    # Segunda llamada: reusa el valor persistido (ignora el now nuevo).
    second = runner._load_or_init_cutoff(path, now=1760000000.0)
    assert second == 1750000000.0
