"""GEICO Quote Proposal PDF downloader.

Utility to download the `Print Quote Proposal` PDF served by the GEICO Sales
portal at the end of Step 6 (Quote & Coverages). The endpoint is:

    https://sales.geico.com/PrintQuote?doctype=CommercialQuotePdfIAAgent
        &retentionKey=<key>&auth=t&conversationId=<id>&termLength=12

Direct navigation renders the PDF *inline* in a new tab and does NOT trigger a
download dialog, so the standard Playwright `expect_download()` pattern fails.

The pattern below was proven live during the GEICO mapping session for
`HUMBERTO_VILLARREAL` (USDOT 2033673). It produced a 99 KB PDF generated from
the `CommercialQuotePdfIAAgent` template with `"Registered to: GEICO"` in the
PDF metadata.

How it works:
    1. The Page is already authenticated against sales.geico.com (cookies set
       on the same origin as the PrintQuote endpoint).
    2. We run `fetch(url, {credentials: 'include'})` inside the page's JS
       context so the browser attaches the auth cookies automatically.
    3. The ArrayBuffer is converted to base64 in JS in 32 KB chunks to avoid
       blowing the call stack with `String.fromCharCode.apply(null, ...)`.
    4. Python decodes the base64 string and writes the bytes to disk after
       validating the `application/pdf` content-type and the `%PDF` magic
       number.
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Union

from playwright.async_api import Page


# JavaScript executed inside the page context. Uses fetch() with
# credentials:'include' so the authenticated sales.geico.com cookies are sent.
# Returns a JSON string (Playwright serializes return values; a string is
# the safest carrier for a base64 blob).
_FETCH_PDF_JS = """
async (args) => {
    const url = args.url;
    const timeoutMs = args.timeoutMs || 30000;
    try {
        // Bound the fetch with AbortController so a hung PrintQuote endpoint
        // surfaces a clear error instead of stalling the whole page.evaluate.
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
        // Convert to base64 in chunks (avoid stack overflow for large blobs).
        let binary = '';
        const chunkSize = 0x8000;
        for (let i = 0; i < bytes.length; i += chunkSize) {
            binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunkSize));
        }
        const b64 = btoa(binary);
        return JSON.stringify({contentType: ct, size: bytes.length, base64: b64});
    } catch (e) {
        // Distinguish abort from other failures so the caller knows.
        const msg = (e && e.name === 'AbortError')
            ? ('timeout after ' + timeoutMs + 'ms')
            : (e && e.message ? e.message : String(e));
        return JSON.stringify({error: msg});
    }
}
"""


async def download_geico_pdf(
    page: Page,
    pdf_url: str,
    output_path: Union[Path, str],
    timeout_ms: int = 30_000,
) -> dict:
    """Download the GEICO PrintQuote PDF using the page's auth context.

    Args:
        page: Playwright Page already on a sales.geico.com page (same origin
              as the PrintQuote endpoint so cookies apply).
        pdf_url: Absolute URL to the PrintQuote endpoint.
        output_path: Where to write the .pdf file. Parent dir is created.
        timeout_ms: Abort the fetch after this many milliseconds. Default 30s.

    Returns:
        dict with keys: {"path": str, "size": int, "content_type": str}.

    Raises:
        RuntimeError on bad URL, HTTP error, timeout, non-PDF content-type,
        or write failure.
    """
    if not pdf_url:
        raise RuntimeError("download_geico_pdf: pdf_url is empty or None")
    raw = await page.evaluate(
        _FETCH_PDF_JS, {"url": pdf_url, "timeoutMs": timeout_ms}
    )

    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"GEICO PDF fetch returned unparseable payload: {exc}") from exc

    if not isinstance(data, dict):
        raise RuntimeError(f"GEICO PDF fetch returned unexpected payload type: {type(data).__name__}")

    if "error" in data:
        status_text = data.get("statusText", "")
        raise RuntimeError(
            f"GEICO PDF fetch failed ({data['error']}): {status_text or 'no detail'}"
        )

    content_type = (data.get("contentType") or "").strip()
    if not content_type.lower().startswith("application/pdf"):
        raise RuntimeError(
            f"GEICO PDF fetch returned non-PDF content-type: {content_type!r}"
        )

    b64_payload = data.get("base64")
    if not b64_payload:
        raise RuntimeError("GEICO PDF fetch returned no base64 payload")

    try:
        pdf_bytes = base64.b64decode(b64_payload)
    except (ValueError, TypeError) as exc:
        raise RuntimeError(f"GEICO PDF base64 decode failed: {exc}") from exc

    if not pdf_bytes.startswith(b"%PDF"):
        raise RuntimeError(
            f"GEICO PDF magic number missing (got {pdf_bytes[:8]!r}); endpoint "
            "likely returned an HTML error page despite content-type."
        )

    out_path = Path(output_path)
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(pdf_bytes)
    except OSError as exc:
        raise RuntimeError(f"GEICO PDF write failed at {out_path}: {exc}") from exc

    return {
        "path": str(out_path),
        "size": len(pdf_bytes),
        "content_type": content_type,
    }


def quote_pdf_filename(business_name: str, quote_number: str | None = None) -> str:
    """Return a filesystem-safe filename like 'geico_quote_HUMBERTO_VILLARREAL.pdf'
    or 'geico_quote_HUMBERTO_VILLARREAL_CA116960411.pdf' if a quote number is
    available. Spaces and punctuation collapse to underscores.
    """
    name = re.sub(r"[^A-Za-z0-9]+", "_", (business_name or "unknown").strip()).strip("_")
    if not name:
        name = "unknown"
    if quote_number:
        safe_qn = re.sub(r"[^A-Za-z0-9]+", "_", quote_number.strip()).strip("_")
        if safe_qn:
            return f"geico_quote_{name}_{safe_qn}.pdf"
    return f"geico_quote_{name}.pdf"
