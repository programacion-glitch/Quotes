"""Diana #3/#9: sección "Other Business Insurance" con DOS preguntas.

Q1 ("currently have") y Q2 ("purchase within 45 days") comparten los mismos
labels de checkbox. nth(0)=Q1, nth(1)=Q2 (orden de DOM, verificado live
2026-06-25). Con GL: tildar 'General Liability' en Q1 y 'None of the above' en
Q2. Sin GL: 'None of the above' en ambas.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.progressive.pages.more_business_page import MoreBusinessPage


def _two_checkboxes():
    """Locator-like con 2 elementos (Q1, Q2) y .count()/.nth()."""
    items = [AsyncMock(), AsyncMock()]
    loc = MagicMock()
    loc.count = AsyncMock(return_value=2)
    loc.nth = MagicMock(side_effect=lambda i: items[i])
    loc._items = items
    return loc


def _wire(mock_page):
    gl = _two_checkboxes()
    none = _two_checkboxes()

    def get_by_role(role, **kw):
        name = kw.get("name")
        if name == "General Liability":
            return gl
        if name == "None of the above":
            return none
        return _two_checkboxes()

    mock_page.get_by_role = MagicMock(side_effect=get_by_role)
    page_obj = MoreBusinessPage(mock_page)
    checked = []
    page_obj.safe_checkbox = AsyncMock(side_effect=lambda loc, check=True: checked.append(loc))
    return page_obj, gl, none, checked


@pytest.mark.asyncio
async def test_gl_ticks_general_liability_q1_and_none_q2(mock_page):
    page_obj, gl, none, checked = _wire(mock_page)
    await page_obj._answer_other_coverages("None", has_general_liability=True)
    assert gl._items[0] in checked, "GL de Q1 debe tildarse"
    assert none._items[1] in checked, "None of the above de Q2 debe tildarse"
    assert gl._items[1] not in checked, "GL de Q2 NO debe tildarse"
    assert none._items[0] not in checked, "None of the above de Q1 NO debe tildarse"


@pytest.mark.asyncio
async def test_no_gl_ticks_none_in_both_questions(mock_page):
    page_obj, gl, none, checked = _wire(mock_page)
    await page_obj._answer_other_coverages("None", has_general_liability=False)
    assert none._items[0] in checked and none._items[1] in checked, \
        "Sin GL: 'None of the above' en ambas preguntas"
    assert gl._items[0] not in checked and gl._items[1] not in checked, \
        "Sin GL: General Liability NO se toca"
