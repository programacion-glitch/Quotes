"""Unit del hook de subida a Drive en el QuoteWorker."""
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

from modules.quote_queue.worker import QuoteWorker


def _profile(name="ELITE TRANSPORT ENTERPRISES LLC", usdot="2857089"):
    return SimpleNamespace(applicant=SimpleNamespace(
        business_name=name, usdot=usdot))


def test_upload_indication_calls_drive(monkeypatch):
    monkeypatch.setenv("DRIVE_UPLOAD_ENABLED", "true")
    drive = MagicMock()
    w = QuoteWorker("PROGRESSIVE", MagicMock(), MagicMock(), MagicMock(),
                    drive_manager=drive)
    w._upload_indication(_profile(), "data/quote_pdfs/p.pdf")
    drive.upload_quote_indication.assert_called_once()
    _, kw = drive.upload_quote_indication.call_args
    assert kw["business_name"] == "ELITE TRANSPORT ENTERPRISES LLC"
    assert kw["usdot"] == "2857089"
    assert kw["pdf_path"] == "data/quote_pdfs/p.pdf"
    assert kw["carrier"] == "PROGRESSIVE"


def test_upload_indication_disabled(monkeypatch):
    monkeypatch.setenv("DRIVE_UPLOAD_ENABLED", "false")
    drive = MagicMock()
    w = QuoteWorker("PROGRESSIVE", MagicMock(), MagicMock(), MagicMock(),
                    drive_manager=drive)
    w._upload_indication(_profile(), "data/quote_pdfs/p.pdf")
    drive.upload_quote_indication.assert_not_called()


def test_upload_indication_never_raises(monkeypatch):
    monkeypatch.setenv("DRIVE_UPLOAD_ENABLED", "true")
    drive = MagicMock()
    drive.upload_quote_indication.side_effect = RuntimeError("boom")
    w = QuoteWorker("PROGRESSIVE", MagicMock(), MagicMock(), MagicMock(),
                    drive_manager=drive)
    # No debe propagar la excepción (Drive nunca tumba el worker).
    w._upload_indication(_profile(), "data/quote_pdfs/p.pdf")
