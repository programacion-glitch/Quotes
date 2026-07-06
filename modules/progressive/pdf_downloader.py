"""Descarga del PDF oficial (proposal) de una cotización de Progressive.

El endpoint `clpolicy.foragentsonly.com/Express/PDFHandler.ashx?...DocumentType=Quote`
sirve el PDF INLINE (no dispara download dialog), igual que GEICO — por eso se usa
un fetch autenticado dentro del contexto de la página en vez de expect_download().
Patrón espejo de `modules/geico/pdf_downloader.py` (probado live).
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Union

from playwright.async_api import Page


_FETCH_PDF_JS = """
async (args) => {
    const url = args.url;
    const timeoutMs = args.timeoutMs || 30000;
    try {
        const ctrl = new AbortController();
        const timer = setTimeout(() => ctrl.abort(), timeoutMs);
        let res;
        try {
            res = await fetch(url, {credentials: 'include', signal: ctrl.signal});
        } finally {
            clearTimeout(timer);
        }
        if (!res.ok) return JSON.stringify({error: 'http ' + res.status, statusText: res.statusText});
        const ct = res.headers.get('content-type');
        const buf = await res.arrayBuffer();
        const bytes = new Uint8Array(buf);
        let binary = '';
        const chunkSize = 0x8000;
        for (let i = 0; i < bytes.length; i += chunkSize) {
            binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunkSize));
        }
        const b64 = btoa(binary);
        return JSON.stringify({contentType: ct, size: bytes.length, base64: b64});
    } catch (e) {
        const msg = (e && e.name === 'AbortError')
            ? ('timeout after ' + timeoutMs + 'ms')
            : (e && e.message ? e.message : String(e));
        return JSON.stringify({error: msg});
    }
}
"""


async def download_progressive_pdf(
    page: Page,
    pdf_url: str,
    output_path: Union[Path, str],
    timeout_ms: int = 30_000,
) -> dict:
    """Descarga el PDF de `pdf_url` usando el contexto autenticado de `page`.

    `page` debe estar en un origen clpolicy.foragentsonly.com para que las cookies
    apliquen. Devuelve {"path","size","content_type"}. Lanza RuntimeError en
    cualquier fallo (url vacía, http error, timeout, content-type no-pdf, sin
    %PDF, o error de escritura).
    """
    if not pdf_url:
        raise RuntimeError("download_progressive_pdf: pdf_url is empty or None")
    raw = await page.evaluate(_FETCH_PDF_JS, {"url": pdf_url, "timeoutMs": timeout_ms})

    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Progressive PDF fetch returned unparseable payload: {exc}") from exc

    if not isinstance(data, dict):
        raise RuntimeError(f"Progressive PDF fetch returned unexpected payload type: {type(data).__name__}")

    if "error" in data:
        status_text = data.get("statusText", "")
        raise RuntimeError(f"Progressive PDF fetch failed ({data['error']}): {status_text or 'no detail'}")

    content_type = (data.get("contentType") or "").strip()
    if not content_type.lower().startswith("application/pdf"):
        raise RuntimeError(f"Progressive PDF fetch returned non-PDF content-type: {content_type!r}")

    b64_payload = data.get("base64")
    if not b64_payload:
        raise RuntimeError("Progressive PDF fetch returned no base64 payload")

    try:
        pdf_bytes = base64.b64decode(b64_payload)
    except (ValueError, TypeError) as exc:
        raise RuntimeError(f"Progressive PDF base64 decode failed: {exc}") from exc

    if not pdf_bytes.startswith(b"%PDF"):
        raise RuntimeError(
            f"Progressive PDF magic number missing (got {pdf_bytes[:8]!r}); endpoint "
            "likely returned an HTML error page despite content-type."
        )

    out_path = Path(output_path)
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(pdf_bytes)
    except OSError as exc:
        raise RuntimeError(f"Progressive PDF write failed at {out_path}: {exc}") from exc

    return {"path": str(out_path), "size": len(pdf_bytes), "content_type": content_type}
