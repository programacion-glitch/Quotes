# Progressive BasePage Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reescribir `modules/progressive/pages/base_page.py` como hub de primitivas ExtJS-safe obligatorias y migrar cada page object para que ninguna interacción con Progressive vuelva a usar `page.fill/click/select_option` directos. Resultado: M&D sigue cotizando + RYD cotiza por primera vez + bugs ExtJS dejan de multiplicarse.

**Architecture:** BasePage expone 5 familias de primitivas (localización, interacción safe, esperas dinámicas, estado de página, diagnóstico). Cada page declara REQUIRED/CONDITIONAL/OPTIONAL fields y delega el cómo a BasePage. Migración por fases atómicas con verificación live entre cada una. Tests unitarios con `unittest.mock.AsyncMock` para mockear `playwright.async_api.Page`.

**Tech Stack:** Python 3.x async/await, Playwright 1.44+, pytest, pytest-asyncio, unittest.mock.AsyncMock.

**Spec base:** [`docs/superpowers/specs/2026-06-02-progressive-basepage-hardening-design.md`](../specs/2026-06-02-progressive-basepage-hardening-design.md)

---

## File Structure

### Files to create

| Path | Responsabilidad |
|---|---|
| `modules/progressive/pages/_exceptions.py` | `ExtJSInteractionError` + subclases (`FillVerifyError`, `RadioStuckError`, `ContinueStuckError`, `ComboSelectError`, `FieldNotFoundError`) con atributos `screenshot_path`, `debug_context`, `primitive`, `field`, `attempts` |
| `modules/progressive/pages/_interactions.py` | **NO se crea en este plan.** El spec lo mencionaba; al implementar las primitivas, el JS dispatch quedó inline en `safe_click_continue` (~15 líneas, no justifica un archivo). Si en el futuro se factoriza, vivirá aquí. |
| `tests/progressive/__init__.py` | marker vacío |
| `tests/progressive/conftest.py` | fixtures `mock_page`, `mock_locator` con `AsyncMock` |
| `tests/progressive/test_base_page_primitives.py` | unit tests de cada primitiva |
| `tests/progressive/test_more_business_field_absence.py` | test específico bug RYD ELD |
| `tools/capture_baseline_metrics.py` | script para fase 0 |
| `docs/superpowers/baselines/2026-06-02-progressive-baseline.md` | métricas capturadas + screenshots referenciados |

### Files to modify

| Path | Cambio |
|---|---|
| `modules/progressive/pages/base_page.py` | Agregar primitivas; marcar viejos `DEPRECATED`; fase 7 borra viejos |
| `modules/progressive/pages/more_business_page.py` | Migrar a primitivas + `field_exists` para ELD |
| `modules/progressive/pages/login_page.py` | Migrar |
| `modules/progressive/pages/home_page.py` | Migrar |
| `modules/progressive/pages/final_details_page.py` | Migrar |
| `modules/progressive/pages/drivers_page.py` | Migrar (3 clases) |
| `modules/progressive/pages/coverages_rates_page.py` | Migrar + Continue robusto |
| `modules/progressive/pages/vehicles_page.py` | Migrar (3 clases) |
| `modules/progressive/pages/business_info_page.py` | Migrar (el último, mayor) |
| `modules/progressive/quote_flow.py` | Propagar skip-warnings de pages a `QuoteResult.warnings` (mínimo) |
| `requirements.txt` | Agregar `pytest>=7.0` y `pytest-asyncio>=0.21` |
| `CLAUDE.md` | Actualizar sección "Reglas para Progressive": referenciar primitivas |
| `docs/AGENTS_CONTEXT.md` | Actualizar arquitectura |

---

## Phase 0: Baseline Capture

### Task 0.1: Asegurar pytest + pytest-asyncio instalados

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Agregar pytest a requirements**

Modificar `requirements.txt` agregando al final:

```
# Testing
pytest>=7.0
pytest-asyncio>=0.21
```

- [ ] **Step 2: Instalar**

Run: `pip install pytest>=7.0 pytest-asyncio>=0.21`
Expected: `Successfully installed pytest-... pytest-asyncio-...`

- [ ] **Step 3: Verificar pytest funciona con los tests existentes**

Run: `python -m pytest tests/test_rule_engine.py -v`
Expected: tests pasan (todos o la mayoría — anotar fallos si los hay)

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "chore: pin pytest and pytest-asyncio for progressive primitives tests"
```

---

### Task 0.2: Capturar métricas baseline pre-refactor

**Files:**
- Create: `tools/capture_baseline_metrics.py`
- Create: `docs/superpowers/baselines/2026-06-02-progressive-baseline.md`

- [ ] **Step 1: Crear script de captura de métricas**

Crear `tools/capture_baseline_metrics.py`:

```python
"""Captura métricas pre-refactor del módulo Progressive.

Cuenta wait_for_timeout sin justificar, _click_continue locales, y tamaños
de cada page. Output va a stdout en formato Markdown listo para pegar
en docs/superpowers/baselines/.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGES_DIR = ROOT / "modules" / "progressive" / "pages"

WAIT_RE = re.compile(r"wait_for_timeout\s*\(\s*(\d+)")
CONTINUE_RE = re.compile(r"def\s+_click_continue\s*\(")


def count_unjustified_waits(text: str) -> int:
    """Cuenta wait_for_timeout(N) cuyas líneas previas NO contienen comentario."""
    lines = text.splitlines()
    count = 0
    for i, line in enumerate(lines):
        if WAIT_RE.search(line):
            prev = lines[i - 1].strip() if i > 0 else ""
            if not prev.startswith("#"):
                count += 1
    return count


def main() -> None:
    print("# Progressive Baseline Metrics — 2026-06-02\n")
    print("| File | Lines | wait_for_timeout (unjustified) | _click_continue locales |")
    print("|---|---|---|---|")

    total_waits, total_continues, total_lines = 0, 0, 0
    for f in sorted(PAGES_DIR.glob("*.py")):
        if f.name.startswith("__") or f.name.startswith("_"):
            continue
        text = f.read_text(encoding="utf-8")
        lines = len(text.splitlines())
        waits = count_unjustified_waits(text)
        continues = len(CONTINUE_RE.findall(text))
        total_lines += lines
        total_waits += waits
        total_continues += continues
        print(f"| `{f.name}` | {lines} | {waits} | {continues} |")

    print(f"| **TOTAL** | **{total_lines}** | **{total_waits}** | **{total_continues}** |")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Correr el script y guardar output**

Run (Windows PowerShell):
```powershell
python tools\capture_baseline_metrics.py > docs\superpowers\baselines\2026-06-02-progressive-baseline.md
```
Expected: archivo creado con tabla rellena. Si la carpeta `baselines/` no existe, créala antes con `New-Item -ItemType Directory docs\superpowers\baselines -Force`.

- [ ] **Step 3: Anexar al baseline tiempos live (opcional si M&D y RYD se pueden correr)**

Si tienes acceso a correr M&D y RYD live, agrega al final del archivo:

```markdown

## Tiempos end-to-end live (pre-refactor)

- M&D CUSTOM FREIGHT LLC: <segundos hasta capturar precio>
- RYD LLC: <segundos hasta el paso donde falla (more_business._answer_eld_required)>
```

Si no, escribe `<no capturado>` y sigue.

- [ ] **Step 4: Commit baseline**

```bash
git add tools/capture_baseline_metrics.py docs/superpowers/baselines/2026-06-02-progressive-baseline.md
git commit -m "chore: capture progressive baseline metrics pre-refactor"
```

---

### Task 0.3: Verificar simulador pasa pre-refactor

**Files:** ninguno modificado

- [ ] **Step 1: Correr simulador y capturar conteo de acciones**

Run:
```powershell
$env:PYTHONIOENCODING="utf-8"
python tests\simulate_progressive.py
```
Expected: simulador termina con éxito y reporta número de acciones (anotar — debería ser ~83 según memoria).

- [ ] **Step 2: Anotar conteo en el baseline**

Editar `docs/superpowers/baselines/2026-06-02-progressive-baseline.md` agregando:

```markdown

## Simulator baseline

- Acciones trazadas: <número>
- Status: OK
```

- [ ] **Step 3: Commit nota**

```bash
git add docs/superpowers/baselines/2026-06-02-progressive-baseline.md
git commit -m "chore: record simulator action count in baseline"
```

---

## Phase 1: Infrastructure + Primitives (TDD)

### Task 1.1: Crear test infrastructure

**Files:**
- Create: `tests/progressive/__init__.py`
- Create: `tests/progressive/conftest.py`

- [ ] **Step 1: Crear marker `__init__.py`**

Crear `tests/progressive/__init__.py` (archivo vacío).

- [ ] **Step 2: Crear `conftest.py` con fixtures**

Crear `tests/progressive/conftest.py`:

```python
"""Shared fixtures for Progressive primitive tests.

Mocks playwright.async_api.Page and Locator so primitives can be tested
without launching a browser.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_locator() -> AsyncMock:
    """A minimal Playwright Locator double."""
    loc = AsyncMock()
    loc.count = AsyncMock(return_value=1)
    loc.is_visible = AsyncMock(return_value=True)
    loc.is_checked = AsyncMock(return_value=False)
    loc.input_value = AsyncMock(return_value="")
    loc.click = AsyncMock()
    loc.fill = AsyncMock()
    loc.check = AsyncMock()
    loc.scroll_into_view_if_needed = AsyncMock()
    loc.wait_for = AsyncMock()
    loc.first = loc
    loc.last = loc
    loc.nth = MagicMock(return_value=loc)
    loc.locator = MagicMock(return_value=loc)
    loc.get_by_role = MagicMock(return_value=loc)
    return loc


@pytest.fixture
def mock_page(mock_locator: AsyncMock) -> AsyncMock:
    """A minimal Playwright Page double that returns mock_locator everywhere."""
    page = AsyncMock()
    page.url = "https://progressive.example/?pageName=Unknown"
    page.title = AsyncMock(return_value="")
    page.locator = MagicMock(return_value=mock_locator)
    page.get_by_role = MagicMock(return_value=mock_locator)
    page.get_by_text = MagicMock(return_value=mock_locator)
    page.get_by_label = MagicMock(return_value=mock_locator)
    page.get_by_placeholder = MagicMock(return_value=mock_locator)
    page.evaluate = AsyncMock(return_value=None)
    page.wait_for_function = AsyncMock(return_value=None)
    page.wait_for_load_state = AsyncMock(return_value=None)
    page.wait_for_timeout = AsyncMock(return_value=None)
    page.keyboard = MagicMock()
    page.keyboard.press = AsyncMock()
    page.screenshot = AsyncMock(return_value=None)
    return page
```

- [ ] **Step 3: Crear pytest.ini o pyproject ajuste**

Si no existe `pytest.ini` ni configuración de pytest, crear `pytest.ini` en la raíz:

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

Si existe `pyproject.toml` con sección `[tool.pytest.ini_options]`, agregar `asyncio_mode = "auto"` ahí. Verificar primero con `Get-Content pyproject.toml -ErrorAction SilentlyContinue` o `cat pytest.ini`.

- [ ] **Step 4: Verificar pytest descubre el módulo nuevo**

Run: `python -m pytest tests/progressive/ -v --collect-only`
Expected: `collected 0 items` (no tests aún) y SIN errores de importación.

- [ ] **Step 5: Commit infra**

```bash
git add tests/progressive/__init__.py tests/progressive/conftest.py pytest.ini
git commit -m "test: scaffold progressive primitives test infrastructure"
```

---

### Task 1.2: Crear `_exceptions.py`

**Files:**
- Create: `modules/progressive/pages/_exceptions.py`
- Create: `tests/progressive/test_exceptions.py`

- [ ] **Step 1: Escribir test de exceptions**

Crear `tests/progressive/test_exceptions.py`:

```python
"""Verify exception classes carry required diagnostic attributes."""

from pathlib import Path

import pytest

from modules.progressive.pages._exceptions import (
    ContinueStuckError,
    ExtJSInteractionError,
    FieldNotFoundError,
    FillVerifyError,
    RadioStuckError,
    ComboSelectError,
)


def test_extjs_interaction_error_carries_all_attrs():
    exc = ExtJSInteractionError(
        message="primitive failed",
        primitive="safe_fill",
        field="business_name",
        attempts=3,
        screenshot_path=Path("logs/x.png"),
        debug_context={"url": "u", "pageName": "P"},
    )
    assert exc.primitive == "safe_fill"
    assert exc.field == "business_name"
    assert exc.attempts == 3
    assert exc.screenshot_path == Path("logs/x.png")
    assert exc.debug_context["pageName"] == "P"
    assert "primitive failed" in str(exc)


def test_fill_verify_error_is_extjs_interaction_error():
    exc = FillVerifyError(message="m", primitive="safe_fill", field="x", attempts=2)
    assert isinstance(exc, ExtJSInteractionError)


def test_radio_stuck_error_is_extjs_interaction_error():
    exc = RadioStuckError(message="m", primitive="safe_radio", field="x", attempts=3)
    assert isinstance(exc, ExtJSInteractionError)


def test_continue_stuck_error_is_extjs_interaction_error():
    exc = ContinueStuckError(message="m", primitive="safe_click_continue", field=None, attempts=3)
    assert isinstance(exc, ExtJSInteractionError)


def test_combo_select_error_is_extjs_interaction_error():
    exc = ComboSelectError(message="m", primitive="safe_select_combo", field="x", attempts=2)
    assert isinstance(exc, ExtJSInteractionError)


def test_field_not_found_error_is_extjs_interaction_error():
    exc = FieldNotFoundError(message="m", primitive="find_radiogroup", field="ELD", attempts=1)
    assert isinstance(exc, ExtJSInteractionError)


def test_optional_attrs_default_to_none():
    exc = ExtJSInteractionError(message="m", primitive="p", field=None, attempts=1)
    assert exc.screenshot_path is None
    assert exc.debug_context == {}
```

- [ ] **Step 2: Correr para verificar que falla por importación**

Run: `python -m pytest tests/progressive/test_exceptions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'modules.progressive.pages._exceptions'`

- [ ] **Step 3: Implementar `_exceptions.py`**

Crear `modules/progressive/pages/_exceptions.py`:

```python
"""Structured exceptions for ExtJS-safe primitives in BasePage.

Every primitive that fails after retries raises a subclass of
ExtJSInteractionError carrying the screenshot path and debug context
captured at the moment of failure.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


class ExtJSInteractionError(Exception):
    """Base for any failure inside a BasePage primitive after retries."""

    def __init__(
        self,
        message: str,
        *,
        primitive: str,
        field: Optional[str],
        attempts: int,
        screenshot_path: Optional[Path] = None,
        debug_context: Optional[dict] = None,
    ) -> None:
        super().__init__(message)
        self.primitive = primitive
        self.field = field
        self.attempts = attempts
        self.screenshot_path = screenshot_path
        self.debug_context = debug_context or {}


class FillVerifyError(ExtJSInteractionError):
    """safe_fill could not verify input_value() after retries."""


class RadioStuckError(ExtJSInteractionError):
    """safe_radio could not make a radio is_checked() after retries."""


class ContinueStuckError(ExtJSInteractionError):
    """safe_click_continue did not advance the URL after retries."""


class ComboSelectError(ExtJSInteractionError):
    """safe_select_combo could not commit the desired option."""


class FieldNotFoundError(ExtJSInteractionError):
    """find_* primitive could not locate a REQUIRED field within timeout."""
```

- [ ] **Step 4: Correr tests, verificar verde**

Run: `python -m pytest tests/progressive/test_exceptions.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add modules/progressive/pages/_exceptions.py tests/progressive/test_exceptions.py
git commit -m "feat(progressive): add structured exceptions for ExtJS-safe primitives"
```

---

### Task 1.3: Crear esqueleto `BasePage` refactorizada con utilities (screenshot + dump_debug_context)

**Files:**
- Modify: `modules/progressive/pages/base_page.py`
- Create: `tests/progressive/test_base_page_primitives.py`

- [ ] **Step 1: Escribir tests para utilities**

Crear `tests/progressive/test_base_page_primitives.py`:

```python
"""Unit tests for BasePage primitives.

Uses AsyncMock fixtures from conftest.py — no real browser.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.progressive.pages.base_page import BasePage


@pytest.mark.asyncio
async def test_current_page_token_extracts_pagename(mock_page):
    mock_page.url = "https://x.progressive.com/agent/?pageName=MoreAboutBusiness&wGuid=abc"
    bp = BasePage(mock_page)
    assert await bp.current_page_token() == "MoreAboutBusiness"


@pytest.mark.asyncio
async def test_current_page_token_returns_empty_when_no_pagename(mock_page):
    mock_page.url = "https://x.progressive.com/agent/"
    bp = BasePage(mock_page)
    assert await bp.current_page_token() == ""


@pytest.mark.asyncio
async def test_remove_overlays_calls_evaluate(mock_page):
    bp = BasePage(mock_page)
    await bp.remove_overlays()
    mock_page.evaluate.assert_awaited()


@pytest.mark.asyncio
async def test_blur_active_element_calls_evaluate(mock_page):
    bp = BasePage(mock_page)
    await bp.blur_active_element()
    mock_page.evaluate.assert_awaited()
```

- [ ] **Step 2: Correr — falla porque BasePage aún no tiene esos métodos**

Run: `python -m pytest tests/progressive/test_base_page_primitives.py::test_current_page_token_extracts_pagename -v`
Expected: FAIL — `AttributeError: 'BasePage' object has no attribute 'current_page_token'`

- [ ] **Step 3: Implementar utilities en `base_page.py`**

Reemplazar el contenido de `modules/progressive/pages/base_page.py` con:

```python
"""Base Page Object for Progressive portal.

Hub of ExtJS-safe primitives. Every page object MUST use these primitives
instead of calling page.fill/click/select_option directly.

5 families of primitives:
  A. Localización tolerante (find_by_label_text, find_radiogroup, ...)
  B. Interacción ExtJS-safe (safe_fill, safe_radio, safe_click_continue, ...)
  C. Esperas dinámicas (wait_for_extjs_idle, wait_for_field_revealed_by, ...)
  D. Estado de página (remove_overlays, blur_active_element, current_page_token)
  E. Diagnóstico (screenshot, dump_debug_context)

DEPRECATED helpers (by_label, fill_by_label, ...) are kept until phase 7
to avoid breaking pages not yet migrated. New code MUST NOT use them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse, parse_qs

from playwright.async_api import Locator, Page


class BasePage:
    """Hub of ExtJS-safe primitives for all Progressive page objects."""

    def __init__(self, page: Page):
        self.page = page

    # ============================================================
    # Familia D — Estado de página
    # ============================================================

    async def remove_overlays(self) -> None:
        """Remove invisible modal overlays that intercept clicks."""
        await self.page.evaluate(
            """() => {
                document.querySelectorAll(
                    '.modalOverlay, .modal-backdrop, [class*="overlay"]'
                ).forEach(el => el.remove());
            }"""
        )

    async def blur_active_element(self) -> None:
        """Blur the active element so ExtJS commits pending state."""
        await self.page.evaluate(
            """() => {
                if (document.activeElement && document.activeElement.blur) {
                    document.activeElement.blur();
                }
            }"""
        )

    async def current_page_token(self) -> str:
        """Extract pageName query param from the current URL."""
        parsed = urlparse(self.page.url)
        qs = parse_qs(parsed.query)
        return qs.get("pageName", [""])[0]

    # ============================================================
    # Familia E — Diagnóstico
    # ============================================================

    async def screenshot(self, name: str, *, output_dir: str = "logs") -> Optional[Path]:
        """Take a screenshot for error reporting. Returns path or None."""
        try:
            path = Path(output_dir) / f"progressive_{name}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            await self.page.screenshot(path=str(path), full_page=True)
            return path
        except Exception as e:
            print(f"    [Progressive] screenshot failed: {e}")
            return None

    async def dump_debug_context(self, label: str) -> dict[str, Any]:
        """Collect URL, pageName, title, visible button labels for error context."""
        try:
            visible_buttons = await self.page.evaluate(
                """() => Array.from(document.querySelectorAll(
                    'button, a.x-btn, .x-btn-inner'
                )).filter(el => el.offsetParent !== null)
                  .map(el => (el.innerText || '').trim())
                  .filter(t => t.length > 0)
                  .slice(0, 20)"""
            )
        except Exception:
            visible_buttons = []
        return {
            "label": label,
            "url": self.page.url,
            "pageName": await self.current_page_token(),
            "visible_buttons": visible_buttons,
        }

    # ============================================================
    # DEPRECATED helpers — kept until phase 7 cleanup
    # ============================================================

    def by_label(self, label_text: str) -> Locator:
        """DEPRECATED — use find_by_label_text. Kept for un-migrated pages."""
        return self.page.locator(
            f"label:has-text('{label_text}')"
        ).locator("xpath=following::input[1] | following::select[1] | following::textarea[1]")

    async def fill_by_label(self, label_text: str, value: str) -> None:
        """DEPRECATED — use safe_fill. Kept for un-migrated pages."""
        loc = self.by_label(label_text)
        await loc.wait_for(state="visible", timeout=10_000)
        await loc.fill(value)

    async def click_by_text(self, text: str, tag: str = "*") -> None:
        """DEPRECATED — use safe_click_continue or direct get_by_text. Kept."""
        await self.remove_overlays()
        loc = self.page.locator(f"{tag}:has-text('{text}')").first
        await loc.click(timeout=10_000)

    async def click_button(self, text: str) -> None:
        """DEPRECATED — use safe_click_continue. Kept for un-migrated pages."""
        await self.remove_overlays()
        await self.page.get_by_role("button", name=text).click(timeout=10_000)

    async def select_by_label(self, label_text: str, value: str) -> None:
        """DEPRECATED — use safe_select_combo. Kept for un-migrated pages."""
        loc = self.by_label(label_text)
        await loc.wait_for(state="visible", timeout=10_000)
        await loc.select_option(value=value, timeout=5_000)

    async def select_option_by_text(self, label_text: str, option_text: str) -> None:
        """DEPRECATED — use safe_select_combo. Kept for un-migrated pages."""
        loc = self.by_label(label_text)
        await loc.wait_for(state="visible", timeout=10_000)
        await loc.select_option(label=option_text, timeout=5_000)

    async def wait_for_text(self, text: str, timeout: int = 15_000) -> None:
        """DEPRECATED — use wait_for_page. Kept for un-migrated pages."""
        await self.page.get_by_text(text).wait_for(state="visible", timeout=timeout)

    async def wait_for_navigation(self, timeout: int = 30_000) -> None:
        """DEPRECATED. Kept for un-migrated pages."""
        await self.page.wait_for_load_state("networkidle", timeout=timeout)
```

- [ ] **Step 4: Correr tests, verificar verde**

Run: `python -m pytest tests/progressive/test_base_page_primitives.py -v`
Expected: 4 passed.

- [ ] **Step 5: Correr simulador, verificar no romper pages existentes**

Run: `$env:PYTHONIOENCODING="utf-8"; python tests\simulate_progressive.py`
Expected: termina OK con el mismo conteo de acciones que baseline.

- [ ] **Step 6: Commit**

```bash
git add modules/progressive/pages/base_page.py tests/progressive/test_base_page_primitives.py
git commit -m "refactor(progressive): scaffold new BasePage with utilities; mark old helpers DEPRECATED"
```

---

### Task 1.4: Implementar `wait_for_extjs_idle`

**Files:**
- Modify: `modules/progressive/pages/base_page.py`
- Modify: `tests/progressive/test_base_page_primitives.py`

- [ ] **Step 1: Agregar test**

Agregar al final de `tests/progressive/test_base_page_primitives.py`:

```python
@pytest.mark.asyncio
async def test_wait_for_extjs_idle_calls_wait_for_function(mock_page):
    bp = BasePage(mock_page)
    await bp.wait_for_extjs_idle()
    mock_page.wait_for_function.assert_awaited_once()
    args, kwargs = mock_page.wait_for_function.call_args
    js = args[0] if args else kwargs.get("expression", "")
    assert "Ext" in js
    assert "x-mask" in js
    assert "readyState" in js


@pytest.mark.asyncio
async def test_wait_for_extjs_idle_respects_timeout_ms(mock_page):
    bp = BasePage(mock_page)
    await bp.wait_for_extjs_idle(timeout_ms=5000)
    args, kwargs = mock_page.wait_for_function.call_args
    assert kwargs.get("timeout") == 5000
```

- [ ] **Step 2: Correr — falla por método inexistente**

Run: `python -m pytest tests/progressive/test_base_page_primitives.py::test_wait_for_extjs_idle_calls_wait_for_function -v`
Expected: FAIL `AttributeError: 'BasePage' object has no attribute 'wait_for_extjs_idle'`

- [ ] **Step 3: Implementar**

Agregar al final de la sección "Familia D" en `base_page.py` (antes de DEPRECATED), insertar una sección nueva:

```python
    # ============================================================
    # Familia C — Esperas dinámicas
    # ============================================================

    async def wait_for_extjs_idle(self, *, timeout_ms: int = 10_000) -> None:
        """Wait until ExtJS finishes: no pending Ajax, no visible masks, document ready."""
        await self.page.wait_for_function(
            """() => {
                const extQuiet = typeof Ext === 'undefined' ||
                                 !Ext.Ajax || !Ext.Ajax.isLoading();
                const noMask = !document.querySelector('.x-mask:not(.x-mask-fixed)');
                const ready = document.readyState === 'complete';
                return extQuiet && noMask && ready;
            }""",
            timeout=timeout_ms,
        )
```

- [ ] **Step 4: Correr tests, verificar verde**

Run: `python -m pytest tests/progressive/test_base_page_primitives.py -v -k extjs_idle`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add modules/progressive/pages/base_page.py tests/progressive/test_base_page_primitives.py
git commit -m "feat(progressive): add wait_for_extjs_idle primitive"
```

---

### Task 1.5: Implementar localizadores `find_by_label_text` y `find_by_placeholder`

**Files:**
- Modify: `modules/progressive/pages/base_page.py`
- Modify: `tests/progressive/test_base_page_primitives.py`

- [ ] **Step 1: Agregar tests**

Agregar al final de `tests/progressive/test_base_page_primitives.py`:

```python
@pytest.mark.asyncio
async def test_find_by_label_text_uses_xpath_following_input(mock_page, mock_locator):
    bp = BasePage(mock_page)
    result = await bp.find_by_label_text("Driver's License Number")
    mock_page.get_by_text.assert_called_once()
    args, kwargs = mock_page.get_by_text.call_args
    assert args[0] == "Driver's License Number"
    assert kwargs.get("exact") is True
    mock_locator.locator.assert_called_with(
        "xpath=following::input[@type='text'][1]"
    )
    assert result is mock_locator


@pytest.mark.asyncio
async def test_find_by_placeholder_uses_get_by_placeholder(mock_page, mock_locator):
    bp = BasePage(mock_page)
    result = await bp.find_by_placeholder("Business Name")
    mock_page.get_by_placeholder.assert_called_once_with("Business Name")
    assert result is mock_locator
```

- [ ] **Step 2: Correr — falla**

Run: `python -m pytest tests/progressive/test_base_page_primitives.py -v -k "find_by_label_text or find_by_placeholder"`
Expected: FAIL — `AttributeError`.

- [ ] **Step 3: Implementar**

Agregar al inicio de la sección Familia D (o crear sección Familia A arriba de D) — recomendado crear sección nueva A en orden alfabético arriba de C. Insertar antes de la sección Familia C:

```python
    # ============================================================
    # Familia A — Localización tolerante
    # ============================================================

    async def find_by_label_text(
        self, label: str, *, kind: str = "input", timeout_ms: int = 5_000
    ) -> Locator:
        """Find an input by XPath traversal from its visible label text.

        Used for fields where Progressive's ExtJS overlay hides the
        placeholder attribute, so get_by_placeholder fails.
        """
        label_loc = self.page.get_by_text(label, exact=True)
        xpath_target = {
            "input": "xpath=following::input[@type='text'][1]",
            "textarea": "xpath=following::textarea[1]",
        }.get(kind, "xpath=following::input[@type='text'][1]")
        return label_loc.locator(xpath_target)

    async def find_by_placeholder(
        self, placeholder: str, *, timeout_ms: int = 5_000
    ) -> Locator:
        """Find an input by its real placeholder attribute (when ExtJS exposes it)."""
        return self.page.get_by_placeholder(placeholder)
```

- [ ] **Step 4: Correr tests verde**

Run: `python -m pytest tests/progressive/test_base_page_primitives.py -v -k "find_by_label_text or find_by_placeholder"`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add modules/progressive/pages/base_page.py tests/progressive/test_base_page_primitives.py
git commit -m "feat(progressive): add find_by_label_text and find_by_placeholder primitives"
```

---

### Task 1.6: Implementar `find_radiogroup`, `find_combo`, `field_exists`

**Files:**
- Modify: `modules/progressive/pages/base_page.py`
- Modify: `tests/progressive/test_base_page_primitives.py`

- [ ] **Step 1: Agregar tests**

Agregar al final de `tests/progressive/test_base_page_primitives.py`:

```python
@pytest.mark.asyncio
async def test_find_radiogroup_uses_get_by_role(mock_page, mock_locator):
    bp = BasePage(mock_page)
    result = await bp.find_radiogroup("Is the customer currently insured?")
    mock_page.get_by_role.assert_called_with(
        "radiogroup",
        name="Is the customer currently insured?",
        exact=False,
    )
    assert result is mock_locator


@pytest.mark.asyncio
async def test_find_combo_uses_get_by_role_combobox(mock_page, mock_locator):
    bp = BasePage(mock_page)
    result = await bp.find_combo("Year")
    mock_page.get_by_role.assert_called_with(
        "combobox",
        name="Year",
        exact=False,
    )
    assert result is mock_locator


@pytest.mark.asyncio
async def test_field_exists_true_when_visible(mock_page, mock_locator):
    mock_locator.count = AsyncMock(return_value=1)
    mock_locator.is_visible = AsyncMock(return_value=True)
    bp = BasePage(mock_page)
    assert await bp.field_exists(mock_locator, wait_ms=100) is True


@pytest.mark.asyncio
async def test_field_exists_false_when_count_zero(mock_page, mock_locator):
    mock_locator.count = AsyncMock(return_value=0)
    bp = BasePage(mock_page)
    assert await bp.field_exists(mock_locator, wait_ms=100) is False


@pytest.mark.asyncio
async def test_field_exists_false_when_not_visible(mock_page, mock_locator):
    mock_locator.count = AsyncMock(return_value=1)
    mock_locator.is_visible = AsyncMock(return_value=False)
    bp = BasePage(mock_page)
    assert await bp.field_exists(mock_locator, wait_ms=100) is False
```

- [ ] **Step 2: Correr — falla**

Run: `python -m pytest tests/progressive/test_base_page_primitives.py -v -k "radiogroup or find_combo or field_exists"`
Expected: FAIL.

- [ ] **Step 3: Implementar**

Agregar a la sección Familia A en `base_page.py`, después de `find_by_placeholder`:

```python
    async def find_radiogroup(
        self, name: str, *, exact: bool = False, timeout_ms: int = 5_000
    ) -> Locator:
        """Find a radiogroup by its accessible name (partial match by default)."""
        return self.page.get_by_role("radiogroup", name=name, exact=exact)

    async def find_combo(
        self, name: str, *, exact: bool = False, timeout_ms: int = 5_000
    ) -> Locator:
        """Find an ExtJS combobox by its accessible name."""
        return self.page.get_by_role("combobox", name=name, exact=exact)

    async def field_exists(self, locator: Locator, *, wait_ms: int = 2_000) -> bool:
        """Short-poll: True if locator has count > 0 AND is visible within wait_ms.

        Used for CONDITIONAL fields that may not render for some
        commodity types (e.g. ELD radio absent for Beverage Distributor).
        """
        try:
            await locator.wait_for(state="visible", timeout=wait_ms)
            return (await locator.count()) > 0 and await locator.is_visible()
        except Exception:
            try:
                if (await locator.count()) > 0 and await locator.is_visible():
                    return True
            except Exception:
                pass
            return False
```

- [ ] **Step 4: Correr tests verde**

Run: `python -m pytest tests/progressive/test_base_page_primitives.py -v -k "radiogroup or find_combo or field_exists"`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add modules/progressive/pages/base_page.py tests/progressive/test_base_page_primitives.py
git commit -m "feat(progressive): add find_radiogroup, find_combo, field_exists primitives"
```

---

### Task 1.7: Implementar `safe_fill`

**Files:**
- Modify: `modules/progressive/pages/base_page.py`
- Modify: `tests/progressive/test_base_page_primitives.py`

- [ ] **Step 1: Agregar tests**

Agregar al final de `tests/progressive/test_base_page_primitives.py`:

```python
@pytest.mark.asyncio
async def test_safe_fill_clicks_fills_tabs_and_verifies(mock_page, mock_locator):
    mock_locator.input_value = AsyncMock(return_value="hello")
    bp = BasePage(mock_page)
    await bp.safe_fill(mock_locator, "hello")
    mock_locator.click.assert_awaited()
    mock_locator.fill.assert_awaited_with("hello")
    mock_page.keyboard.press.assert_awaited_with("Tab")
    mock_locator.input_value.assert_awaited()


@pytest.mark.asyncio
async def test_safe_fill_retries_when_value_mismatch(mock_page, mock_locator):
    mock_locator.input_value = AsyncMock(side_effect=["wrong", "wrong", "hello"])
    bp = BasePage(mock_page)
    await bp.safe_fill(mock_locator, "hello", retries=2)
    assert mock_locator.fill.await_count == 3


@pytest.mark.asyncio
async def test_safe_fill_raises_FillVerifyError_after_retries(mock_page, mock_locator):
    from modules.progressive.pages._exceptions import FillVerifyError
    mock_locator.input_value = AsyncMock(return_value="wrong")
    bp = BasePage(mock_page)
    with pytest.raises(FillVerifyError) as exc_info:
        await bp.safe_fill(mock_locator, "hello", retries=2)
    assert exc_info.value.primitive == "safe_fill"
    assert exc_info.value.attempts == 3


@pytest.mark.asyncio
async def test_safe_fill_skips_verify_when_verify_false(mock_page, mock_locator):
    mock_locator.input_value = AsyncMock(return_value="wrong")
    bp = BasePage(mock_page)
    await bp.safe_fill(mock_locator, "hello", verify=False)
    mock_locator.input_value.assert_not_awaited()
```

- [ ] **Step 2: Correr — falla**

Run: `python -m pytest tests/progressive/test_base_page_primitives.py -v -k safe_fill`
Expected: FAIL.

- [ ] **Step 3: Implementar**

Agregar a `base_page.py` una nueva sección Familia B (entre A y C), insertarla después de `field_exists`:

```python
    # ============================================================
    # Familia B — Interacción ExtJS-safe (obligatorias)
    # ============================================================

    async def safe_fill(
        self,
        locator: Locator,
        value: str,
        *,
        verify: bool = True,
        retries: int = 2,
    ) -> None:
        """Click → fill → Tab → verify input_value(). Retry on mismatch."""
        from modules.progressive.pages._exceptions import FillVerifyError

        attempts = 0
        last_seen = ""
        for attempt in range(retries + 1):
            attempts = attempt + 1
            try:
                await locator.click(timeout=5_000)
                await locator.fill(value)
                await self.page.keyboard.press("Tab")
            except Exception as e:
                if attempt == retries:
                    debug = await self.dump_debug_context("safe_fill_action")
                    screenshot = await self.screenshot(f"safe_fill_action_failed_{attempts}")
                    raise FillVerifyError(
                        f"safe_fill action failed after {attempts} attempts: {e}",
                        primitive="safe_fill",
                        field=value,
                        attempts=attempts,
                        screenshot_path=screenshot,
                        debug_context=debug,
                    ) from e
                await self.page.wait_for_timeout(500 * (attempt + 1))
                continue

            if not verify:
                return

            try:
                last_seen = (await locator.input_value()) or ""
            except Exception:
                last_seen = ""

            if last_seen == value:
                return

            if attempt < retries:
                await self.page.wait_for_timeout(500 * (attempt + 1))

        debug = await self.dump_debug_context("safe_fill_verify")
        screenshot = await self.screenshot(f"safe_fill_verify_failed_{attempts}")
        raise FillVerifyError(
            f"safe_fill expected '{value}' got '{last_seen}' after {attempts} attempts",
            primitive="safe_fill",
            field=value,
            attempts=attempts,
            screenshot_path=screenshot,
            debug_context=debug,
        )
```

- [ ] **Step 4: Correr tests verde**

Run: `python -m pytest tests/progressive/test_base_page_primitives.py -v -k safe_fill`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add modules/progressive/pages/base_page.py tests/progressive/test_base_page_primitives.py
git commit -m "feat(progressive): add safe_fill primitive with verify+retry"
```

---

### Task 1.8: Implementar `safe_radio`

**Files:**
- Modify: `modules/progressive/pages/base_page.py`
- Modify: `tests/progressive/test_base_page_primitives.py`

- [ ] **Step 1: Agregar tests**

Agregar al final de `tests/progressive/test_base_page_primitives.py`:

```python
@pytest.mark.asyncio
async def test_safe_radio_clicks_option_and_verifies(mock_page, mock_locator):
    mock_radio = AsyncMock()
    mock_radio.click = AsyncMock()
    mock_radio.check = AsyncMock()
    mock_radio.is_checked = AsyncMock(return_value=True)
    mock_locator.get_by_role = MagicMock(return_value=mock_radio)
    bp = BasePage(mock_page)
    await bp.safe_radio(mock_locator, "Yes")
    mock_locator.get_by_role.assert_called_with("radio", name="Yes", exact=True)
    mock_radio.click.assert_awaited()


@pytest.mark.asyncio
async def test_safe_radio_retries_with_force_then_check(mock_page, mock_locator):
    mock_radio = AsyncMock()
    mock_radio.click = AsyncMock()
    mock_radio.check = AsyncMock()
    mock_radio.is_checked = AsyncMock(side_effect=[False, False, True])
    mock_locator.get_by_role = MagicMock(return_value=mock_radio)
    bp = BasePage(mock_page)
    await bp.safe_radio(mock_locator, "Yes", retries=3)
    assert mock_radio.click.await_count >= 2


@pytest.mark.asyncio
async def test_safe_radio_raises_RadioStuckError_after_retries(mock_page, mock_locator):
    from modules.progressive.pages._exceptions import RadioStuckError
    mock_radio = AsyncMock()
    mock_radio.click = AsyncMock()
    mock_radio.check = AsyncMock()
    mock_radio.is_checked = AsyncMock(return_value=False)
    mock_locator.get_by_role = MagicMock(return_value=mock_radio)
    bp = BasePage(mock_page)
    with pytest.raises(RadioStuckError) as exc_info:
        await bp.safe_radio(mock_locator, "Yes", retries=2)
    assert exc_info.value.primitive == "safe_radio"
```

- [ ] **Step 2: Correr — falla**

Run: `python -m pytest tests/progressive/test_base_page_primitives.py -v -k safe_radio`
Expected: FAIL.

- [ ] **Step 3: Implementar**

Agregar a Familia B en `base_page.py`, después de `safe_fill`:

```python
    async def safe_radio(
        self,
        group: Locator,
        option: str,
        *,
        retries: int = 3,
    ) -> None:
        """Click radio by visible name within group; verify is_checked. Retry escalating force."""
        from modules.progressive.pages._exceptions import RadioStuckError

        radio = group.get_by_role("radio", name=option, exact=True)
        attempts = 0
        for attempt in range(retries + 1):
            attempts = attempt + 1
            try:
                if attempt == 0:
                    await radio.click(timeout=5_000)
                elif attempt == 1:
                    await radio.click(timeout=5_000, force=True)
                else:
                    await radio.check(force=True, timeout=5_000)
            except Exception:
                pass

            try:
                if await radio.is_checked():
                    return
            except Exception:
                pass

            if attempt < retries:
                await self.page.wait_for_timeout(500 * (attempt + 1))

        debug = await self.dump_debug_context("safe_radio")
        screenshot = await self.screenshot(f"safe_radio_stuck_{option}_{attempts}")
        raise RadioStuckError(
            f"safe_radio could not check '{option}' after {attempts} attempts",
            primitive="safe_radio",
            field=option,
            attempts=attempts,
            screenshot_path=screenshot,
            debug_context=debug,
        )
```

- [ ] **Step 4: Correr tests verde**

Run: `python -m pytest tests/progressive/test_base_page_primitives.py -v -k safe_radio`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add modules/progressive/pages/base_page.py tests/progressive/test_base_page_primitives.py
git commit -m "feat(progressive): add safe_radio primitive with escalating force"
```

---

### Task 1.9: Implementar `safe_checkbox`

**Files:**
- Modify: `modules/progressive/pages/base_page.py`
- Modify: `tests/progressive/test_base_page_primitives.py`

- [ ] **Step 1: Agregar tests**

```python
@pytest.mark.asyncio
async def test_safe_checkbox_checks_when_unchecked(mock_page, mock_locator):
    mock_locator.is_checked = AsyncMock(side_effect=[False, True])
    bp = BasePage(mock_page)
    await bp.safe_checkbox(mock_locator, check=True)
    mock_locator.click.assert_awaited()


@pytest.mark.asyncio
async def test_safe_checkbox_skips_when_already_correct(mock_page, mock_locator):
    mock_locator.is_checked = AsyncMock(return_value=True)
    bp = BasePage(mock_page)
    await bp.safe_checkbox(mock_locator, check=True)
    mock_locator.click.assert_not_awaited()


@pytest.mark.asyncio
async def test_safe_checkbox_unchecks_when_check_false(mock_page, mock_locator):
    mock_locator.is_checked = AsyncMock(side_effect=[True, False])
    bp = BasePage(mock_page)
    await bp.safe_checkbox(mock_locator, check=False)
    mock_locator.click.assert_awaited()
```

- [ ] **Step 2: Correr — falla**

Run: `python -m pytest tests/progressive/test_base_page_primitives.py -v -k safe_checkbox`
Expected: FAIL.

- [ ] **Step 3: Implementar**

Agregar a Familia B en `base_page.py`, después de `safe_radio`:

```python
    async def safe_checkbox(
        self,
        locator: Locator,
        *,
        check: bool = True,
        retries: int = 2,
    ) -> None:
        """Toggle checkbox only if current state differs from desired; verify."""
        from modules.progressive.pages._exceptions import RadioStuckError

        attempts = 0
        for attempt in range(retries + 1):
            attempts = attempt + 1
            try:
                current = await locator.is_checked()
            except Exception:
                current = not check
            if current == check:
                return
            try:
                await locator.click(timeout=5_000, force=(attempt > 0))
            except Exception:
                pass
            try:
                if await locator.is_checked() == check:
                    return
            except Exception:
                pass
            if attempt < retries:
                await self.page.wait_for_timeout(500 * (attempt + 1))

        debug = await self.dump_debug_context("safe_checkbox")
        screenshot = await self.screenshot(f"safe_checkbox_stuck_{attempts}")
        raise RadioStuckError(
            f"safe_checkbox could not set state={check} after {attempts} attempts",
            primitive="safe_checkbox",
            field=None,
            attempts=attempts,
            screenshot_path=screenshot,
            debug_context=debug,
        )
```

- [ ] **Step 4: Correr tests verde**

Run: `python -m pytest tests/progressive/test_base_page_primitives.py -v -k safe_checkbox`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add modules/progressive/pages/base_page.py tests/progressive/test_base_page_primitives.py
git commit -m "feat(progressive): add safe_checkbox primitive"
```

---

### Task 1.10: Implementar `safe_select_combo`

**Files:**
- Modify: `modules/progressive/pages/base_page.py`
- Modify: `tests/progressive/test_base_page_primitives.py`

- [ ] **Step 1: Agregar tests**

```python
@pytest.mark.asyncio
async def test_safe_select_combo_clicks_combo_then_option(mock_page, mock_locator):
    mock_option = AsyncMock()
    mock_option.click = AsyncMock()
    mock_locator.input_value = AsyncMock(return_value="Texas")
    mock_page.get_by_role = MagicMock(side_effect=[mock_locator, mock_option, mock_option])
    bp = BasePage(mock_page)
    await bp.safe_select_combo(mock_locator, "Texas")
    mock_locator.click.assert_awaited()


@pytest.mark.asyncio
async def test_safe_select_combo_raises_ComboSelectError_when_value_not_set(mock_page, mock_locator):
    from modules.progressive.pages._exceptions import ComboSelectError
    mock_option = AsyncMock()
    mock_option.click = AsyncMock()
    mock_locator.input_value = AsyncMock(return_value="")
    mock_page.get_by_role = MagicMock(return_value=mock_option)
    bp = BasePage(mock_page)
    with pytest.raises(ComboSelectError):
        await bp.safe_select_combo(mock_locator, "Texas", retries=1)
```

- [ ] **Step 2: Correr — falla**

Run: `python -m pytest tests/progressive/test_base_page_primitives.py -v -k safe_select_combo`
Expected: FAIL.

- [ ] **Step 3: Implementar**

Agregar a Familia B en `base_page.py`, después de `safe_checkbox`:

```python
    async def safe_select_combo(
        self,
        combo: Locator,
        option_text: str,
        *,
        retries: int = 2,
    ) -> None:
        """ExtJS combo: click combo → click option by role → verify input_value contains text."""
        from modules.progressive.pages._exceptions import ComboSelectError

        attempts = 0
        last_value = ""
        for attempt in range(retries + 1):
            attempts = attempt + 1
            try:
                await combo.click(timeout=5_000)
                await self.page.wait_for_timeout(300)
                option = self.page.get_by_role("option", name=option_text, exact=True)
                await option.click(timeout=5_000)
                await self.page.keyboard.press("Tab")
            except Exception:
                pass

            try:
                last_value = (await combo.input_value()) or ""
            except Exception:
                last_value = ""

            if option_text.lower() in last_value.lower():
                return

            if attempt < retries:
                await self.page.wait_for_timeout(500 * (attempt + 1))

        debug = await self.dump_debug_context("safe_select_combo")
        screenshot = await self.screenshot(f"safe_combo_failed_{attempts}")
        raise ComboSelectError(
            f"safe_select_combo expected '{option_text}' got '{last_value}' after {attempts} attempts",
            primitive="safe_select_combo",
            field=option_text,
            attempts=attempts,
            screenshot_path=screenshot,
            debug_context=debug,
        )
```

- [ ] **Step 4: Correr tests verde**

Run: `python -m pytest tests/progressive/test_base_page_primitives.py -v -k safe_select_combo`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add modules/progressive/pages/base_page.py tests/progressive/test_base_page_primitives.py
git commit -m "feat(progressive): add safe_select_combo primitive for ExtJS comboboxes"
```

---

### Task 1.11: Implementar `safe_click_continue`

**Files:**
- Modify: `modules/progressive/pages/base_page.py`
- Modify: `tests/progressive/test_base_page_primitives.py`

- [ ] **Step 1: Agregar tests**

```python
@pytest.mark.asyncio
async def test_safe_click_continue_returns_when_url_changes(mock_page, mock_locator):
    from unittest.mock import PropertyMock, patch
    state = {"url": "https://x.com/?pageName=MoreAboutBusiness"}

    async def click_advances_url(*args, **kwargs):
        state["url"] = "https://x.com/?pageName=Rates"

    mock_locator.click = AsyncMock(side_effect=click_advances_url)
    mock_locator.scroll_into_view_if_needed = AsyncMock()

    bp = BasePage(mock_page)
    with patch.object(type(mock_page), "url", new_callable=PropertyMock) as url_mock:
        url_mock.side_effect = lambda: state["url"]
        await bp.safe_click_continue(expect_url_changes_from="MoreAboutBusiness")
    mock_locator.click.assert_awaited()


@pytest.mark.asyncio
async def test_safe_click_continue_raises_ContinueStuckError(mock_page, mock_locator):
    from modules.progressive.pages._exceptions import ContinueStuckError
    mock_page.url = "https://x.com/?pageName=MoreAboutBusiness"
    bp = BasePage(mock_page)
    with pytest.raises(ContinueStuckError) as exc_info:
        await bp.safe_click_continue(expect_url_changes_from="MoreAboutBusiness", retries=2)
    assert exc_info.value.primitive == "safe_click_continue"
```

- [ ] **Step 2: Correr — falla**

Run: `python -m pytest tests/progressive/test_base_page_primitives.py -v -k safe_click_continue`
Expected: FAIL.

- [ ] **Step 3: Implementar**

Agregar a Familia B en `base_page.py`, después de `safe_select_combo`:

```python
    async def safe_click_continue(
        self,
        *,
        expect_url_changes_from: str,
        retries: int = 3,
    ) -> None:
        """Click 'Continue' robustly: blur → text-based locator → force=True → JS dispatch fallback.

        Verifies URL no longer contains `expect_url_changes_from` token.
        Raises ContinueStuckError if URL never advances.
        """
        from modules.progressive.pages._exceptions import ContinueStuckError

        await self.blur_active_element()
        await self.page.wait_for_timeout(300)

        attempts = 0
        for attempt in range(retries + 1):
            attempts = attempt + 1
            try:
                btn = self.page.get_by_text("Continue", exact=True).last
                await btn.scroll_into_view_if_needed(timeout=2_000)
                await btn.click(timeout=10_000, force=True)
            except Exception:
                try:
                    btn = self.page.get_by_role("button", name="Continue").last
                    await btn.click(timeout=5_000, force=True)
                except Exception:
                    pass

            try:
                await self.page.wait_for_load_state("networkidle", timeout=30_000)
            except Exception:
                pass

            if expect_url_changes_from not in self.page.url:
                return

            if attempt >= 1:
                try:
                    await self.page.evaluate(
                        """() => {
                            const spans = Array.from(document.querySelectorAll('span'))
                              .filter(s => (s.innerText || '').trim() === 'Continue');
                            for (const span of spans) {
                                let el = span;
                                while (el && !(el.classList && el.classList.contains('x-btn'))) {
                                    el = el.parentElement;
                                }
                                if (el) {
                                    ['mousedown','mouseup','click'].forEach(t =>
                                        el.dispatchEvent(new MouseEvent(t, {bubbles: true}))
                                    );
                                    return;
                                }
                            }
                        }"""
                    )
                    await self.page.wait_for_timeout(1_500)
                    if expect_url_changes_from not in self.page.url:
                        return
                except Exception:
                    pass

            if attempt < retries:
                await self.page.wait_for_timeout(1_000 * (attempt + 1))

        debug = await self.dump_debug_context("safe_click_continue")
        screenshot = await self.screenshot(f"continue_stuck_{expect_url_changes_from}_{attempts}")
        raise ContinueStuckError(
            f"safe_click_continue: URL still contains '{expect_url_changes_from}' after {attempts} attempts",
            primitive="safe_click_continue",
            field=None,
            attempts=attempts,
            screenshot_path=screenshot,
            debug_context=debug,
        )
```

- [ ] **Step 4: Correr tests verde**

Run: `python -m pytest tests/progressive/test_base_page_primitives.py -v -k safe_click_continue`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add modules/progressive/pages/base_page.py tests/progressive/test_base_page_primitives.py
git commit -m "feat(progressive): add safe_click_continue with JS dispatch fallback"
```

---

### Task 1.12: Implementar esperas dinámicas restantes (`wait_for_page`, `wait_for_field_revealed_by`, `wait_for_currency_formatted`)

**Files:**
- Modify: `modules/progressive/pages/base_page.py`
- Modify: `tests/progressive/test_base_page_primitives.py`

- [ ] **Step 1: Agregar tests**

```python
@pytest.mark.asyncio
async def test_wait_for_page_polls_until_token_appears(mock_page):
    mock_page.url = "https://x.com/?pageName=Rates"
    bp = BasePage(mock_page)
    await bp.wait_for_page("Rates", timeout_ms=1000)


@pytest.mark.asyncio
async def test_wait_for_page_raises_on_timeout(mock_page):
    mock_page.url = "https://x.com/?pageName=Other"
    bp = BasePage(mock_page)
    with pytest.raises(TimeoutError):
        await bp.wait_for_page("Rates", timeout_ms=300)


@pytest.mark.asyncio
async def test_wait_for_field_revealed_by_calls_trigger_then_returns_field(mock_page, mock_locator):
    triggered = {"count": 0}

    async def trigger():
        triggered["count"] += 1

    async def find():
        return mock_locator

    bp = BasePage(mock_page)
    result = await bp.wait_for_field_revealed_by(trigger, find, timeout_ms=2000)
    assert triggered["count"] == 1
    assert result is mock_locator


@pytest.mark.asyncio
async def test_wait_for_currency_formatted_returns_when_dollar_present(mock_page, mock_locator):
    mock_locator.input_value = AsyncMock(return_value="$50,000")
    bp = BasePage(mock_page)
    await bp.wait_for_currency_formatted(mock_locator, timeout_ms=1000)
```

- [ ] **Step 2: Correr — falla**

Run: `python -m pytest tests/progressive/test_base_page_primitives.py -v -k "wait_for_page or wait_for_field_revealed or currency_formatted"`
Expected: FAIL.

- [ ] **Step 3: Implementar**

Agregar a Familia C en `base_page.py`, después de `wait_for_extjs_idle`:

```python
    async def wait_for_page(self, page_name_token: str, *, timeout_ms: int = 30_000) -> None:
        """Poll until URL contains pageName=<page_name_token>. Raises TimeoutError if not."""
        import asyncio
        deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
        while asyncio.get_event_loop().time() < deadline:
            token = await self.current_page_token()
            if token == page_name_token or page_name_token in self.page.url:
                return
            await self.page.wait_for_timeout(200)
        raise TimeoutError(
            f"wait_for_page: token '{page_name_token}' not seen within {timeout_ms}ms; url={self.page.url}"
        )

    async def wait_for_field_revealed_by(
        self,
        trigger_fn,
        target_finder,
        *,
        timeout_ms: int = 5_000,
    ) -> Locator:
        """Run trigger_fn, then poll target_finder until the returned locator is visible."""
        import asyncio
        import inspect

        if inspect.iscoroutinefunction(trigger_fn):
            await trigger_fn()
        else:
            trigger_fn()

        deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
        while asyncio.get_event_loop().time() < deadline:
            result = target_finder()
            if inspect.iscoroutine(result):
                result = await result
            try:
                if (await result.count()) > 0 and await result.is_visible():
                    return result
            except Exception:
                pass
            await self.page.wait_for_timeout(150)

        result = target_finder()
        if inspect.iscoroutine(result):
            result = await result
        return result

    async def wait_for_currency_formatted(
        self,
        locator: Locator,
        *,
        timeout_ms: int = 3_000,
    ) -> None:
        """Wait until input_value contains '$' (ExtJS finished currency formatting)."""
        import asyncio
        deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
        while asyncio.get_event_loop().time() < deadline:
            try:
                v = await locator.input_value()
                if "$" in (v or ""):
                    return
            except Exception:
                pass
            await self.page.wait_for_timeout(150)
```

- [ ] **Step 4: Correr tests verde**

Run: `python -m pytest tests/progressive/test_base_page_primitives.py -v -k "wait_for_page or wait_for_field_revealed or currency_formatted"`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add modules/progressive/pages/base_page.py tests/progressive/test_base_page_primitives.py
git commit -m "feat(progressive): add wait_for_page, wait_for_field_revealed_by, wait_for_currency_formatted"
```

---

### Task 1.13: Verificación holística de fase 1

**Files:** ninguno modificado

- [ ] **Step 1: Correr todos los tests del módulo progressive**

Run: `python -m pytest tests/progressive/ -v`
Expected: todos verde (debe haber > 25 tests).

- [ ] **Step 2: Correr simulador**

Run: `$env:PYTHONIOENCODING="utf-8"; python tests\simulate_progressive.py`
Expected: termina OK con conteo de acciones igual al baseline.

- [ ] **Step 3: Correr tests existentes para no romper nada**

Run: `python -m pytest tests/test_rule_engine.py -v`
Expected: igual que en fase 0.

---

## Phase 2: Migrar `more_business_page.py` (arregla bug RYD)

### Task 2.1: Test que reproduce el bug RYD ELD soft-skip

**Files:**
- Create: `tests/progressive/test_more_business_field_absence.py`

- [ ] **Step 1: Escribir test**

Crear `tests/progressive/test_more_business_field_absence.py`:

```python
"""Verify MoreBusinessPage soft-skips fields not rendered for this commodity.

Reproduces the RYD LLC bug: ELD radio doesn't render for Beverage Distributor.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.progressive.pages.more_business_page import MoreBusinessPage


@pytest.mark.asyncio
async def test_eld_skipped_when_radio_not_present(mock_page, mock_locator):
    """When the ELD radiogroup is absent, fill_and_submit must NOT raise."""
    eld_locator = AsyncMock()
    eld_locator.count = AsyncMock(return_value=0)
    eld_locator.wait_for = AsyncMock(side_effect=TimeoutError("not visible"))

    insured_group = AsyncMock()
    insured_radio = AsyncMock()
    insured_radio.click = AsyncMock()
    insured_radio.check = AsyncMock()
    insured_radio.is_checked = AsyncMock(return_value=True)
    insured_group.get_by_role = MagicMock(return_value=insured_radio)

    filings_group = AsyncMock()
    filings_group.count = AsyncMock(return_value=0)
    filings_group.wait_for = AsyncMock(side_effect=TimeoutError("not visible"))

    none_checkbox = AsyncMock()
    none_checkbox.is_checked = AsyncMock(return_value=True)
    none_checkbox.click = AsyncMock()

    call_n = {"i": 0}

    def get_by_role_side(name=None, exact=False, **kwargs):
        if "radiogroup" == kwargs.get("role") or kwargs.get("name") and "currently insured" in (kwargs.get("name") or "").lower():
            return insured_group
        return eld_locator

    def get_by_role(role, **kwargs):
        n = (kwargs.get("name") or "").lower()
        if "currently insured" in n:
            return insured_group
        if "filings required" in n:
            return filings_group
        if "electronic logging device" in n or "eld" in n:
            return eld_locator
        if role == "checkbox":
            return none_checkbox
        return AsyncMock()

    mock_page.get_by_role = MagicMock(side_effect=get_by_role)

    urls = iter([
        "https://x.com/?pageName=MoreAboutBusiness",
        "https://x.com/?pageName=Rates",
    ])
    type(mock_page).url = property(lambda self: next(urls, "https://x.com/?pageName=Rates"))

    page_obj = MoreBusinessPage(mock_page)
    page_obj.warnings = []

    await page_obj.fill_and_submit(
        currently_insured=False,
        other_coverages="None",
        eld_required=False,
    )

    assert any("eld" in w.lower() and "skip" in w.lower() for w in page_obj.warnings), \
        f"Expected ELD-skipped warning, got: {page_obj.warnings}"
```

- [ ] **Step 2: Correr — falla porque MoreBusinessPage aún no tiene `warnings` ni soft-skip**

Run: `python -m pytest tests/progressive/test_more_business_field_absence.py -v`
Expected: FAIL (test rojo o error).

---

### Task 2.2: Migrar `MoreBusinessPage.fill_and_submit` a primitivas + soft-skip

**Files:**
- Modify: `modules/progressive/pages/more_business_page.py`

- [ ] **Step 1: Reemplazar el archivo entero**

Reemplazar el contenido de `modules/progressive/pages/more_business_page.py` con:

```python
"""More About Business page (BUSINESS step).

URL: pageName=MoreAboutBusiness

REQUIRED fields:
  - currently_insured (Yes/No radio)
  - other_coverages (checkbox group: None of the above by default)

CONDITIONAL fields (may not render for some commodities — soft-skipped):
  - eld_required          (NOT rendered for Beverage Distributor)
  - federal_filings_required

OPTIONAL fields:
  - customer_email
"""

from __future__ import annotations

from typing import List, Optional

from modules.progressive.pages.base_page import BasePage


class MoreBusinessPage(BasePage):
    """Progressive wizard - MoreAboutBusiness page (BUSINESS step)."""

    REQUIRED_FIELDS = ("currently_insured", "other_coverages")
    CONDITIONAL_FIELDS = ("eld_required", "federal_filings_required")
    OPTIONAL_FIELDS = ("customer_email",)

    def __init__(self, page):
        super().__init__(page)
        self.warnings: List[str] = []

    async def fill_and_submit(
        self,
        currently_insured: bool = False,
        other_coverages: str = "None",
        eld_required: bool = False,
        customer_email: Optional[str] = None,
        federal_filings_required: bool = False,
    ) -> None:
        await self.wait_for_extjs_idle()
        await self.remove_overlays()

        if customer_email:
            await self._fill_email(customer_email)

        await self._answer_currently_insured(currently_insured)
        await self._answer_other_coverages(other_coverages)
        await self._answer_federal_filings_conditional(federal_filings_required)
        await self._answer_eld_required_conditional(eld_required)
        await self.safe_click_continue(expect_url_changes_from="MoreAboutBusiness")

    async def _fill_email(self, email: str) -> None:
        print(f"    [Progressive] Customer email: {email}")
        box = self.page.get_by_role("textbox", name="Customer Email Address")
        if await box.count() > 0:
            await self.safe_fill(box.first, email)

    async def _answer_currently_insured(self, is_insured: bool) -> None:
        answer = "Yes" if is_insured else "No"
        print(f"    [Progressive] Currently insured: {answer}")
        group = await self.find_radiogroup("Is the customer currently insured?")
        await self.safe_radio(group, answer)

    async def _answer_other_coverages(self, choice: str) -> None:
        print(f"    [Progressive] Other coverages: {choice}")
        target_labels = ["None of the above"] if choice in ("None", None, "") else [choice]
        for label in target_labels:
            checkboxes = self.page.get_by_role("checkbox", name=label, exact=True)
            n = await checkboxes.count()
            print(f"    [Progressive] Found {n} '{label}' checkbox(es); ticking each")
            for i in range(n):
                cb = checkboxes.nth(i)
                try:
                    await self.safe_checkbox(cb, check=True)
                except Exception as e:
                    print(f"    [Progressive] WARN: checkbox '{label}'[{i}]: {e}")

    async def _answer_federal_filings_conditional(self, required: bool) -> None:
        answer = "Yes" if required else "No"
        group = await self.find_radiogroup("Are state or federal filings required?", timeout_ms=2000)
        if not await self.field_exists(group, wait_ms=1000):
            self._log_skipped("federal_filings_required", "field_not_rendered")
            return
        print(f"    [Progressive] Federal/state filings required: {answer}")
        await self.safe_radio(group, answer)

    async def _answer_eld_required_conditional(self, required: bool) -> None:
        answer = "Yes" if required else "No"
        group = await self.find_radiogroup(
            "Is an Electronic Logging Device (ELD) required",
            timeout_ms=2000,
        )
        if not await self.field_exists(group, wait_ms=1000):
            self._log_skipped("eld_required", "field_not_rendered_for_this_commodity")
            return
        print(f"    [Progressive] ELD required: {answer}")
        await self.safe_radio(group, answer)

    def _log_skipped(self, field: str, reason: str) -> None:
        msg = f"more_business: skipped '{field}' — {reason}"
        print(f"    [Progressive] {msg}")
        self.warnings.append(msg)
```

- [ ] **Step 2: Correr el test específico**

Run: `python -m pytest tests/progressive/test_more_business_field_absence.py -v`
Expected: PASS.

- [ ] **Step 3: Correr todos los tests progressive**

Run: `python -m pytest tests/progressive/ -v`
Expected: todos verde.

- [ ] **Step 4: Correr simulador**

Run: `$env:PYTHONIOENCODING="utf-8"; python tests\simulate_progressive.py`
Expected: termina OK.

- [ ] **Step 5: Propagar warnings a `QuoteResult` en `quote_flow.py`**

Modificar `modules/progressive/quote_flow.py`. Buscar la sección donde se instancia `MoreBusinessPage` y se llama `fill_and_submit`:

```python
            # Step 6: BUSINESS (MoreAboutBusiness)
            result.step_reached = "more_business"
            more_biz = MoreBusinessPage(wizard_page)
            await more_biz.fill_and_submit(
                currently_insured=False,
                other_coverages="None",
                eld_required=False,
            )
```

Reemplazar por:

```python
            # Step 6: BUSINESS (MoreAboutBusiness)
            result.step_reached = "more_business"
            more_biz = MoreBusinessPage(wizard_page)
            await more_biz.fill_and_submit(
                currently_insured=False,
                other_coverages="None",
                eld_required=False,
            )
            result.warnings.extend(more_biz.warnings)
```

- [ ] **Step 6: Live test RYD**

Run:
```powershell
$env:PYTHONIOENCODING="utf-8"
python scripts\run_progressive_from_pdf.py "C:\Users\Desarrollo\Downloads\20260601 BLUE QUOTE RYD LLC.pdf" 06/15/2026
```
Expected: avanza más allá de `more_business`, idealmente captura precio. Si no captura precio aún, anota en qué page rompe (será diferente del bug ELD ahora).

- [ ] **Step 7: Commit fase 2**

```bash
git add modules/progressive/pages/more_business_page.py modules/progressive/quote_flow.py tests/progressive/test_more_business_field_absence.py
git commit -m "fix(progressive): RYD ELD bug — soft-skip conditional fields not rendered for commodity

MoreBusinessPage now uses BasePage primitives and field_exists to gate
ELD and federal-filings radios. Beverage Distributor (RYD) doesn't get
the ELD radio rendered, so we skip with a warning instead of timing out.

Adds REQUIRED/CONDITIONAL/OPTIONAL field classification (see spec
2026-06-02-progressive-basepage-hardening-design.md)."
```

---

## Phase 3: Migrar pages pequeñas

### Task 3.1: Migrar `login_page.py`

**Files:**
- Modify: `modules/progressive/pages/login_page.py`

- [ ] **Step 1: Leer el archivo actual**

Run: `Get-Content modules\progressive\pages\login_page.py | Select-Object -First 200`
Anotar: qué llamadas directas a `page.fill/click` hay, qué se puede convertir.

- [ ] **Step 2: Migrar interacciones**

Reemplazar todas las llamadas `self.page.fill(selector, value)` por:
```python
await self.safe_fill(self.page.locator(selector).first, value, verify=True)
```
Reemplazar todas las llamadas `self.page.click(selector)` para el botón Sign In por:
```python
await self.page.locator(selector).first.click(force=True)
```
(El botón de login NO usa `safe_click_continue` porque no es un Continue del wizard; sigue siendo un click directo, pero con `force=True`.)

Verificar que el `print(f"...")` se mantiene para trazabilidad.

- [ ] **Step 3: Correr simulador**

Run: `$env:PYTHONIOENCODING="utf-8"; python tests\simulate_progressive.py`
Expected: termina OK con mismo conteo.

- [ ] **Step 4: Live RYD para verificar login real**

Run:
```powershell
$env:PYTHONIOENCODING="utf-8"
python scripts\run_progressive_from_pdf.py "C:\Users\Desarrollo\Downloads\20260601 BLUE QUOTE RYD LLC.pdf" 06/15/2026
```
Expected: login completa sin regresión.

- [ ] **Step 5: Commit**

```bash
git add modules/progressive/pages/login_page.py
git commit -m "refactor(progressive): migrate login_page to BasePage primitives"
```

---

### Task 3.2: Migrar `home_page.py`

**Files:**
- Modify: `modules/progressive/pages/home_page.py`

- [ ] **Step 1: Leer el archivo actual**

Run: `Get-Content modules\progressive\pages\home_page.py | Select-Object -First 200`
Anotar interacciones directas.

- [ ] **Step 2: Migrar**

Reglas de reemplazo:
- `self.page.fill(sel, val)` → `await self.safe_fill(self.page.locator(sel).first, val)`
- `self.page.select_option(sel, ...)` → `await self.safe_select_combo(self.page.locator(sel).first, value)`
- `self.page.click("button:has-text('Continue')")` → `await self.safe_click_continue(expect_url_changes_from="<page-token>")`
- `await self.page.wait_for_load_state("networkidle")` antes de cada interacción → reemplazar por `await self.wait_for_extjs_idle()`

Mantener la lógica de USDOT search + new-tab tracking sin cambios estructurales.

- [ ] **Step 3: Correr simulador**

Run: `$env:PYTHONIOENCODING="utf-8"; python tests\simulate_progressive.py`
Expected: termina OK.

- [ ] **Step 4: Live RYD**

Run el script de RYD. Expected: home page completa sin regresión.

- [ ] **Step 5: Commit**

```bash
git add modules/progressive/pages/home_page.py
git commit -m "refactor(progressive): migrate home_page to BasePage primitives"
```

---

### Task 3.3: Migrar `final_details_page.py`

**Files:**
- Modify: `modules/progressive/pages/final_details_page.py`

- [ ] **Step 1: Leer el archivo (71 líneas)**

Run: `Get-Content modules\progressive\pages\final_details_page.py`

- [ ] **Step 2: Migrar**

Aplicar mismas reglas que en Task 3.2. **IMPORTANTE:** este page object NO debe clickear "Continue" porque avanzaría a PAYMENT (binding real). Solo lee información y toma screenshot. Si hay algún `_click_continue` local, **eliminarlo**, no migrarlo.

- [ ] **Step 3: Correr simulador**

Run: `$env:PYTHONIOENCODING="utf-8"; python tests\simulate_progressive.py`
Expected: termina OK.

- [ ] **Step 4: Commit**

```bash
git add modules/progressive/pages/final_details_page.py
git commit -m "refactor(progressive): migrate final_details_page to BasePage primitives"
```

---

### Task 3.4: Verificación end-to-end RYD fase 3

- [ ] **Step 1: Live RYD completo**

Run:
```powershell
$env:PYTHONIOENCODING="utf-8"
python scripts\run_progressive_from_pdf.py "C:\Users\Desarrollo\Downloads\20260601 BLUE QUOTE RYD LLC.pdf" 06/15/2026
```
Expected: avanza hasta donde llegue (idealmente captura precio o llega a la próxima page no migrada).

- [ ] **Step 2: Anotar progreso en baseline**

Si RYD captura precio aquí: gran victoria, agrega nota al baseline doc.

---

## Phase 4: Migrar `drivers_page.py`

### Task 4.1: Migrar `AddDriverPage`

**Files:**
- Modify: `modules/progressive/pages/drivers_page.py`

- [ ] **Step 1: Leer el archivo (271 líneas)**

Run: `Get-Content modules\progressive\pages\drivers_page.py`
Identificar las 3 clases (`AddDriverPage`, `DriverSummaryPage`, `NoHitPage`).

- [ ] **Step 2: Migrar `AddDriverPage.fill_and_submit`**

Aplicar reglas:
- Cualquier `self.page.fill(...)` → `await self.safe_fill(...)`
- Cualquier `self.page.click(...)` para selects ExtJS → `await self.safe_select_combo(...)`
- Cualquier `get_by_role("radio", ...)` directo → `await self.safe_radio(await self.find_radiogroup(...), ...)`
- License Number sin label confiable → `await self.find_by_label_text("License Number")`
- Cualquier `_click_continue` local → `await self.safe_click_continue(expect_url_changes_from="AddDriver")`
- Antes de cada bloque de interacciones → `await self.wait_for_extjs_idle()`

Agregar al inicio de la clase:
```python
class AddDriverPage(BasePage):
    REQUIRED_FIELDS = ("license_state", "license_number")
    CONDITIONAL_FIELDS = ("exclude_from_policy", "has_driving_history")
    OPTIONAL_FIELDS = ()
```

- [ ] **Step 3: Correr simulador**

Run: `$env:PYTHONIOENCODING="utf-8"; python tests\simulate_progressive.py`
Expected: termina OK.

- [ ] **Step 4: Commit incremental**

```bash
git add modules/progressive/pages/drivers_page.py
git commit -m "refactor(progressive): migrate AddDriverPage to BasePage primitives"
```

---

### Task 4.2: Migrar `DriverSummaryPage` y `NoHitPage`

**Files:**
- Modify: `modules/progressive/pages/drivers_page.py`

- [ ] **Step 1: Migrar `DriverSummaryPage`**

Aplicar reglas. Para `add_driver` button (no es Continue del wizard):
```python
btn = self.page.get_by_text("Add Driver", exact=True).last
await btn.click(force=True)
```

Para `click_continue`:
```python
await self.safe_click_continue(expect_url_changes_from="DriverSummary")
```

- [ ] **Step 2: Migrar `NoHitPage`**

Este page solo se muestra cuando MVR falla y NO debe avanzar (es un HALT). Migrar solo screenshot/diagnóstico. Ningún Continue.

- [ ] **Step 3: Correr simulador + RYD live**

Run simulador, luego script RYD.
Expected: simulador OK; RYD avanza más.

- [ ] **Step 4: Commit fase 4**

```bash
git add modules/progressive/pages/drivers_page.py
git commit -m "refactor(progressive): migrate DriverSummaryPage and NoHitPage to BasePage primitives"
```

---

## Phase 5: Migrar pages grandes

### Task 5.1: Migrar `coverages_rates_page.py`

**Files:**
- Modify: `modules/progressive/pages/coverages_rates_page.py`

- [ ] **Step 1: Leer el archivo (408 líneas)**

Run: `Get-Content modules\progressive\pages\coverages_rates_page.py`

- [ ] **Step 2: Identificar grupos lógicos**

Anotar las funciones del page:
- Captura de precio
- Selección de coverages opcionales
- Continue a final details

- [ ] **Step 3: Migrar grupo "captura de precio"**

Las lecturas (`get_by_text(...).inner_text()`) NO requieren primitiva. Mantener. Solo migrar las que llenan/click.

- [ ] **Step 4: Migrar grupo "selección de coverages"**

Combos → `safe_select_combo`. Checkboxes → `safe_checkbox`. Radios → `safe_radio`. Cada `wait_for_timeout(N)` mágico → reemplazar por `wait_for_extjs_idle()` salvo justificación documentada.

- [ ] **Step 5: Migrar `proceed_to_final_details`**

Reemplazar el Continue local por:
```python
async def proceed_to_final_details(self) -> None:
    await self.safe_click_continue(expect_url_changes_from="CoveragesRates")
```

- [ ] **Step 6: Correr simulador**

Run: `$env:PYTHONIOENCODING="utf-8"; python tests\simulate_progressive.py`
Expected: termina OK.

- [ ] **Step 7: Live RYD**

Run el script. Expected: si llega hasta esta página, ya debería capturar precio.

- [ ] **Step 8: Commit**

```bash
git add modules/progressive/pages/coverages_rates_page.py
git commit -m "refactor(progressive): migrate coverages_rates_page to BasePage primitives + robust Continue"
```

---

### Task 5.2: Migrar `vehicles_page.py` — `VehicleSummaryPage` y `MostCommonVehiclesPage`

**Files:**
- Modify: `modules/progressive/pages/vehicles_page.py`

- [ ] **Step 1: Leer el archivo (639 líneas)**

Run: `Get-Content modules\progressive\pages\vehicles_page.py`
Identificar las 3 clases.

- [ ] **Step 2: Migrar `VehicleSummaryPage`**

- `add_vehicle` button:
```python
btn = self.page.get_by_text("Add Vehicle", exact=True).last
await btn.click(force=True)
```
- `click_continue`:
```python
await self.safe_click_continue(expect_url_changes_from="VehicleSummary")
```

- [ ] **Step 3: Migrar `MostCommonVehiclesPage.select_vehicle_type`**

El "tile picker" no es exactamente combo ni radio. Usar:
```python
tile = self.page.get_by_text(vehicle_type, exact=True).first
await tile.click(force=True)
await self.wait_for_extjs_idle()
```
Y el Continue al final:
```python
await self.safe_click_continue(expect_url_changes_from="MostCommonVehicles")
```

- [ ] **Step 4: Correr simulador**

Run: `$env:PYTHONIOENCODING="utf-8"; python tests\simulate_progressive.py`
Expected: termina OK.

- [ ] **Step 5: Commit incremental**

```bash
git add modules/progressive/pages/vehicles_page.py
git commit -m "refactor(progressive): migrate VehicleSummaryPage and MostCommonVehiclesPage"
```

---

### Task 5.3: Migrar `vehicles_page.py` — `AddVehiclePage`

**Files:**
- Modify: `modules/progressive/pages/vehicles_page.py`

- [ ] **Step 1: Migrar combos Year/Make/Model/Style**

Cada combo:
```python
year_combo = await self.find_combo("Year")
await self.safe_select_combo(year_combo, str(vehicle.year))
```

- [ ] **Step 2: Migrar campos VIN, plate, value**

```python
vin_input = await self.find_by_label_text("VIN")
await self.safe_fill(vin_input, vehicle.vin)

plate_input = await self.find_by_label_text("Plate")
await self.safe_fill(plate_input, vehicle.plate)

value_input = await self.find_by_label_text("Vehicle Value")
await self.safe_fill(value_input, str(vehicle.value or 50000))
await self.wait_for_currency_formatted(value_input)
```

- [ ] **Step 3: Migrar checkbox "Vehicle has no equipment"**

```python
no_equip = self.page.get_by_role("checkbox", name="Vehicle has no equipment", exact=True)
if await self.field_exists(no_equip, wait_ms=1500):
    await self.safe_checkbox(no_equip, check=True)
else:
    self._log_skipped("vehicle_has_no_equipment", "field_not_rendered")
```

(Agregar `_log_skipped` y `self.warnings: List[str] = []` en `__init__` de `AddVehiclePage` siguiendo el patrón de `MoreBusinessPage`.)

- [ ] **Step 4: Migrar Continue**

```python
await self.safe_click_continue(expect_url_changes_from="AddVehicle")
```

- [ ] **Step 5: Correr simulador**

Run: `$env:PYTHONIOENCODING="utf-8"; python tests\simulate_progressive.py`
Expected: termina OK.

- [ ] **Step 6: Live M&D (regresión completa)**

Run:
```powershell
$env:PYTHONIOENCODING="utf-8"
python scripts\run_progressive_from_pdf.py "<ruta al PDF de M&D>" 06/15/2026
```
Expected: M&D captura precio igual que pre-refactor.

- [ ] **Step 7: Live RYD**

Run el script RYD. Expected: avanza más / captura precio.

- [ ] **Step 8: Commit fase 5**

```bash
git add modules/progressive/pages/vehicles_page.py
git commit -m "refactor(progressive): migrate AddVehiclePage to BasePage primitives + conditional fields"
```

---

## Phase 6: Migrar `business_info_page.py` (el más grande)

### Task 6.1: Migrar `BusinessInfoPage` por bloques

**Files:**
- Modify: `modules/progressive/pages/business_info_page.py`

- [ ] **Step 1: Leer el archivo (831 líneas)**

Run: `Get-Content modules\progressive\pages\business_info_page.py | Select-Object -First 250`
Luego siguientes lotes de 250 líneas. Identificar bloques:
- Operator USDOT confirmation
- Business name (default + diferente)
- Address
- Phone
- Owner info
- Owns goods (conditional, solo distributors)
- Commodity / radius

- [ ] **Step 2: Agregar clasificación al inicio de la clase**

```python
class BusinessInfoPage(BasePage):
    REQUIRED_FIELDS = (
        "business_name",
        "address_line1", "city", "state", "zip",
        "phone",
        "owner_first_name", "owner_last_name", "owner_dob",
        "commodity", "radius",
    )
    CONDITIONAL_FIELDS = (
        "owns_goods",          # only distributors
        "different_business_name",
    )
    OPTIONAL_FIELDS = ("owner_phone", "customer_email")

    def __init__(self, page):
        super().__init__(page)
        self.warnings: list[str] = []

    def _log_skipped(self, field: str, reason: str) -> None:
        msg = f"business_info: skipped '{field}' — {reason}"
        print(f"    [Progressive] {msg}")
        self.warnings.append(msg)
```

- [ ] **Step 3: Migrar bloque "business name"**

Reemplazar el `_fill_role_textbox` (o similares) que usa lookup-por-placeholder por:

```python
# Si el usuario marca "Enter a different business name":
diff_radio_group = await self.find_radiogroup("business name")
await self.safe_radio(diff_radio_group, "Enter a different Business Name")

# El textbox revelado:
diff_input = self.page.locator(
    "//*[contains(text(),'Enter a different Business Name')]/following::input[@type='text'][1]"
)
await self.safe_fill(diff_input, fields.business_name)
```

Para el botón Continue (varias páginas dentro de BusinessInfo): `safe_click_continue`.

- [ ] **Step 4: Migrar bloque "address"**

Cada campo: `find_by_placeholder` o `find_by_label_text` + `safe_fill`. State es combo: `find_combo` + `safe_select_combo`.

- [ ] **Step 5: Migrar bloque "phone"**

```python
phone_input = await self.find_by_label_text("Primary Phone")
await self.safe_fill(phone_input, fields.phone)
```

- [ ] **Step 6: Migrar bloque "owns goods" (conditional)**

Agregar este método a la clase `BusinessInfoPage` (no es función de módulo) y llamarlo desde `fill_and_submit`:

```python
async def _answer_owns_goods_conditional(self, owns: bool) -> None:
    group = await self.find_radiogroup("own goods", timeout_ms=2000)
    if not await self.field_exists(group, wait_ms=1000):
        self._log_skipped("owns_goods", "field_not_rendered_for_this_commodity")
        return
    await self.safe_radio(group, "Yes" if owns else "No")
```

- [ ] **Step 7: Migrar bloque "commodity / radius"**

```python
commodity_combo = await self.find_combo("primary commodity")
await self.safe_select_combo(commodity_combo, fields.commodity)

radius_combo = await self.find_combo("radius")
await self.safe_select_combo(radius_combo, fields.radius)
```

- [ ] **Step 8: Propagar `self.warnings` al `QuoteResult`**

En `modules/progressive/quote_flow.py`, en la sección de business_info:

```python
            # Step 3: START (BusinessOwnerInfo)
            result.step_reached = "business_info"
            biz_page = BusinessInfoPage(wizard_page)
            await biz_page.fill_and_submit(fields)
            result.warnings.extend(biz_page.warnings)
```

- [ ] **Step 9: Correr simulador**

Run: `$env:PYTHONIOENCODING="utf-8"; python tests\simulate_progressive.py`
Expected: termina OK.

- [ ] **Step 10: Live M&D (regresión crítica)**

Run el script M&D. Expected: cotiza igual que pre-refactor con precio similar.

- [ ] **Step 11: Live RYD**

Run el script RYD. Expected: cotización end-to-end completa, captura precio, warnings poblados con campos skipped.

- [ ] **Step 12: Commit fase 6**

```bash
git add modules/progressive/pages/business_info_page.py modules/progressive/quote_flow.py
git commit -m "refactor(progressive): migrate business_info_page to BasePage primitives

Last and largest page in the migration. business_info_page.py was 831 lines
of imperative ExtJS workarounds; this commit migrates each field-group to
the safe_* primitives and adds REQUIRED/CONDITIONAL/OPTIONAL classification.

Skipped CONDITIONAL fields (e.g. owns_goods for non-distributors) are now
logged to QuoteResult.warnings instead of crashing the flow."
```

---

## Phase 7: Cleanup + docs

### Task 7.1: Borrar helpers DEPRECATED de `base_page.py`

**Files:**
- Modify: `modules/progressive/pages/base_page.py`

- [ ] **Step 1: Verificar que no quedan llamadas a los viejos**

Run:
```powershell
Select-String -Path "modules\progressive\pages\*.py" -Pattern "by_label|fill_by_label|select_by_label|click_by_text|select_option_by_text|wait_for_text|wait_for_navigation" | Where-Object { $_.Path -notlike "*base_page.py" }
```
Expected: ningún match.

- [ ] **Step 2: Borrar la sección "DEPRECATED helpers" de `base_page.py`**

Eliminar las funciones: `by_label`, `fill_by_label`, `click_by_text`, `click_button`, `select_by_label`, `select_option_by_text`, `wait_for_text`, `wait_for_navigation` y el comentario de header de esa sección.

- [ ] **Step 3: Correr simulador**

Run: `$env:PYTHONIOENCODING="utf-8"; python tests\simulate_progressive.py`
Expected: termina OK.

- [ ] **Step 4: Correr todos los tests**

Run: `python -m pytest tests/ -v`
Expected: todos verde.

- [ ] **Step 5: Commit**

```bash
git add modules/progressive/pages/base_page.py
git commit -m "refactor(progressive): remove DEPRECATED helpers from BasePage

All pages now use the safe_* primitives. The legacy helpers
(by_label, fill_by_label, select_by_label, click_by_text,
select_option_by_text, wait_for_text, wait_for_navigation)
are dead code and removed."
```

---

### Task 7.2: Verificar criterios de éxito #3 y #4

**Files:** ninguno

- [ ] **Step 1: Cero llamadas directas a page.fill/click/select_option desde pages**

Run:
```powershell
Select-String -Path "modules\progressive\pages\*.py" -Pattern "self\.page\.(fill|click|select_option)" | Where-Object { $_.Path -notlike "*base_page.py" }
```
Expected: ningún match. Si hay matches, decidir caso por caso si justificar con comentario o migrar a primitiva.

- [ ] **Step 2: Cero `_click_continue` locales**

Run:
```powershell
Select-String -Path "modules\progressive\pages\*.py" -Pattern "_click_continue" | Where-Object { ($_.Line -notlike "*safe_click_continue*") -and ($_.Path -notlike "*base_page.py*") }
```
Expected: ningún match.

- [ ] **Step 3: Si algo sale, fixearlo + commit**

Si hay matches, hacer las migraciones que falten y commit:

```bash
git add modules/progressive/pages/
git commit -m "refactor(progressive): final cleanup of direct page.* calls"
```

---

### Task 7.3: Capturar métricas post-refactor

**Files:**
- Modify: `docs/superpowers/baselines/2026-06-02-progressive-baseline.md`

- [ ] **Step 1: Re-correr el script de métricas**

Run:
```powershell
python tools\capture_baseline_metrics.py > docs\superpowers\baselines\2026-06-02-progressive-post-refactor.md
```

- [ ] **Step 2: Anexar comparativa al baseline**

Editar `docs/superpowers/baselines/2026-06-02-progressive-baseline.md` agregando al final:

```markdown

## Comparativa pre/post refactor

Ver `2026-06-02-progressive-post-refactor.md` para los conteos post-refactor.

| Métrica | Pre | Post | Δ |
|---|---|---|---|
| Total wait_for_timeout (unjustified) | <N pre> | <N post> | -<diff>% |
| Total _click_continue locales | <N pre> | 0 | -100% |
| Total líneas pages/*.py | <N pre> | <N post> | <diff> |

Criterio de éxito #5: reducción ≥ 70% de wait_for_timeout mágicos.
Resultado: <PASS|FAIL>
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/baselines/
git commit -m "docs: progressive post-refactor metrics comparison"
```

---

### Task 7.4: Actualizar `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Leer la sección "Reglas para Progressive"**

Run: `Get-Content CLAUDE.md`

- [ ] **Step 2: Reemplazar la sección**

Localizar:
```markdown
## Reglas para Progressive (web automation)

- **Selectores ExtJS**: comboboxes Sencha NO son `<select>`. Patrón obligatorio: `combo.click()` → `get_by_role("option", name=value).click()`. NUNCA `select_option()` con ExtJS.
- **STOP en FINAL DETAILS**: el flujo termina en `pageName=AdditionalDetails`. NUNCA click el "Continue" final — avanza a PAYMENT y bind real de la póliza.
- **NoHit es HALT**: si MVR/CLUE falla y Progressive pide SSN → reportar al usuario, no auto-rellenar SSN (data sensible).
- **Effective date**: viene del subject del email con regex `[Ee]ffective\s+date[:\s]+(\d{1,2}/\d{1,2}/\d{4})`.
```

Reemplazar por:
```markdown
## Reglas para Progressive (web automation)

- **Todas las interacciones usan las primitivas de `BasePage` (`modules/progressive/pages/base_page.py`)**: `safe_fill`, `safe_radio`, `safe_checkbox`, `safe_select_combo`, `safe_click_continue`. NINGÚN page object llama `page.fill/click/select_option` directo. Ver spec `docs/superpowers/specs/2026-06-02-progressive-basepage-hardening-design.md`.
- **Campos condicionales por commodity**: declarar en `CONDITIONAL_FIELDS` de la clase + usar `field_exists` para soft-skip con `_log_skipped(...)`. Ejemplos: ELD radio ausente para Beverage Distributor, owns_goods ausente para Trucker.
- **STOP en FINAL DETAILS**: el flujo termina en `pageName=AdditionalDetails`. NUNCA click el "Continue" final — avanza a PAYMENT y bind real de la póliza.
- **NoHit es HALT**: si MVR/CLUE falla y Progressive pide SSN → reportar al usuario, no auto-rellenar SSN (data sensible).
- **Effective date**: viene del subject del email con regex `[Ee]ffective\s+date[:\s]+(\d{1,2}/\d{1,2}/\d{4})`.
- **Esperas dinámicas, no `wait_for_timeout` mágicos**: usar `wait_for_extjs_idle`, `wait_for_field_revealed_by`, `wait_for_currency_formatted`, `wait_for_page`. Si necesitás un `wait_for_timeout(N)` literal, dejá comentario justificando.
```

- [ ] **Step 3: Actualizar sección "Estado actual"**

Localizar la sección con "Estado actual (2026-05-26)" y reemplazar con:

```markdown
## Estado actual (post-refactor 2026-06-XX)

✅ Módulo Progressive con BasePage hardened y primitivas ExtJS-safe obligatorias.
✅ End-to-end LIVE validado con M&D Trucker + RYD Beverage Distributor.
✅ Campos condicionales por commodity manejados con `field_exists` + soft-skip.
✅ Simulador pasa con el conteo histórico de acciones.

Próximos PRs candidatos:
- Add Trailer flow real (hoy se skipea con warning).
- Centralización de selectores en YAML registry si Progressive cambia mucho.
- Split de `business_info_page.py` y `vehicles_page.py` por responsabilidad.
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md after Progressive BasePage hardening"
```

---

### Task 7.5: Actualizar `docs/AGENTS_CONTEXT.md`

**Files:**
- Modify: `docs/AGENTS_CONTEXT.md`

- [ ] **Step 1: Leer**

Run: `Get-Content docs\AGENTS_CONTEXT.md | Select-Object -First 100`

- [ ] **Step 2: Agregar sección al final**

Append al final:

```markdown

## 2026-06-XX — BasePage hardening (post-refactor)

Refactor mayor del módulo Progressive: `base_page.py` ahora es el hub de
primitivas ExtJS-safe obligatorias. Cada page declara
`REQUIRED_FIELDS`/`CONDITIONAL_FIELDS`/`OPTIONAL_FIELDS` y delega
interacción a las primitivas. Bug RYD ELD resuelto con `field_exists` +
soft-skip.

Referencias:
- Spec: `docs/superpowers/specs/2026-06-02-progressive-basepage-hardening-design.md`
- Plan: `docs/superpowers/plans/2026-06-02-progressive-basepage-hardening.md`
- Métricas: `docs/superpowers/baselines/2026-06-02-progressive-baseline.md`
```

- [ ] **Step 3: Commit**

```bash
git add docs/AGENTS_CONTEXT.md
git commit -m "docs: AGENTS_CONTEXT — record BasePage hardening refactor"
```

---

### Task 7.6: Actualizar memorias persistentes

**Files:**
- Modify: `C:\Users\Desarrollo\.claude\projects\c--Users-Desarrollo-Videos-Quotes-H2O-Quote-RPA\memory\progressive_extjs_selector_patterns.md`
- Modify: `C:\Users\Desarrollo\.claude\projects\c--Users-Desarrollo-Videos-Quotes-H2O-Quote-RPA\memory\progressive_state_2026_06_02.md`
- Modify: `C:\Users\Desarrollo\.claude\projects\c--Users-Desarrollo-Videos-Quotes-H2O-Quote-RPA\memory\MEMORY.md`

- [ ] **Step 1: Actualizar `progressive_extjs_selector_patterns.md`**

Reemplazar el cuerpo de la memoria con:

```markdown
# Progressive ExtJS — primitivas obligatorias (post-refactor)

**Why:** Antes de 2026-06-XX, cada page reimplementaba sus propios patches contra ExtJS. Tras el refactor BasePage Hardening, todos los patches están centralizados en `modules/progressive/pages/base_page.py`.

**How to apply:** Cuando edites cualquier `pages/*.py`, llamá las primitivas de BasePage. NO llames `page.fill/click/select_option` directo. Si un campo nuevo no rinde para algún commodity, marcalo `CONDITIONAL_FIELDS` y usá `field_exists` + `_log_skipped`.

## Catálogo (ver `base_page.py` para firmas completas)

- Localización: `find_by_label_text`, `find_by_placeholder`, `find_radiogroup`, `find_combo`, `field_exists`
- Interacción: `safe_fill`, `safe_radio`, `safe_checkbox`, `safe_select_combo`, `safe_click_continue`
- Esperas dinámicas: `wait_for_extjs_idle`, `wait_for_page`, `wait_for_field_revealed_by`, `wait_for_currency_formatted`
- Estado: `remove_overlays`, `blur_active_element`, `current_page_token`
- Diagnóstico: `screenshot`, `dump_debug_context`

## Regla del usuario (durable)

- NO usar `keyboard.type()` para contenido. Tab/Escape OK para blur.
- Esperar a CONDICIÓN, no a tiempo. Cada `wait_for_timeout(N)` literal lleva comentario.
```

- [ ] **Step 2: Actualizar `progressive_state_2026_06_02.md`**

Reemplazar el cuerpo con un breve resumen del estado post-refactor:

```markdown
# Estado Progressive — post-refactor BasePage hardening

## Funciona end-to-end LIVE

- M&D CUSTOM FREIGHT LLC (Trucker, USDOT 2998569)
- RYD LLC (Beverage Distributor, USDOT 4427567) — primera cotización exitosa

## Arquitectura

`base_page.py` es el hub de primitivas ExtJS-safe. Pages declaran
REQUIRED/CONDITIONAL/OPTIONAL y delegan interacción.

## Refs

- Spec: `docs/superpowers/specs/2026-06-02-progressive-basepage-hardening-design.md`
- Plan: `docs/superpowers/plans/2026-06-02-progressive-basepage-hardening.md`

## Pendientes futuros

- Add Trailer flow real
- Centralización de selectores en registry
- Split de archivos grandes
```

- [ ] **Step 3: Verificar `MEMORY.md` sigue apuntando**

Las líneas existentes en `MEMORY.md` siguen siendo válidas (mismos archivos, contenido actualizado). No agregar duplicados.

---

### Task 7.7: Verificación final de los 8 criterios de éxito

**Files:** ninguno

- [ ] **Step 1: Criterio #1 — M&D end-to-end live**

Run M&D script. Expected: captura precio.

- [ ] **Step 2: Criterio #2 — RYD end-to-end live**

Run RYD script. Expected: captura precio + warnings con skipped fields.

- [ ] **Step 3: Criterio #3 — cero `page.fill/click/select_option` directo en pages**

Run:
```powershell
Select-String -Path "modules\progressive\pages\*.py" -Pattern "self\.page\.(fill|click|select_option)" | Where-Object { $_.Path -notlike "*base_page.py" }
```
Expected: vacío.

- [ ] **Step 4: Criterio #4 — cero `_click_continue` local**

Run:
```powershell
Select-String -Path "modules\progressive\pages\*.py" -Pattern "_click_continue" | Where-Object { ($_.Line -notlike "*safe_click_continue*") -and ($_.Path -notlike "*base_page.py*") }
```
Expected: vacío.

- [ ] **Step 5: Criterio #5 — reducción ≥ 70% de wait_for_timeout mágicos**

Run:
```powershell
python tools\capture_baseline_metrics.py
```
Comparar con baseline pre-refactor. Calcular % de reducción.

- [ ] **Step 6: Criterio #6 — simulador pasa con conteo histórico**

Run: `$env:PYTHONIOENCODING="utf-8"; python tests\simulate_progressive.py`
Expected: termina OK con conteo de acciones igual o equivalente al baseline.

- [ ] **Step 7: Criterio #7 — tests unitarios pasan**

Run: `python -m pytest tests/progressive/ -v`
Expected: todos verde.

- [ ] **Step 8: Criterio #8 — errores estructurados**

Provocar un fallo intencional (e.g., comentar temporalmente la implementación de un radio para que `safe_radio` falle) y verificar que el `ExtJSInteractionError` lleva `primitive`, `field`, `attempts`, `screenshot_path`, `debug_context`. Revertir el cambio inmediatamente después.

- [ ] **Step 9: Actualizar el baseline doc con resultado de cada criterio**

Editar `docs/superpowers/baselines/2026-06-02-progressive-baseline.md`:

```markdown

## Criterios de éxito — resultado final

| # | Criterio | Resultado |
|---|---|---|
| 1 | M&D end-to-end live | ✅ / ❌ |
| 2 | RYD end-to-end live | ✅ / ❌ |
| 3 | Cero page.* directo en pages | ✅ / ❌ |
| 4 | Cero _click_continue local | ✅ / ❌ |
| 5 | Reducción ≥ 70% wait_for_timeout mágicos | ✅ / ❌ (X%) |
| 6 | Simulador pasa | ✅ / ❌ |
| 7 | Tests unitarios pasan | ✅ / ❌ |
| 8 | ExtJSInteractionError con contexto | ✅ / ❌ |
```

- [ ] **Step 10: Commit final**

```bash
git add docs/superpowers/baselines/
git commit -m "docs: record final success criteria results for BasePage hardening"
```

---

## Done

Cuando todas las 7 fases estén commiteadas y los 8 criterios verificados, abrir PR a `main` con descripción que liga al spec, al plan, y al baseline doc. Mencionar:
- Bug RYD ELD: resuelto.
- M&D: sin regresión.
- Tests unitarios añadidos: `tests/progressive/`.
- Fuera de alcance (PRs futuros): Add Trailer flow, registry de selectores, split de archivos grandes, JSON logging.
