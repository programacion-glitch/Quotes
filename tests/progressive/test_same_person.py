"""_same_person: owner ~ driver name matching (sources the owner's DOB).

A miss leaves owner_dob blank and Progressive rejects the START page for
Individual / Sole Proprietor, so the tolerance here directly gates quotes.
"""

from modules.progressive.field_mapper import _same_person


def test_exact_match():
    assert _same_person("JOSE LUIS LEZAMA", "JOSE LUIS LEZAMA")


def test_middle_name_vs_initial():
    assert _same_person("JOSE ANDRES DELGADO", "JOSE A DELGADO")


def test_one_vs_two_surnames():
    assert _same_person("JERSSON MEDINA", "JERSSON STIVEN MEDINA ROBAYO")


def test_extra_absent_middle_name():
    assert _same_person("JUAN ROJAS", "JUAN QUEVEDO ROJAS")


def test_driver_row_leads_with_initial():
    """Live 2026-06-10 (GONZALEZ, A. TRUCKING): the driver row led with an
    initial ('J ANTONIO GONZALEZ') while the owner section spelled
    'ANTONIO S GONZALEZ' — must match so the owner DOB is sourced."""
    assert _same_person("ANTONIO S GONZALEZ", "J ANTONIO GONZALEZ")


def test_initial_with_period_skipped():
    assert _same_person("A. RICARDO SOSA", "RICARDO SOSA JR")


def test_different_first_names_no_match():
    assert not _same_person("PEDRO GONZALEZ", "ANTONIO GONZALEZ")


def test_same_first_name_no_shared_surname_no_match():
    assert not _same_person("ANTONIO LOPEZ", "ANTONIO GONZALEZ")


def test_empty_names_no_match():
    assert not _same_person(None, "ANTONIO GONZALEZ")
    assert not _same_person("ANTONIO GONZALEZ", "")
