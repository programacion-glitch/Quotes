"""Detección de General Liability desde profile.coverages (códigos Blue Quote)."""
from types import SimpleNamespace

import pytest

from modules.progressive.field_mapper import _has_general_liability


@pytest.mark.parametrize("codes,expected", [
    (["AL", "GL", "MTC", "APD"], True),   # ELITE: GL presente
    (["gl"], True),                        # case-insensitive
    ([" GL "], True),                      # tolera espacios
    (["AL", "MTC", "APD"], False),         # sin GL
    ([], False),
    (None, False),
])
def test_has_general_liability(codes, expected):
    profile = SimpleNamespace(coverages=codes)
    assert _has_general_liability(profile) is expected
