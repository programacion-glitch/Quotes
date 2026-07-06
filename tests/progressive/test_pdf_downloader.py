"""Unit del downloader del PDF oficial de Progressive (page.evaluate mockeado)."""
import base64
import json

import pytest

from modules.progressive.pdf_downloader import download_progressive_pdf


class FakePage:
    """Async page double: evaluate() devuelve un JSON string preseteado."""
    def __init__(self, payload):
        self._payload = payload
        self.evaluate_args = []

    async def evaluate(self, js, arg=None):
        self.evaluate_args.append(arg)
        return self._payload


def _ok_payload(pdf_bytes):
    return json.dumps({
        "contentType": "application/pdf",
        "size": len(pdf_bytes),
        "base64": base64.b64encode(pdf_bytes).decode(),
    })


@pytest.mark.asyncio
async def test_download_writes_pdf_bytes(tmp_path):
    out = tmp_path / "q.pdf"
    page = FakePage(_ok_payload(b"%PDF-1.7 abc"))
    res = await download_progressive_pdf(page, "https://clpolicy/x", out)
    assert res["path"] == str(out)
    assert res["size"] == len(b"%PDF-1.7 abc")
    assert res["content_type"] == "application/pdf"
    assert out.read_bytes() == b"%PDF-1.7 abc"
    assert page.evaluate_args and page.evaluate_args[0]["url"] == "https://clpolicy/x"


@pytest.mark.asyncio
async def test_download_empty_url_raises(tmp_path):
    page = FakePage(_ok_payload(b"%PDF-1.7"))
    with pytest.raises(RuntimeError, match="empty or None"):
        await download_progressive_pdf(page, "", tmp_path / "q.pdf")


@pytest.mark.asyncio
async def test_download_http_error_raises(tmp_path):
    page = FakePage(json.dumps({"error": "http 500", "statusText": "Server Error"}))
    with pytest.raises(RuntimeError, match="http 500"):
        await download_progressive_pdf(page, "https://clpolicy/x", tmp_path / "q.pdf")


@pytest.mark.asyncio
async def test_download_non_pdf_content_type_raises(tmp_path):
    page = FakePage(json.dumps({
        "contentType": "text/html", "size": 3,
        "base64": base64.b64encode(b"<h1").decode(),
    }))
    with pytest.raises(RuntimeError, match="non-PDF content-type"):
        await download_progressive_pdf(page, "https://clpolicy/x", tmp_path / "q.pdf")


@pytest.mark.asyncio
async def test_download_missing_magic_raises(tmp_path):
    page = FakePage(json.dumps({
        "contentType": "application/pdf", "size": 5,
        "base64": base64.b64encode(b"<html").decode(),
    }))
    with pytest.raises(RuntimeError, match="magic number missing"):
        await download_progressive_pdf(page, "https://clpolicy/x", tmp_path / "q.pdf")
