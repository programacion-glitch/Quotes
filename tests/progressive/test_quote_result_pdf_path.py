from modules.progressive.quote_flow import QuoteResult


def test_quote_result_has_pdf_path_defaulting_none():
    r = QuoteResult()
    assert r.pdf_path is None
