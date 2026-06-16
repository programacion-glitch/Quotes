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
