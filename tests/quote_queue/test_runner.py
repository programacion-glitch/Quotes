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


def test_poll_once_guard_skips_non_matching_sender():
    gmail = MagicMock()
    gmail.fetch_unread.return_value = [
        {"id": "m1", "subject": "Submission // ACME", "sender_email": "simon@h2oins.com"},
        {"id": "m2", "subject": "Submission // OTHER", "sender_email": "ajeno@gmail.com"},
    ]
    orch = MagicMock()
    n = runner.poll_once(gmail, orch, "Submission",
                         rt_senders={"simon@h2oins.com"},
                         new_venture_senders=set())
    assert n == 1
    orch.process_email.assert_called_once()
    gmail.add_label.assert_called_once_with("m1", "Procesado-Bot")


def test_poll_once_guard_skips_reply_subject():
    gmail = MagicMock()
    gmail.fetch_unread.return_value = [
        {"id": "m1", "subject": "Re: Submission // ACME",
         "sender_email": "simon@h2oins.com"},
    ]
    orch = MagicMock()
    n = runner.poll_once(gmail, orch, "Submission",
                         rt_senders={"simon@h2oins.com"},
                         new_venture_senders=set())
    assert n == 0
    orch.process_email.assert_not_called()
    gmail.add_label.assert_not_called()


def test_poll_once_passes_from_allowlist_union():
    gmail = MagicMock()
    gmail.fetch_unread.return_value = []
    orch = MagicMock()
    runner.poll_once(gmail, orch, "Submission",
                     rt_senders={"simon@h2oins.com"},
                     new_venture_senders={"duvan@h2oins.com"})
    _, kwargs = gmail.fetch_unread.call_args
    assert sorted(kwargs.get("from_allowlist")) == [
        "duvan@h2oins.com", "simon@h2oins.com"]


def test_load_sender_sets_lowercases_and_splits_groups():
    class FakeConfig:
        def get(self, key, default=None):
            data = {
                "email.monitoring.senders.rt":
                    ["Simon@H2Oins.com", "esteban@h2oins.com"],
                "email.monitoring.senders.new_venture":
                    ["Duvan@h2oins.com"],
            }
            return data.get(key, default)

    rt, nv = runner._load_sender_sets(FakeConfig())
    assert rt == {"simon@h2oins.com", "esteban@h2oins.com"}
    assert nv == {"duvan@h2oins.com"}


def test_load_sender_sets_empty_when_missing():
    class FakeConfig:
        def get(self, key, default=None):
            return default

    rt, nv = runner._load_sender_sets(FakeConfig())
    assert rt == set()
    assert nv == set()
