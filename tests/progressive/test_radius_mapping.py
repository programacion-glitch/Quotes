"""Mapeo de radio de operación -> bracket discreto de Progressive.

Diana 2026-06-25: una Blue Quote con 'radius 500 miles' terminaba en el bracket
'More than 500 miles' (>500, más caro). Progressive tiene un bracket DISCRETO
'500 miles'. Opciones reales verificadas live: 50/100/200/300/500/More than 500.
"""
import pytest

from modules.progressive.pages.vehicles_page import radius_to_progressive_option


@pytest.mark.parametrize("raw,expected", [
    # Caso exacto de Diana: 500 millas -> bracket discreto, NO ">500"
    ("500 MILES", "500 miles"),
    ("500", "500 miles"),
    ("500 miles", "500 miles"),
    # Frases sin tope -> More than 500
    ("Over 500 miles", "More than 500 miles"),
    ("more than 500", "More than 500 miles"),
    (">500", "More than 500 miles"),
    ("unlimited", "More than 500 miles"),
    # Brackets exactos
    ("300", "300 miles"),
    ("300 miles", "300 miles"),
    ("200", "200 miles"),
    ("100", "100 miles"),
    ("50", "50 miles"),
    ("50 miles", "50 miles"),
    # Valores intermedios -> bracket más chico que los cubre
    ("250", "300 miles"),
    ("450", "500 miles"),
    ("75", "100 miles"),
    # >500 numérico -> More than 500
    ("600", "More than 500 miles"),
    ("1,000", "More than 500 miles"),
    # Vacío/desconocido -> conservador (no sub-estimar)
    ("", "More than 500 miles"),
    (None, "More than 500 miles"),
    ("statewide", "More than 500 miles"),
])
def test_radius_to_progressive_option(raw, expected):
    assert radius_to_progressive_option(raw) == expected
