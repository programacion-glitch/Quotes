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


# ---------------------------------------------------------------------------
# Dos límites de AL en la misma cotización (R-097)
# ---------------------------------------------------------------------------

def test_el_limite_de_al_va_al_final_del_nombre():
    """El formato de R-086 que Diana aprobó no se toca: el límite se agrega
    al final para distinguir las dos indicaciones."""
    out = quote_pdf_basename("T&S LOGISTICS", "CA117054124", when=_WHEN,
                             al_limit="$750K CSL")
    assert out.startswith("2026-08-03 T&S LOGISTICS Progressive CA117054124")
    assert out.endswith("AL 750K")


def test_los_dos_limites_dan_nombres_distintos():
    uno = quote_pdf_basename("T&S", "CA1", when=_WHEN, al_limit="$1M CSL")
    dos = quote_pdf_basename("T&S", "CA1", when=_WHEN, al_limit="$750K CSL")
    assert uno != dos


def test_sin_limite_el_nombre_es_el_de_siempre():
    con = quote_pdf_basename("T&S", "CA1", when=_WHEN, al_limit=None)
    sin = quote_pdf_basename("T&S", "CA1", when=_WHEN)
    assert con == sin
