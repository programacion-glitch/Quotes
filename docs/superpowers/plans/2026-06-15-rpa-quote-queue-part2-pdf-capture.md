# Cola de Cotización RPA — Parte 2: Captura PDF de la página de precio (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Imprimir a PDF la página completa donde se ve el precio final (Progressive: RATES; GEICO: Quote & Coverages) usando `page.pdf()` de Chromium headless, con fallback a PNG full-page si se corre headed. Esa "impresión" es lo que la Parte 3 adjuntará al correo de análisis.

**Architecture:** Una primitiva nueva `save_page_pdf(name)` en CADA `BasePage` (Progressive y GEICO), análoga a la `screenshot` existente: intenta `self.page.pdf(...)` (solo headless) y cae a `self.page.screenshot(full_page=True)` (PNG) cuando headed. Progressive gana un campo `pdf_path` en su `QuoteResult` (GEICO ya lo tiene) y captura en el paso RATES antes de avanzar. GEICO captura el render de la página de precio dentro de `capture_and_advance` (antes del Next) y lo usa como **fallback confiable** cuando el endpoint flaky `PrintQuote` falla.

**Tech Stack:** Python 3.12, Playwright async (`page.pdf`, `page.screenshot`), `pytest` + `pytest-asyncio` con `FakePage` (sin browser).

**Spec de referencia:** `docs/superpowers/specs/2026-06-15-rpa-quote-queue-design.md`

**Intérprete Python:** `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe` (no está en PATH).

**Hechos verificados contra el código (no re-derivar):**
- Progressive `BasePage.__init__(self, page)` y GEICO `BasePage.__init__(self, page)` — ambos solo reciben `page`. Los tests instancian `BasePage(FakePage())`.
- Progressive `screenshot(self, name, *, output_dir="logs")` (keyword-only) escribe `progressive_{name}.png` full_page. GEICO `screenshot(self, name, output_dir="logs")` (posicional) escribe `geico_{name}.png`. Las primitivas nuevas espejan esa firma por MGA.
- Progressive: el precio se captura en `CoveragesRatesPage.capture_price()` (paso RATES); el flujo sigue a FINAL DETAILS con `proceed_to_final_details()`. En `modules/progressive/quote_flow.py` la línea `result.price = await rates_page.customize_and_capture(fields)` queda **en la página RATES** justo antes de avanzar — ahí se captura el PDF.
- Progressive `QuoteResult` (en `quote_flow.py`) NO tiene `pdf_path`. GEICO `QuoteResult` (en `quote_result_types.py`) SÍ.
- GEICO: `CoveragesPage.capture_and_advance()` captura premium y luego llama `_click_next()` (avanza a Step 7). El PDF del render debe tomarse ANTES de `_click_next()`. El caller (`geico/quote_flow.py`) baja el PrintQuote oficial en un `try/except`; ese `except` es el punto del fallback.

**`pytest-asyncio`:** los tests async usan `@pytest.mark.asyncio`. Verificá que `pytest-asyncio` esté instalado (`...python.exe -m pip show pytest-asyncio`); si no, instalalo (`...python.exe -m pip install pytest-asyncio`). Si el repo ya usa otra config async (revisá `tests/progressive/conftest.py`), seguí ese patrón en su lugar.

---

## File Structure

- **Modify** `modules/progressive/pages/base_page.py` — add `save_page_pdf` primitive.
- **Modify** `modules/progressive/quote_flow.py` — add `pdf_path` to `QuoteResult`; capture at RATES step.
- **Modify** `modules/geico/pages/base_page.py` — add `save_page_pdf` primitive.
- **Modify** `modules/geico/pages/coverages_page.py` — capture render before Next in `capture_and_advance`.
- **Modify** `modules/geico/quote_flow.py` — use render as fallback when PrintQuote fails.
- **Modify** `.gitignore` — ignore `data/quote_pdfs/` (client data, never commit).
- **Create** `tests/progressive/test_save_page_pdf.py`
- **Create** `tests/progressive/test_quote_result_pdf_path.py`
- **Create** `tests/geico/__init__.py`
- **Create** `tests/geico/test_save_page_pdf.py`

---

## Task 1: Progressive — primitiva `save_page_pdf` en BasePage

**Files:**
- Modify: `modules/progressive/pages/base_page.py` (add method right AFTER `screenshot`, ~line 76)
- Test: `tests/progressive/test_save_page_pdf.py`

- [ ] **Step 1: Escribir el test que falla**

Create `tests/progressive/test_save_page_pdf.py`:

```python
import pytest

from modules.progressive.pages.base_page import BasePage


class FakePage:
    """Minimal async page double: records pdf()/screenshot() calls."""

    def __init__(self, pdf_raises=False, screenshot_raises=False):
        self.pdf_raises = pdf_raises
        self.screenshot_raises = screenshot_raises
        self.pdf_calls = []
        self.screenshot_calls = []

    async def pdf(self, path=None, print_background=False, **kw):
        self.pdf_calls.append({"path": path, "print_background": print_background})
        if self.pdf_raises:
            raise RuntimeError("PDF generation is only supported for Headless Chromium")

    async def screenshot(self, path=None, full_page=False, **kw):
        self.screenshot_calls.append({"path": path, "full_page": full_page})
        if self.screenshot_raises:
            raise RuntimeError("screenshot boom")


@pytest.mark.asyncio
async def test_save_page_pdf_headless_writes_pdf(tmp_path):
    page = FakePage()
    bp = BasePage(page)
    out = await bp.save_page_pdf("CA123", output_dir=str(tmp_path))
    assert out == str(tmp_path / "progressive_quote_CA123.pdf")
    assert page.pdf_calls and page.pdf_calls[0]["print_background"] is True
    assert page.screenshot_calls == []  # no fallback when pdf works


@pytest.mark.asyncio
async def test_save_page_pdf_falls_back_to_png_when_headed(tmp_path):
    page = FakePage(pdf_raises=True)
    bp = BasePage(page)
    out = await bp.save_page_pdf("CA123", output_dir=str(tmp_path))
    assert out == str(tmp_path / "progressive_quote_CA123.png")
    assert page.screenshot_calls and page.screenshot_calls[0]["full_page"] is True


@pytest.mark.asyncio
async def test_save_page_pdf_returns_none_when_both_fail(tmp_path):
    page = FakePage(pdf_raises=True, screenshot_raises=True)
    bp = BasePage(page)
    out = await bp.save_page_pdf("CA123", output_dir=str(tmp_path))
    assert out is None
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/progressive/test_save_page_pdf.py -v`
Expected: FAIL con `AttributeError: 'BasePage' object has no attribute 'save_page_pdf'`.

- [ ] **Step 3: Implementar la primitiva**

En `modules/progressive/pages/base_page.py`, INMEDIATAMENTE DESPUÉS del método `screenshot` (después de su `return None`, ~línea 75), agregar:

```python
    async def save_page_pdf(
        self, name: str, *, output_dir: str = "data/quote_pdfs"
    ) -> Optional[str]:
        """Imprime la página ACTUAL a un PDF (la 'impresión' para el correo).

        Usa page.pdf() de Chromium (solo headless). Si se corre headed, page.pdf()
        lanza excepción → fallback a un screenshot full-page (.png). Devuelve el
        path de lo que se escribió, o None si ambos fallan.
        """
        base = Path(output_dir) / f"progressive_quote_{name}"
        pdf_path = base.with_suffix(".pdf")
        try:
            base.parent.mkdir(parents=True, exist_ok=True)
            await self.page.pdf(path=str(pdf_path), print_background=True)
            return str(pdf_path)
        except Exception as e:
            print(f"    [Progressive] page.pdf() no disponible ({e}); fallback a PNG")
            png_path = base.with_suffix(".png")
            try:
                await self.page.screenshot(path=str(png_path), full_page=True)
                return str(png_path)
            except Exception as e2:
                print(f"    [Progressive] captura de página de precio falló: {e2}")
                return None
```

`Path` y `Optional` ya están importados en este archivo (los usa `screenshot`).

- [ ] **Step 4: Correr y verificar que pasa**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/progressive/test_save_page_pdf.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: pyflakes + commit**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pyflakes modules/progressive/pages/base_page.py`
Expected: sin salida.

```bash
git add modules/progressive/pages/base_page.py tests/progressive/test_save_page_pdf.py
git commit -m "feat(progressive): primitiva save_page_pdf (page.pdf headless + fallback PNG)"
```

---

## Task 2: Progressive — `pdf_path` en QuoteResult + captura en el paso RATES

**Files:**
- Modify: `modules/progressive/quote_flow.py` (QuoteResult dataclass + RATES step)
- Modify: `.gitignore`
- Test: `tests/progressive/test_quote_result_pdf_path.py`

- [ ] **Step 1: Escribir el test que falla (campo presente)**

Create `tests/progressive/test_quote_result_pdf_path.py`:

```python
from modules.progressive.quote_flow import QuoteResult


def test_quote_result_has_pdf_path_defaulting_none():
    r = QuoteResult()
    assert r.pdf_path is None
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/progressive/test_quote_result_pdf_path.py -v`
Expected: FAIL con `AttributeError: 'QuoteResult' object has no attribute 'pdf_path'`.

- [ ] **Step 3: Agregar el campo `pdf_path` al QuoteResult de Progressive**

En `modules/progressive/quote_flow.py`, en el dataclass `QuoteResult`, agregar `pdf_path` justo después de `screenshot_path`:

```python
@dataclass
class QuoteResult:
    """Result of a Progressive quote attempt."""
    success: bool = False
    step_reached: str = ""
    error: Optional[str] = None
    screenshot_path: Optional[str] = None
    pdf_path: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)   # offline preflight assumptions (logged for traceability)
    # Quote details (when success)
    price: Optional[QuotePrice] = None
```

- [ ] **Step 4: Capturar el PDF en el paso RATES**

En `modules/progressive/quote_flow.py`, en el bloque del Step 7 (RATES), justo DESPUÉS de `result.price = await rates_page.customize_and_capture(fields)` y ANTES del chequeo de `dry_run`, agregar la captura (la página sigue en RATES en ese punto). El bloque queda así:

```python
            # Step 7: RATES (CoveragesRates) - the page with the premium
            result.step_reached = "rates"
            rates_page = CoveragesRatesPage(wizard_page)
            result.price = await rates_page.customize_and_capture(fields)
            result.warnings.extend(rates_page.warnings)

            # Imprimir la página RATES completa (donde se ve el premium) a PDF —
            # es la "impresión" que la Parte 3 adjunta al correo. Se captura ACÁ,
            # antes de proceed_to_final_details() que navega fuera de RATES.
            result.pdf_path = await rates_page.save_page_pdf(
                f"quote_{(result.price.quote_number if result.price else None) or 'unknown'}"
            )

            if self.dry_run:
```

(No toques nada más del bloque dry_run / final_details.)

- [ ] **Step 5: Ignorar `data/quote_pdfs/` en git**

Verificá si ya está cubierto:
Run: `grep -n "quote_pdfs" .gitignore` (si no hay `.gitignore`, créalo).
Si NO aparece, agregá una línea `data/quote_pdfs/` al final de `.gitignore` (usá Edit/Write; no dupliques si ya existe `data/` ignorado por completo — en ese caso saltá este step y anotalo).

- [ ] **Step 6: Correr tests + pyflakes**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/progressive/test_quote_result_pdf_path.py -v`
Expected: PASS (1 passed).

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pyflakes modules/progressive/quote_flow.py`
Expected: sin salida.

- [ ] **Step 7: Commit**

```bash
git add modules/progressive/quote_flow.py tests/progressive/test_quote_result_pdf_path.py .gitignore
git commit -m "feat(progressive): pdf_path en QuoteResult + captura de la pagina RATES a PDF"
```

> **Nota de validación:** el wiring del flujo (que el PDF se genere de verdad en RATES) se valida LIVE corriendo una cotización real de Progressive — no es unit-testeable sin browser. El unit test sólo garantiza la presencia del campo; la primitiva ya está cubierta en Task 1.

---

## Task 3: GEICO — primitiva `save_page_pdf` en BasePage

**Files:**
- Modify: `modules/geico/pages/base_page.py` (add method right AFTER `screenshot`, ~line 381)
- Create: `tests/geico/__init__.py`
- Test: `tests/geico/test_save_page_pdf.py`

- [ ] **Step 1: Crear el paquete de tests GEICO**

Create `tests/geico/__init__.py` con contenido vacío (un solo salto de línea).

- [ ] **Step 2: Escribir el test que falla**

Create `tests/geico/test_save_page_pdf.py`:

```python
import pytest

from modules.geico.pages.base_page import BasePage


class FakePage:
    """Minimal async page double: records pdf()/screenshot() calls."""

    def __init__(self, pdf_raises=False, screenshot_raises=False):
        self.pdf_raises = pdf_raises
        self.screenshot_raises = screenshot_raises
        self.pdf_calls = []
        self.screenshot_calls = []

    async def pdf(self, path=None, print_background=False, **kw):
        self.pdf_calls.append({"path": path, "print_background": print_background})
        if self.pdf_raises:
            raise RuntimeError("PDF generation is only supported for Headless Chromium")

    async def screenshot(self, path=None, full_page=False, **kw):
        self.screenshot_calls.append({"path": path, "full_page": full_page})
        if self.screenshot_raises:
            raise RuntimeError("screenshot boom")


@pytest.mark.asyncio
async def test_geico_save_page_pdf_headless_writes_pdf(tmp_path):
    page = FakePage()
    bp = BasePage(page)
    out = await bp.save_page_pdf("CA123", output_dir=str(tmp_path))
    assert out == str(tmp_path / "geico_quote_CA123.pdf")
    assert page.pdf_calls and page.pdf_calls[0]["print_background"] is True
    assert page.screenshot_calls == []


@pytest.mark.asyncio
async def test_geico_save_page_pdf_falls_back_to_png_when_headed(tmp_path):
    page = FakePage(pdf_raises=True)
    bp = BasePage(page)
    out = await bp.save_page_pdf("CA123", output_dir=str(tmp_path))
    assert out == str(tmp_path / "geico_quote_CA123.png")
    assert page.screenshot_calls and page.screenshot_calls[0]["full_page"] is True


@pytest.mark.asyncio
async def test_geico_save_page_pdf_returns_none_when_both_fail(tmp_path):
    page = FakePage(pdf_raises=True, screenshot_raises=True)
    bp = BasePage(page)
    out = await bp.save_page_pdf("CA123", output_dir=str(tmp_path))
    assert out is None
```

- [ ] **Step 3: Correr y verificar que falla**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/geico/test_save_page_pdf.py -v`
Expected: FAIL con `AttributeError: 'BasePage' object has no attribute 'save_page_pdf'`.

- [ ] **Step 4: Implementar la primitiva**

En `modules/geico/pages/base_page.py`, INMEDIATAMENTE DESPUÉS del método `screenshot` (después de su `return None`, ~línea 381), agregar:

```python
    async def save_page_pdf(
        self, name: str, output_dir: str = "data/quote_pdfs"
    ) -> Optional[str]:
        """Imprime la página ACTUAL a un PDF (la 'impresión' de la página de precio).

        page.pdf() de Chromium funciona solo headless; headed cae a PNG full-page.
        Devuelve el path escrito o None.
        """
        base = Path(output_dir) / f"geico_quote_{name}"
        pdf_path = base.with_suffix(".pdf")
        try:
            base.parent.mkdir(parents=True, exist_ok=True)
            await self.page.pdf(path=str(pdf_path), print_background=True)
            return str(pdf_path)
        except Exception as e:
            print(f"    [GEICO] page.pdf() no disponible ({e}); fallback a PNG")
            png_path = base.with_suffix(".png")
            try:
                await self.page.screenshot(path=str(png_path), full_page=True)
                return str(png_path)
            except Exception as e2:
                print(f"    [GEICO] captura de página de precio falló: {e2}")
                return None
```

`Path` y `Optional` ya están importados en este archivo (los usa `screenshot`). Si pyflakes se queja de que falta `Optional`, confirmá el import existente — `screenshot` ya devuelve `Optional[str]`, así que debería estar.

- [ ] **Step 5: Correr y verificar que pasa**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/geico/test_save_page_pdf.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: pyflakes + commit**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pyflakes modules/geico/pages/base_page.py`
Expected: sin salida.

```bash
git add modules/geico/pages/base_page.py tests/geico/__init__.py tests/geico/test_save_page_pdf.py
git commit -m "feat(geico): primitiva save_page_pdf (page.pdf headless + fallback PNG)"
```

---

## Task 4: GEICO — capturar el render de la página de precio + usarlo como fallback de PrintQuote

GEICO ya baja el PDF oficial vía el endpoint `PrintQuote`, pero es **intermitente** (a veces devuelve JSON, a veces el link no aparece). Capturamos el render full-page de la página de precio (Quote & Coverages) ANTES del Next, y lo usamos como **fallback confiable** cuando `PrintQuote` falla — así el correo SIEMPRE tiene impresión. Cuando `PrintQuote` funciona, sigue ganando (es el proposal oficial, más prolijo).

**Files:**
- Modify: `modules/geico/pages/coverages_page.py` (`capture_and_advance`)
- Modify: `modules/geico/quote_flow.py` (el `except` del bloque PrintQuote)

> **Validación:** este wiring se valida LIVE (requiere el wizard de GEICO con sesión real). No es unit-testeable sin browser; las primitivas ya están testeadas (Task 3). GEICO arranca detrás de `GEICO_QUEUE_ENABLED=false`, así que este cambio no afecta el pipeline activo hasta que se habilite.

- [ ] **Step 1: Capturar el render en `capture_and_advance` (antes del Next)**

En `modules/geico/pages/coverages_page.py`, dentro de `capture_and_advance`, JUSTO ANTES de `await self._click_next()` (la línea actual `await self._click_next()` / `return price, pdf_url`), agregar la captura del render:

```python
        # Imprimir la página Quote & Coverages completa (donde se ve el premium)
        # a PDF — la "impresión" CONFIABLE para el correo, tomada ANTES del Next
        # que navega al Step 7. Independiente del endpoint flaky PrintQuote.
        self.price_pdf_path = await self.save_page_pdf(
            f"{price.quote_number or 'unknown'}"
        )

        await self._click_next()
        return price, pdf_url
```

(`save_page_pdf` es heredada de `BasePage` — Task 3. `self.price_pdf_path` es un atributo nuevo seteado acá; el caller lo lee con `getattr` en el Step 2, así que NO hace falta declararlo en `__init__`.)

- [ ] **Step 2: Usar el render como fallback en `geico/quote_flow.py`**

En `modules/geico/quote_flow.py`, reemplazar SOLO el bloque `except` del download de PrintQuote (líneas actuales 209-211):

```python
            except Exception as e:
                result.warnings.append(f"PDF download failed: {e}")
                print(f"    [GEICO] WARN: PDF download failed: {e}")
```

por:

```python
            except Exception as e:
                # PrintQuote es intermitente (a veces JSON, a veces el link no
                # está). Fallback al render full-page de la página de precio
                # capturado en capture_and_advance — para que el correo SIEMPRE
                # tenga impresión.
                render = getattr(coverages_page, "price_pdf_path", None)
                if render:
                    result.pdf_path = render
                    result.warnings.append(
                        f"PrintQuote no disponible ({e}); se adjunta la impresión "
                        f"de la página de precio."
                    )
                    print(f"    [GEICO] PrintQuote falló; usando render: {render}")
                else:
                    result.warnings.append(f"PDF download failed: {e}")
                    print(f"    [GEICO] WARN: PDF download failed: {e}")
```

(El camino feliz — PrintQuote OK → `result.pdf_path = info["path"]` — queda intacto. No toques las líneas 197-208.)

- [ ] **Step 3: pyflakes**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pyflakes modules/geico/pages/coverages_page.py modules/geico/quote_flow.py`
Expected: sin salida.

- [ ] **Step 4: Smoke de regresión (la suite no debe romperse)**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/geico/ tests/progressive/ -q`
Expected: PASS (los tests nuevos de Parte 2 + los de Progressive existentes; sin regresiones).

- [ ] **Step 5: Commit**

```bash
git add modules/geico/pages/coverages_page.py modules/geico/quote_flow.py
git commit -m "feat(geico): render full-page de la pagina de precio como fallback confiable de PrintQuote"
```

---

## Self-review checklist (correr al final del plan, antes de ejecutar)

- Cobertura del spec (sección "Captura de la impresión"): primitiva `page.pdf()` full-page + fallback PNG ✓ (Tasks 1, 3); `pdf_path` en Progressive QuoteResult ✓ (Task 2); captura en la página de precio de ambos MGAs ✓ (Tasks 2, 4); reemplazo/fallback del flaky PrintQuote de GEICO ✓ (Task 4); PDFs a `data/quote_pdfs/` gitignored ✓ (Task 2).
- Sin placeholders: cada step trae código real + comando + salida esperada.
- Consistencia de tipos: `save_page_pdf(name, ... output_dir)` devuelve `Optional[str]` en ambos MGAs; Progressive usa `*, output_dir` (keyword-only, espeja su `screenshot`), GEICO usa `output_dir` posicional (espeja el suyo). `result.pdf_path` es `Optional[str]` en ambos QuoteResult.

## Notas / decisiones

- **Por qué el render y no solo el proposal oficial:** el pedido del usuario es "imprimir toda la página donde se ve el precio final". `page.pdf()` lo logra 100% confiable y headless-nativo. En GEICO el proposal oficial (PrintQuote) sigue siendo preferido cuando funciona; el render cubre el hueco intermitente.
- **Headed/debug:** `page.pdf()` solo corre headless; el fallback PNG garantiza que aún en modo debug haya un adjunto.
- **No se toca la lógica de precio ni el STOP antes de pago.** Solo se agrega la captura de impresión.
