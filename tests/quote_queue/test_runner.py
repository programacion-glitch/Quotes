"""Unit del runner: un ciclo de monitor procesa cada correo y lo ETIQUETA como
procesado SIN marcarlo leído (queda NO LEÍDO para el equipo humano)."""
from unittest.mock import MagicMock

from modules.quote_queue import runner


def test_poll_once_processes_and_labels_seen_keeps_unread():
    gmail = MagicMock()
    gmail.fetch_unread.return_value = [
        {"id": "m1", "subject": "Submission A"},
        {"id": "m2", "subject": "Submission B"},
    ]
    orch = MagicMock()

    n = runner.poll_once(gmail, orch, "Submission", seen_label="Procesado-Bot")

    assert n == 2
    assert orch.process_email.call_count == 2
    # NO marca leído: el correo queda NO LEÍDO para el equipo.
    gmail.mark_read.assert_not_called()
    # En su lugar etiqueta como procesado para no reprocesarlo.
    gmail.add_label.assert_any_call("m1", "Procesado-Bot")
    gmail.add_label.assert_any_call("m2", "Procesado-Bot")
    # Y el fetch debe excluir esa etiqueta (dedup sin leído).
    _, kwargs = gmail.fetch_unread.call_args
    assert kwargs.get("exclude_label") == "Procesado-Bot"


def test_poll_once_labels_seen_even_if_process_raises():
    gmail = MagicMock()
    gmail.fetch_unread.return_value = [{"id": "m1", "subject": "X"}]
    orch = MagicMock()
    orch.process_email.side_effect = RuntimeError("boom")

    n = runner.poll_once(gmail, orch, "Submission", seen_label="Procesado-Bot")

    assert n == 1
    gmail.add_label.assert_called_once_with("m1", "Procesado-Bot")
    gmail.mark_read.assert_not_called()


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
