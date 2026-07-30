# Descarga del PDF oficial de cotización de Progressive

**Fecha:** 2026-07-06
**Estado:** Diseño aprobado por el usuario (2026-07-06)
**Ámbito:** `modules/progressive/` (nuevo `pdf_downloader.py`, método en `coverages_rates_page.py`, integración en `quote_flow.py`)

## Problema

Hoy, tras capturar el premium en la página RATES, el flujo llama
`CoveragesRatesPage.save_page_pdf(...)` (`quote_flow.py:200`) que hace
`page.pdf()` (solo headless) o un screenshot PNG de fallback. Eso adjunta un
**render de la página**, no el **PDF oficial** que Progressive genera para la
cotización. El usuario necesita adjuntar el proposal oficial (como ya hace GEICO
con su Print Quote Proposal).

## Mapeo live (2026-07-06, RYD LLC, Quote #CA117158735)

Desde la página RATES (`pageName=CoveragesRates`):
1. Botón header **"Print, Email, Fax"** → `pageName=PrintEmailFax`.
2. Radio **"Insurance Quote (with all bill plans)"** (el otro, "Document Set", es
   para pólizas vendidas).
3. Checkbox **"Print"** → REVELA el botón **"Print/Send"** (y auto-marca "Agent
   Fax Cover Page", inofensivo — no se toca).
4. **"Print/Send"** → abre una **pestaña/popup NUEVA** con el PDF inline; la tab
   principal va a `pageName=PrintEmailFaxConfirm` ("Your request has been
   completed!", con botón **"Return to quote"**).

**Endpoint** (URL del popup, se captura, NO se arma a mano):
`clpolicy.foragentsonly.com/Express/PDFHandler.ashx?sessionID=...&RequestType=DataPro&DocumentType=Quote&rdm=...&wGuid=<quote>&correlationId=...&pageName=Quote`
Verificado con fetch autenticado: `200 · application/pdf · content-disposition
inline; filename=DataProDocument.pdf · ~73KB · %PDF-1.7`. Servido inline (como
GEICO) → `expect_download()` NO sirve; se usa fetch autenticado con
`credentials:'include'` desde una página del mismo origen (clpolicy).

## Objetivo

Reemplazar el `save_page_pdf` del path de RATES por la descarga del PDF oficial,
con **reintento** y **fallback a la captura** si falla, sin que la cotización se
pierda nunca por un problema de impresión.

## Componentes

### 1. `modules/progressive/pdf_downloader.py` (nuevo)

Espejo de `modules/geico/pdf_downloader.py`, con mensajes de error "Progressive".

```python
async def download_progressive_pdf(
    page, pdf_url: str, output_path, timeout_ms: int = 30_000
) -> dict:
    """Descarga el PDF vía fetch autenticado dentro del contexto de `page`
    (debe estar en un origen clpolicy.foragentsonly.com para que apliquen las
    cookies). Corre `fetch(url,{credentials:'include'})`, pasa el ArrayBuffer a
    base64 en chunks de 0x8000, y del lado Python valida content-type
    `application/pdf` + magic `%PDF`, y escribe los bytes.
    Devuelve {"path", "size", "content_type"}. Lanza RuntimeError si:
    url vacía, http error, timeout, content-type no-pdf, sin %PDF, o falla la
    escritura."""
```

El JS del fetch, el troceo base64, el parseo del JSON, y las validaciones son
idénticos a `download_geico_pdf` (mismo patrón probado). Se DUPLICA (módulo
Progressive propio) siguiendo la convención por-MGA del repo; sin refactor del de
GEICO. NO se incluye un helper `quote_pdf_filename` (YAGNI: el caller ya pasa un
`name` pre-armado; `download_quote_pdf` construye `progressive_quote_<name>.pdf`
igual que `save_page_pdf`, para que primary y fallback nombren consistente).

### 2. `CoveragesRatesPage.download_quote_pdf` (nuevo método)

```python
async def download_quote_pdf(
    self, name: str, *, output_dir: str = "data/quote_pdfs", max_attempts: int = 2
) -> Optional[str]:
```

Requisito de entrada: el wizard está en RATES (`pageName=CoveragesRates`).

Loop de hasta `max_attempts` intentos. En cada intento:
1. `_ensure_on_rates()` — si el token de página no es CoveragesRates, click el
   botón de step "RATES" y espera a que cargue RATES.
2. Click **"Print, Email, Fax"** (botón header) → espera `PrintEmailFax`.
3. `safe_radio` sobre **"Insurance Quote (with all bill plans)"**.
4. `safe_checkbox` **"Print"** → espera que aparezca **"Print/Send"**.
5. `async with self.page.context.expect_page() as popup_info:` click **"Print/Send"**.
   `popup = await popup_info.value`. Espera que `popup.url` sea la de
   `PDFHandler.ashx` (wait_for_url/poll). Guarda `pdf_url = popup.url`. Cierra el
   popup (`await popup.close()`).
6. `download_progressive_pdf(self.page, pdf_url, out_path)` — fetch desde
   `self.page` (que quedó en `PrintEmailFaxConfirm`, mismo origen clpolicy).
7. Click **"Return to quote"** → `_ensure_on_rates()` (verifica CoveragesRates).
8. Éxito → devuelve `str(out_path)`.

Manejo de error por intento: capturar excepción, loguear, `dump_debug_context`
opcional; en el próximo intento `_ensure_on_rates()` re-encarrila desde donde
haya quedado. Tras agotar los intentos: `_ensure_on_rates()` (garantiza RATES) y
devuelve `None`.

**Garantía de post-condición:** al retornar (éxito o `None`), el wizard queda en
**RATES**. Así el fallback captura RATES y `proceed_to_final_details` (que usa
`expect_url_changes_from="CoveragesRates"`) funciona.

Selectores (del mapeo live), vía primitivas BasePage donde aplican; los botones
de acción son clicks por rol (como login/OTP), con `remove_overlays` + `force`
en retry:
- header: `get_by_role("button", name="Print, Email, Fax")`
- radio:  "Insurance Quote (with all bill plans)" (match parcial "Insurance Quote")
- checkbox: `get_by_role("checkbox", name="Print")` (exacto)
- `get_by_role("button", name="Print/Send")`
- `get_by_role("button", name="Return to quote")`
- step RATES: `get_by_role("button", name="RATES")`
- popup URL match: contiene `PDFHandler.ashx` y `DocumentType=Quote`

### 3. Integración en `quote_flow.py` (líneas 197-202)

Reemplazar:
```python
result.pdf_path = await rates_page.save_page_pdf(
    f"quote_{(result.price.quote_number if result.price else None) or 'unknown'}"
)
```
por:
```python
_pdf_name = f"quote_{(result.price.quote_number if result.price else None) or 'unknown'}"
result.pdf_path = await rates_page.download_quote_pdf(_pdf_name)
if not result.pdf_path:
    result.warnings.append(
        "PDF oficial de Progressive falló tras reintentos; fallback a captura de RATES")
    result.pdf_path = await rates_page.save_page_pdf(_pdf_name)
```

`save_page_pdf` **se mantiene** (fallback). Se deja ANTES del check de `dry_run`
(igual que hoy), así un dry-run también ejercita el flujo de impresión (es
seguro: imprime el proposal, NO bindea).

## Manejo de errores

- `download_progressive_pdf` lanza `RuntimeError` en cualquier fallo.
- `download_quote_pdf` captura por intento, reintenta (hasta `max_attempts`),
  y devuelve `None` si se agotan — nunca propaga (la quote no debe fallar por el
  PDF). Deja el wizard en RATES pase lo que pase.
- `quote_flow` cae a `save_page_pdf` si `download_quote_pdf` devuelve `None`.
- La cotización **nunca** falla por el PDF.

## Testing

`tests/progressive/test_pdf_downloader.py` (nuevo):
- `download_progressive_pdf` con un `page` fake cuyo `evaluate` devuelve:
  - JSON de éxito `{contentType:"application/pdf", size, base64:<%PDF...>}` →
    escribe bytes en `tmp_path`, devuelve dict con path/size/content_type.
  - `{error: "http 500", statusText:"..."}` → RuntimeError.
  - content-type no-pdf (ej. `text/html`) → RuntimeError.
  - base64 de bytes sin `%PDF` → RuntimeError (magic ausente).
  - `pdf_url` vacía → RuntimeError.

`download_quote_pdf` (flujo Playwright con popup/ExtJS): **validado LIVE**, no unit
— consistente con el resto de las pages de Progressive (sus flujos de browser no
se testean unit). Validación live: correr una quote (o reabrir una existente) y
confirmar que adjunta el PDF oficial (`DataProDocument.pdf`, `%PDF`).

## Fuera de alcance

- No se toca `download_geico_pdf` (sin refactor compartido; convención por-MGA).
- No se cambia cómo el orquestador adjunta `result.pdf_path` al correo — ya
  fluye; solo cambia a qué archivo apunta.
- No se toca el STOP en FINAL DETAILS ni nada del binding.
