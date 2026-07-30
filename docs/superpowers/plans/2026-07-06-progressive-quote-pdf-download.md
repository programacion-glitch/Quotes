# Descarga del PDF oficial de Progressive — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reemplazar el render de página (`save_page_pdf`) por la descarga del PDF oficial de la cotización de Progressive, con reintento y fallback a la captura.

**Architecture:** Un módulo `pdf_downloader.py` (espejo del de GEICO) hace el fetch autenticado `credentials:'include'` del endpoint `PDFHandler.ashx` y valida `%PDF`. Un método nuevo `CoveragesRatesPage.download_quote_pdf` orquesta el flujo UI (Print, Email, Fax → Insurance Quote → Print → Print/Send → captura del popup → fetch → Return to quote), con retry y garantía de volver a RATES. `quote_flow.py` lo llama y cae a `save_page_pdf` si devuelve None.

**Tech Stack:** Python 3.12, Playwright (async), pytest + pytest-asyncio.

## Global Constraints

- Intérprete Python (NO en PATH): `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe`. Tests: `<python> -m pytest <ruta> -v`.
- El flujo termina en FINAL DETAILS; NUNCA se clickea el Continue final ni se bindea. Este cambio ocurre ANTES de eso, en RATES.
- Endpoint del PDF (se captura del popup, NO se arma): URL con `PDFHandler.ashx` y `DocumentType=Quote`. content-type `application/pdf`, magic `%PDF`.
- El fetch se hace desde `self.page` (la wizard page, origen `clpolicy.foragentsonly.com`) para que apliquen las cookies.
- POST-CONDICIÓN de `download_quote_pdf`: al retornar (éxito o None), el wizard queda en RATES (`pageName=CoveragesRates`).
- La cotización NUNCA falla por el PDF: `download_quote_pdf` no propaga; devuelve None y el caller cae a `save_page_pdf`.
- Selectores por rol para botones de acción (como `login_page.py`), con `remove_overlays` + `force=True`. `safe_radio`/`safe_checkbox` para los controles de formulario.
- Commits: cada commit termina con el trailer del proyecto:
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_013KyDtAX1fj3ZKoWymRqkLo
  ```

---

### Task 1: Módulo `pdf_downloader.py` (fetch + validación)

**Files:**
- Create: `modules/progressive/pdf_downloader.py`
- Test:   `tests/progressive/test_pdf_downloader.py`

**Interfaces:**
- Produces: `async download_progressive_pdf(page, pdf_url: str, output_path, timeout_ms: int = 30_000) -> dict` con claves `{"path","size","content_type"}`; lanza `RuntimeError` en cualquier fallo.

- [ ] **Step 1: Write the failing test** — crear `tests/progressive/test_pdf_downloader.py`:

```python
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
    # se pasó la url al JS de fetch
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/progressive/test_pdf_downloader.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'modules.progressive.pdf_downloader'`

- [ ] **Step 3: Write minimal implementation** — crear `modules/progressive/pdf_downloader.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/progressive/test_pdf_downloader.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add modules/progressive/pdf_downloader.py tests/progressive/test_pdf_downloader.py
git commit -m "feat(progressive): download_progressive_pdf (fetch autenticado del PDFHandler)"
```
(Con el trailer del proyecto en el mensaje.)

---

### Task 2: `CoveragesRatesPage.download_quote_pdf` + `_ensure_on_rates`

**Files:**
- Modify: `modules/progressive/pages/coverages_rates_page.py` (agregar 2 métodos + import de `Optional`/`Path` si faltan)

**Interfaces:**
- Consumes: `download_progressive_pdf(page, url, out_path)` (Task 1); primitivas BasePage: `current_page_token()`, `remove_overlays()`, `wait_for_page(token)`, `wait_for_extjs_idle()`, `safe_radio(group, option)`, `safe_checkbox(locator)`.
- Produces: `async download_quote_pdf(self, name: str, *, output_dir: str = "data/quote_pdfs", max_attempts: int = 2) -> Optional[str]` (devuelve el path del PDF o None). `async _ensure_on_rates(self, *, timeout_ms: int = 30_000) -> None`.

- [ ] **Step 1: Confirmar imports.** Abrir `modules/progressive/pages/coverages_rates_page.py`. Verificar que arriba estén `from pathlib import Path` y `from typing import Optional`. Si falta alguno, agregarlo junto a los imports existentes (no dupliques). (El archivo ya usa `QuotePrice` y `MappedFields`; agregá solo lo que falte.)

- [ ] **Step 2: Agregar los dos métodos** dentro de la clase `CoveragesRatesPage`, justo DESPUÉS de `proceed_to_final_details` (que termina en la línea ~293, antes del comentario `# ---- Helpers ----`). Pegar exactamente:

```python
    async def _ensure_on_rates(self, *, timeout_ms: int = 30_000) -> None:
        """Garantiza que el wizard esté en RATES (pageName=CoveragesRates).

        No-op si ya está en RATES (evita re-rate). Si no, click el step 'RATES'
        del nav superior y espera a que cargue.
        """
        if await self.current_page_token() == "CoveragesRates":
            return
        await self.remove_overlays()
        try:
            await self.page.get_by_role("button", name="RATES", exact=True).click(
                force=True, timeout=10_000
            )
        except Exception:
            pass
        await self.wait_for_page("CoveragesRates", timeout_ms=timeout_ms)
        await self.wait_for_extjs_idle()

    async def download_quote_pdf(
        self, name: str, *, output_dir: str = "data/quote_pdfs", max_attempts: int = 2
    ) -> Optional[str]:
        """Descarga el PDF oficial (proposal) desde RATES.

        Flujo: 'Print, Email, Fax' -> radio 'Insurance Quote' -> checkbox 'Print'
        -> 'Print/Send' (abre popup con el PDF) -> captura la URL del popup ->
        fetch autenticado -> 'Return to quote'. Reintenta hasta `max_attempts`; si
        todos fallan devuelve None (el caller cae a save_page_pdf).

        PRE: el wizard está en RATES. POST: al retornar (éxito o None) queda en RATES.
        """
        from modules.progressive.pdf_downloader import download_progressive_pdf

        out_path = Path(output_dir) / f"progressive_quote_{name}.pdf"
        last_err = None
        for attempt in range(max_attempts):
            try:
                await self._ensure_on_rates()

                # 1) Print, Email, Fax -> PrintEmailFax
                await self.remove_overlays()
                await self.page.get_by_role(
                    "button", name="Print, Email, Fax"
                ).click(force=True, timeout=10_000)
                await self.wait_for_page("PrintEmailFax")
                await self.wait_for_extjs_idle()

                # 2) radio "Insurance Quote (with all bill plans)"
                await self.safe_radio(
                    self.page.get_by_role("radiogroup").first,
                    "Insurance Quote (with all bill plans)",
                )
                await self.wait_for_extjs_idle()

                # 3) checkbox "Print" -> revela "Print/Send"
                await self.safe_checkbox(
                    self.page.get_by_role("checkbox", name="Print", exact=True)
                )
                print_send = self.page.get_by_role("button", name="Print/Send")
                await print_send.wait_for(state="visible", timeout=10_000)

                # 4) Print/Send -> popup con el PDF inline
                await self.remove_overlays()
                async with self.page.context.expect_page(timeout=20_000) as popup_info:
                    await print_send.click(force=True, timeout=10_000)
                popup = await popup_info.value
                try:
                    await popup.wait_for_url("**/PDFHandler.ashx**", timeout=15_000)
                except Exception:
                    pass
                pdf_url = popup.url
                try:
                    await popup.close()
                except Exception:
                    pass
                if "PDFHandler.ashx" not in pdf_url:
                    raise RuntimeError(
                        f"popup URL no es un endpoint PDFHandler: {pdf_url[:120]}"
                    )

                # 5) fetch desde self.page (quedó en PrintEmailFaxConfirm, clpolicy)
                info = await download_progressive_pdf(self.page, pdf_url, out_path)
                print(
                    f"    [Progressive] PDF oficial: {info['size']} bytes -> {info['path']}"
                )

                # 6) Return to quote -> RATES
                await self.remove_overlays()
                try:
                    await self.page.get_by_role(
                        "button", name="Return to quote"
                    ).click(force=True, timeout=10_000)
                except Exception:
                    pass
                await self._ensure_on_rates()
                return str(out_path)

            except Exception as e:
                last_err = e
                print(
                    f"    [Progressive] download_quote_pdf intento "
                    f"{attempt + 1}/{max_attempts} falló: {e}"
                )
                try:
                    await self._ensure_on_rates()
                except Exception:
                    pass

        print(
            f"    [Progressive] PDF oficial no descargado tras {max_attempts} "
            f"intentos ({last_err})"
        )
        try:
            await self._ensure_on_rates()
        except Exception:
            pass
        return None
```

- [ ] **Step 3: Smoke check** — la firma importa y son coroutines (no hay unit test de browser; el flujo se valida LIVE, como el resto de las pages de Progressive):

Run:
```
C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -c "import inspect; from modules.progressive.pages.coverages_rates_page import CoveragesRatesPage as C; assert inspect.iscoroutinefunction(C.download_quote_pdf); assert inspect.iscoroutinefunction(C._ensure_on_rates); print('OK smoke')"
```
Expected: `OK smoke`

- [ ] **Step 4: No-regression** — correr los tests de Progressive (deben seguir verdes; confirma que el archivo sigue importable y nada se rompió):

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/progressive/ -q`
Expected: PASS (mismos que antes + los 5 nuevos de Task 1; sin fallos nuevos).

- [ ] **Step 5: Commit**

```bash
git add modules/progressive/pages/coverages_rates_page.py
git commit -m "feat(progressive): download_quote_pdf (Print,Email,Fax -> PDF oficial, retry, vuelve a RATES)"
```
(Con el trailer.)

---

### Task 3: Integrar en `quote_flow.py` (primary + fallback)

**Files:**
- Modify: `modules/progressive/quote_flow.py:197-202`

**Interfaces:**
- Consumes: `CoveragesRatesPage.download_quote_pdf(name)` (Task 2); `CoveragesRatesPage.save_page_pdf(name)` (existente).

- [ ] **Step 1: Reemplazar el bloque.** En `modules/progressive/quote_flow.py`, el bloque actual (líneas ~197-202) es:

```python
            # Imprimir la página RATES completa (donde se ve el premium) a PDF —
            # es la "impresión" que se adjunta al correo. Se captura ACÁ, antes
            # de proceed_to_final_details() que navega fuera de RATES.
            result.pdf_path = await rates_page.save_page_pdf(
                f"quote_{(result.price.quote_number if result.price else None) or 'unknown'}"
            )
```

Reemplazarlo por:

```python
            # Descargar el PDF OFICIAL de la cotización (proposal) desde RATES,
            # antes de proceed_to_final_details() que navega fuera de RATES. Si la
            # descarga falla tras reintentos, se cae a la captura de la página
            # (save_page_pdf) para no perder la evidencia. download_quote_pdf deja
            # el wizard en RATES pase lo que pase.
            _pdf_name = f"quote_{(result.price.quote_number if result.price else None) or 'unknown'}"
            result.pdf_path = await rates_page.download_quote_pdf(_pdf_name)
            if not result.pdf_path:
                result.warnings.append(
                    "PDF oficial de Progressive falló tras reintentos; "
                    "fallback a captura de RATES"
                )
                result.pdf_path = await rates_page.save_page_pdf(_pdf_name)
```

- [ ] **Step 2: Smoke check** — el módulo importa sin errores y `QuoteResult.pdf_path` sigue defaulteando a None:

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/progressive/test_quote_result_pdf_path.py -v`
Expected: PASS (1 passed)

- [ ] **Step 3: Import check** — confirmar que quote_flow importa limpio:

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -c "import modules.progressive.quote_flow as m; print('OK import', bool(m.QuoteFlow))"`
Expected: `OK import True`

- [ ] **Step 4: Commit**

```bash
git add modules/progressive/quote_flow.py
git commit -m "feat(progressive): quote_flow usa download_quote_pdf con fallback a save_page_pdf"
```
(Con el trailer.)

---

### Task 4: Suite completa verde

**Files:** ninguno (verificación).

- [ ] **Step 1: Correr toda la suite**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest -q`
Expected: PASS salvo los 2 fallos PRE-EXISTENTES de `tests/test_rule_engine.py` (`test_business_years_too_low`, `test_informational_passed_through`) — NO atribuirlos a este cambio. El conteo de `passed` debe subir en +5 (Task 1) respecto del baseline.

- [ ] **Step 2: (Sin commit)** — reportar resultado. La validación LIVE de `download_quote_pdf` (adjuntar el `DataProDocument.pdf` real) queda para una corrida con sesión Progressive, fuera de este plan.
