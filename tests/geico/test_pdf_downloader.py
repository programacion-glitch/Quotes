

# ---------------------------------------------------------------------------
# Dos límites de AL en la misma cotización (R-097)
# ---------------------------------------------------------------------------

def test_el_limite_de_al_distingue_los_dos_pdfs_de_geico():
    from modules.geico.pdf_downloader import quote_pdf_filename
    uno = quote_pdf_filename("T&S LOGISTICS", "CA1", al_limit="$1M CSL")
    dos = quote_pdf_filename("T&S LOGISTICS", "CA1", al_limit="$500K CSL")
    assert uno != dos
    assert uno.endswith("_AL_1M.pdf")
    assert dos.endswith("_AL_500K.pdf")


def test_sin_limite_geico_conserva_el_nombre_de_siempre():
    from modules.geico.pdf_downloader import quote_pdf_filename
    assert quote_pdf_filename("T&S LOGISTICS", "CA1") == \
        quote_pdf_filename("T&S LOGISTICS", "CA1", al_limit=None)
