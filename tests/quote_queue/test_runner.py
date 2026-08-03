"""Unit del runner: un ciclo de monitor procesa cada correo y lo RECLAMA en la BD
SIN etiquetarlo ni marcarlo leído. La dedup vive en SQLite, no en Gmail."""
from unittest.mock import MagicMock

from modules.quote_queue import runner


def test_poll_once_processes_without_labels(tmp_path):
    from modules.quote_queue.store import QuoteQueueStore
    store = QuoteQueueStore(tmp_path / "q.db")
    gmail = MagicMock()
    gmail.fetch_unread.return_value = [
        {"id": "m1", "subject": "Submission A"},
        {"id": "m2", "subject": "Submission B"},
    ]
    orch = MagicMock()

    n = runner.poll_once(gmail, orch, "Submission", store)

    assert n == 2
    assert orch.process_email.call_count == 2
    # NO marca leído, NO etiqueta: dedup vive en SQLite.
    gmail.mark_read.assert_not_called()
    gmail.add_label.assert_not_called()
    # El fetch NO excluye etiqueta (no usa label dedup).
    _, kwargs = gmail.fetch_unread.call_args
    assert kwargs.get("exclude_label") is None


def test_poll_once_claims_even_if_process_raises(tmp_path):
    from modules.quote_queue.store import QuoteQueueStore
    store = QuoteQueueStore(tmp_path / "q.db")
    gmail = MagicMock()
    gmail.fetch_unread.return_value = [{"id": "m1", "subject": "X"}]
    orch = MagicMock()
    orch.process_email.side_effect = RuntimeError("boom")

    n = runner.poll_once(gmail, orch, "Submission", store)

    assert n == 1
    # Se reclama en la BD aunque el procesamiento falle.
    assert store.try_claim_email("m1") is False
    gmail.mark_read.assert_not_called()
    gmail.add_label.assert_not_called()


def test_poll_once_passes_after_epoch(tmp_path):
    from modules.quote_queue.store import QuoteQueueStore
    store = QuoteQueueStore(tmp_path / "q.db")
    gmail = MagicMock()
    gmail.fetch_unread.return_value = []
    orch = MagicMock()
    runner.poll_once(gmail, orch, "Submission", store, after_epoch=1750000000)
    _, kwargs = gmail.fetch_unread.call_args
    assert kwargs.get("after_epoch") == 1750000000


def test_poll_once_guard_skips_non_matching_sender(tmp_path):
    from modules.quote_queue.store import QuoteQueueStore
    store = QuoteQueueStore(tmp_path / "q.db")
    gmail = MagicMock()
    gmail.fetch_unread.return_value = [
        {"id": "m1", "subject": "Submission // ACME", "sender_email": "simon@h2oins.com"},
        {"id": "m2", "subject": "Submission // OTHER", "sender_email": "ajeno@gmail.com"},
    ]
    orch = MagicMock()
    n = runner.poll_once(gmail, orch, "Submission", store,
                         rt_senders={"simon@h2oins.com"},
                         new_venture_senders=set())
    assert n == 1
    orch.process_email.assert_called_once()
    # Solo m1 se procesa y se reclama; m2 no pasa el guard.
    assert store.try_claim_email("m1") is False  # reclamado
    assert store.try_claim_email("m2") is True   # nunca se procesó


def test_poll_once_guard_skips_reply_subject(tmp_path):
    from modules.quote_queue.store import QuoteQueueStore
    store = QuoteQueueStore(tmp_path / "q.db")
    gmail = MagicMock()
    gmail.fetch_unread.return_value = [
        {"id": "m1", "subject": "Re: Submission // ACME",
         "sender_email": "simon@h2oins.com"},
    ]
    orch = MagicMock()
    n = runner.poll_once(gmail, orch, "Submission", store,
                         rt_senders={"simon@h2oins.com"},
                         new_venture_senders=set())
    assert n == 0
    orch.process_email.assert_not_called()
    # No se procesa, no se reclama (sigue libre en BD).
    assert store.try_claim_email("m1") is True


def test_poll_once_passes_from_allowlist_union(tmp_path):
    from modules.quote_queue.store import QuoteQueueStore
    store = QuoteQueueStore(tmp_path / "q.db")
    gmail = MagicMock()
    gmail.fetch_unread.return_value = []
    orch = MagicMock()
    runner.poll_once(gmail, orch, "Submission", store,
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


class _MailboxGuardGmail:
    """Gmail fake que EXPLOTA si el bot intenta modificar el buzón."""
    def __init__(self, emails):
        self._emails = emails

    def fetch_unread(self, *a, **k):
        return self._emails

    def add_label(self, *a, **k):
        raise AssertionError("El bot NO debe etiquetar correos (transparencia)")

    def mark_read(self, *a, **k):
        raise AssertionError("El bot NO debe marcar leído (transparencia)")


class _SpyOrchestrator:
    def __init__(self):
        self.processed = []

    def process_email(self, email_data):
        self.processed.append(email_data["id"])


def _email(id_="m1", sender="rt@h2oins.com", subject="Submission - X"):
    return {"id": id_, "sender_email": sender, "subject": subject}


class TestPollOnceTransparente:
    def test_procesa_sin_tocar_el_buzon(self, tmp_path):
        from modules.quote_queue.store import QuoteQueueStore
        store = QuoteQueueStore(tmp_path / "q.db")
        gmail = _MailboxGuardGmail([_email()])
        orch = _SpyOrchestrator()
        n = runner.poll_once(gmail, orch, "Submission", store,
                      rt_senders={"rt@h2oins.com"}, new_venture_senders=set())
        assert n == 1
        assert orch.processed == ["m1"]

    def test_no_reprocesa_correo_ya_visto(self, tmp_path):
        from modules.quote_queue.store import QuoteQueueStore
        store = QuoteQueueStore(tmp_path / "q.db")
        gmail = _MailboxGuardGmail([_email()])
        orch = _SpyOrchestrator()
        runner.poll_once(gmail, orch, "Submission", store,
                  rt_senders={"rt@h2oins.com"}, new_venture_senders=set())
        n2 = runner.poll_once(gmail, orch, "Submission", store,
                       rt_senders={"rt@h2oins.com"}, new_venture_senders=set())
        assert n2 == 0
        assert orch.processed == ["m1"]  # una sola vez

    def test_correo_no_procesable_no_se_reclama(self, tmp_path):
        """Un correo que no pasa el guard de remitentes NO se reclama:
        si mañana entra al allowlist, se puede procesar."""
        from modules.quote_queue.store import QuoteQueueStore
        store = QuoteQueueStore(tmp_path / "q.db")
        gmail = _MailboxGuardGmail([_email(sender="otro@x.com")])
        orch = _SpyOrchestrator()
        n = runner.poll_once(gmail, orch, "Submission", store,
                      rt_senders={"rt@h2oins.com"}, new_venture_senders=set())
        assert n == 0
        assert store.try_claim_email("m1") is True  # sigue libre

    def test_crash_de_procesamiento_no_reprocesa(self, tmp_path):
        """Mismo comportamiento que la etiqueta vieja: reclamado aunque falle."""
        from modules.quote_queue.store import QuoteQueueStore
        store = QuoteQueueStore(tmp_path / "q.db")

        class Boom:
            def process_email(self, email_data):
                raise RuntimeError("boom")

        gmail = _MailboxGuardGmail([_email()])
        runner.poll_once(gmail, Boom(), "Submission", store,
                  rt_senders={"rt@h2oins.com"}, new_venture_senders=set())
        assert store.try_claim_email("m1") is False


def test_poll_once_pasa_skip_que_salta_ya_vistos(tmp_path):
    """El skip (metadata-first) evita re-descargar correos ya reclamados."""
    from modules.quote_queue.store import QuoteQueueStore
    store = QuoteQueueStore(tmp_path / "q.db")
    store.try_claim_email("viejo")
    gmail = MagicMock()
    gmail.fetch_unread.return_value = []
    orch = MagicMock()

    runner.poll_once(gmail, orch, "Submission", store)

    _, kwargs = gmail.fetch_unread.call_args
    skip = kwargs.get("skip_message_id")
    assert skip is not None
    assert skip("viejo") is True
    assert skip("nuevo") is False


def test_poll_once_guard_rechazado_entra_al_skip_cache(tmp_path):
    """Un correo rechazado por el guard no se reclama, pero queda en el
    cache en memoria para no re-descargarlo cada ciclo de 5s."""
    from modules.quote_queue.store import QuoteQueueStore
    store = QuoteQueueStore(tmp_path / "q.db")
    gmail = MagicMock()
    gmail.fetch_unread.return_value = [
        {"id": "mx", "subject": "Submission X",
         "sender_email": "desconocido@otro.com"},
    ]
    orch = MagicMock()
    cache = set()

    n = runner.poll_once(gmail, orch, "Submission", store,
                         rt_senders={"ventas@h2o.com"},
                         new_venture_senders=set(), skip_cache=cache)

    assert n == 0
    assert "mx" in cache            # no se re-descarga este proceso
    assert store.is_seen("mx") is False  # pero NO quedó reclamado (durable)
    _, kwargs = gmail.fetch_unread.call_args
    assert kwargs["skip_message_id"]("mx") is True
