"""R-086 (Diana 2026-08-03): el PDF de la cotización se guarda con la fecha
AAAA-MM-DD primero, luego el negocio y el número de quote."""

from datetime import datetime

from modules.progressive.pdf_downloader import quote_pdf_basename

_WHEN = datetime(2026, 8, 3, 15, 30)


def test_formato_fecha_negocio_quote():
    out = quote_pdf_basename("PANTHER EXPRESS TRUCKING LLC", "CA117638002", when=_WHEN)
    assert out == "2026-08-03 PANTHER EXPRESS TRUCKING LLC Progressive CA117638002"


def test_empieza_con_fecha_aaaa_mm_dd():
    out = quote_pdf_basename("ACME", "CA1", when=_WHEN)
    assert out.startswith("2026-08-03 ")


def test_sanitiza_caracteres_invalidos_del_negocio():
    out = quote_pdf_basename('R/D "TRUCKING": <LLC>?', "CA1", when=_WHEN)
    assert out == "2026-08-03 RD TRUCKING LLC Progressive CA1"


def test_sin_negocio_ni_quote_number():
    out = quote_pdf_basename(None, None, when=_WHEN)
    assert out == "2026-08-03 Progressive sin-numero"


def test_usa_fecha_actual_por_defecto():
    out = quote_pdf_basename("ACME", "CA1")
    assert out.split(" ")[0] == datetime.now().strftime("%Y-%m-%d")
