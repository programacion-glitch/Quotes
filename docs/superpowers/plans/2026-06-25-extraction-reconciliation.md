# Doble validación por reconciliación form ↔ IA — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que la extracción de la Blue Quote corra el extractor form-based Y el de IA y reconcilie ambos (form autoritativo, IA llena huecos), auto-corrigiendo el subconteo de listas (drivers/unidades) del fallback de IA.

**Architecture:** Función pura `reconcile()` en un módulo nuevo `modules/extraction_reconciler.py` que recibe los campos extraídos por cada fuente (`ExtractionFields`) y devuelve los reconciliados + discrepancias. `document_ai_extractor.py` corre ambos extractores (best-effort) y llama `reconcile`. El extractor de IA se refactoriza para DEVOLVER `ExtractionFields` en vez de mutar el `profile`.

**Tech Stack:** Python 3.12, dataclasses, pytest. Intérprete: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe`.

**Spec:** `docs/superpowers/specs/2026-06-25-extraction-reconciliation-design.md`

---

## File Structure

- **Create** `modules/extraction_reconciler.py` — `ExtractionFields`, `Discrepancy`, `reconcile()` (pura). Única responsabilidad: reconciliar dos extracciones.
- **Create** `tests/test_extraction_reconciler.py` — unit de `reconcile()` (determinista, sin red).
- **Modify** `modules/document_ai_extractor.py` — refactor `_extract_blue_quote_with_ai` → `_extract_blue_quote_ai_fields` (devuelve `ExtractionFields`); reescribir el bloque "BLUE QUOTE" de `extract_all` para correr ambos + `reconcile`.
- **Create** `tests/test_blue_quote_reconciliation.py` — integración con doubles (form 4 / IA 2 → 4).

---

## Task 1: Módulo reconciler + función pura `reconcile()`

**Files:**
- Create: `modules/extraction_reconciler.py`
- Test: `tests/test_extraction_reconciler.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_extraction_reconciler.py
"""Unit de reconcile(): form autoritativo, IA llena huecos. Determinista."""
from modules.quote_profile import ApplicantProfile, UnitsProfile, DriverProfile, CoveragesProfile
from modules.extraction_reconciler import ExtractionFields, reconcile


def _drv(n):
    return [DriverProfile(name=f"D{i}") for i in range(n)]


def test_form_drivers_win_over_ai_undercount():
    # Caso ELITE: form 4 drivers, IA 2 -> 4 + discrepancia.
    form = ExtractionFields(applicant=ApplicantProfile(business_name="ELITE"),
                            drivers=_drv(4), units=UnitsProfile(count=4))
    ai = ExtractionFields(applicant=ApplicantProfile(business_name="ELITE"),
                          drivers=_drv(2), units=UnitsProfile(count=4))
    out, disc = reconcile(form, ai)
    assert len(out.drivers) == 4
    assert any(d.field == "drivers" for d in disc)


def test_form_empty_uses_ai_drivers():
    form = ExtractionFields(applicant=ApplicantProfile(business_name="X"), drivers=[])
    ai = ExtractionFields(applicant=ApplicantProfile(business_name="X"), drivers=_drv(3))
    out, disc = reconcile(form, ai)
    assert len(out.drivers) == 3
    assert any(d.field == "drivers" and "IA" in d.resolution for d in disc)


def test_commodity_form_wins():
    form = ExtractionFields(commodity="BUILDING MATERIALS")
    ai = ExtractionFields(commodity="GENERAL FREIGHT")
    out, disc = reconcile(form, ai)
    assert out.commodity == "BUILDING MATERIALS"
    assert any(d.field == "commodity" for d in disc)


def test_ai_none_uses_form():
    form = ExtractionFields(applicant=ApplicantProfile(business_name="X"), drivers=_drv(4))
    out, disc = reconcile(form, None)
    assert len(out.drivers) == 4
    assert disc == []


def test_form_none_uses_ai():
    ai = ExtractionFields(applicant=ApplicantProfile(business_name="X"), drivers=_drv(2))
    out, disc = reconcile(None, ai)
    assert len(out.drivers) == 2


def test_scalar_gap_filled_from_ai():
    # form sin email -> usa el email de la IA.
    form = ExtractionFields(applicant=ApplicantProfile(business_name="X", email=None))
    ai = ExtractionFields(applicant=ApplicantProfile(business_name="X", email="a@b.com"))
    out, _ = reconcile(form, ai)
    assert out.applicant.email == "a@b.com"


def test_unit_count_mismatch_form_wins_with_warning():
    form = ExtractionFields(units=UnitsProfile(count=4, vehicles=[]),
                            drivers=_drv(1))
    # form vacío de vehicles pero count>0 -> autoritativo
    ai = ExtractionFields(units=UnitsProfile(count=2))
    out, disc = reconcile(form, ai)
    assert out.units.count == 4
    assert any(d.field == "units" for d in disc)


def test_coverages_detail_from_form_only():
    cd = CoveragesProfile()
    form = ExtractionFields(coverages_detail=cd)
    ai = ExtractionFields(coverages_detail=None)
    out, _ = reconcile(form, ai)
    assert out.coverages_detail is cd
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/test_extraction_reconciler.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'modules.extraction_reconciler'`

- [ ] **Step 3: Write the implementation**

```python
# modules/extraction_reconciler.py
"""Reconciliación form ↔ IA de la extracción de la Blue Quote.

El extractor form-based (campos del PDF rellenable) es AUTORITATIVO; la IA llena
huecos y sirve de doble-chequeo. Si ambos tienen una lista (drivers/unidades) y
los conteos difieren, gana el form y se registra la discrepancia. Si el form
está vacío (PDF plano), se usa la IA. Best-effort: cualquiera de las dos
fuentes puede ser None.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields as dataclass_fields
from typing import List, Optional

from modules.quote_profile import (
    ApplicantProfile, UnitsProfile, CoveragesProfile, DriverProfile,
)


@dataclass
class ExtractionFields:
    """Campos extraídos de una Blue Quote por UNA fuente (form ó IA)."""
    applicant: Optional[ApplicantProfile] = None
    commodity: str = ""
    coverages: List[str] = field(default_factory=list)
    units: Optional[UnitsProfile] = None
    drivers: List[DriverProfile] = field(default_factory=list)
    coverages_detail: Optional[CoveragesProfile] = None


@dataclass
class Discrepancy:
    field: str
    form_value: object
    ai_value: object
    resolution: str


def _empty(v) -> bool:
    return v is None or v == "" or v == []


def _merge_applicant(form: Optional[ApplicantProfile],
                     ai: Optional[ApplicantProfile]) -> Optional[ApplicantProfile]:
    """Por cada campo: gana el form si no está vacío; si no, la IA."""
    if form is None:
        return ai
    if ai is None:
        return form
    merged = ApplicantProfile()
    for f in dataclass_fields(ApplicantProfile):
        fv = getattr(form, f.name)
        av = getattr(ai, f.name)
        setattr(merged, f.name, av if _empty(fv) else fv)
    return merged


def reconcile(form: Optional[ExtractionFields],
              ai: Optional[ExtractionFields]):
    """Devuelve (ExtractionFields reconciliado, [Discrepancy])."""
    discrepancies: List[Discrepancy] = []

    if form is None and ai is None:
        return ExtractionFields(), discrepancies
    if form is None:
        return ai, discrepancies
    if ai is None:
        return form, discrepancies

    out = ExtractionFields()
    out.applicant = _merge_applicant(form.applicant, ai.applicant)

    # commodity (form autoritativo)
    out.commodity = form.commodity if not _empty(form.commodity) else (ai.commodity or "")
    if (not _empty(form.commodity) and not _empty(ai.commodity)
            and form.commodity != ai.commodity):
        discrepancies.append(
            Discrepancy("commodity", form.commodity, ai.commodity, "uso form"))

    # coverages (lista de códigos)
    out.coverages = form.coverages if form.coverages else (ai.coverages or [])

    # coverages_detail: solo el form lo produce
    out.coverages_detail = form.coverages_detail

    # drivers
    fdrv = form.drivers or []
    adrv = ai.drivers or []
    if fdrv:
        out.drivers = fdrv
        if len(adrv) != len(fdrv):
            res = ("WARNING: IA encontró MÁS" if len(adrv) > len(fdrv)
                   else "uso form")
            discrepancies.append(
                Discrepancy("drivers", len(fdrv), len(adrv), res))
    else:
        out.drivers = adrv
        if adrv:
            discrepancies.append(
                Discrepancy("drivers", 0, len(adrv), "form vacío → IA"))

    # units (form con vehicles ó count>0 es autoritativo)
    funits = form.units
    aunits = ai.units
    fcount = funits.count if funits else 0
    acount = aunits.count if aunits else 0
    if funits and (fcount > 0 or funits.vehicles):
        out.units = funits
        if aunits and acount > 0 and acount != fcount:
            res = ("WARNING: IA contó MÁS" if acount > fcount else "uso form")
            discrepancies.append(Discrepancy("units", fcount, acount, res))
    else:
        out.units = aunits or UnitsProfile()
        if acount:
            discrepancies.append(
                Discrepancy("units", fcount, acount, "form vacío → IA"))

    return out, discrepancies
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/test_extraction_reconciler.py -q`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add modules/extraction_reconciler.py tests/test_extraction_reconciler.py
git commit -m "feat(extract): reconcile() form<->IA (funcion pura + tests)"
```

---

## Task 2: Refactor del extractor de IA → devolver `ExtractionFields`

**Files:**
- Modify: `modules/document_ai_extractor.py` (método `_extract_blue_quote_with_ai`, ~L808–873)
- Test: `tests/test_blue_quote_reconciliation.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_blue_quote_reconciliation.py
"""Integración: el extractor de IA devuelve ExtractionFields y la reconciliación
hace ganar al form."""
from modules.document_ai_extractor import DocumentAIExtractor
from modules.extraction_reconciler import ExtractionFields


def test_ai_fields_returns_extractionfields(monkeypatch):
    ex = DocumentAIExtractor()
    # Evitar red: forzar el contenido y la respuesta de IA.
    monkeypatch.setattr(ex, "_extract_content",
                        lambda *a, **k: {"type": "text", "text": "x"})
    monkeypatch.setattr(ex, "_extract_ai_document", lambda *a, **k: {
        "business_name": "ELITE", "owner_name": "LUIS", "usdot": "2857089",
        "commodity": "BUILDING MATERIALS", "coverages": ["AL", "MTC"],
        "unit_count": 4, "trailer_types": ["FLATBED"],
        "drivers": [{"name": "LUIS", "exp_years": 8},
                    {"name": "IRVING", "exp_years": 2}],
    })
    fields = ex._extract_blue_quote_ai_fields({"filename": "BQ.pdf", "data": b"x"})
    assert isinstance(fields, ExtractionFields)
    assert fields.applicant.business_name == "ELITE"
    assert len(fields.drivers) == 2
    assert fields.units.count == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/test_blue_quote_reconciliation.py::test_ai_fields_returns_extractionfields -q`
Expected: FAIL with `AttributeError: ... has no attribute '_extract_blue_quote_ai_fields'`

- [ ] **Step 3: Refactor `_extract_blue_quote_with_ai` into `_extract_blue_quote_ai_fields`**

Reemplazar el método `_extract_blue_quote_with_ai(self, att, profile)` (que muta `profile` y devuelve bool) por uno que DEVUELVE `ExtractionFields` (o `None`). Mantener intactas las dos pasadas (texto → visión).

Agregar el import al tope del archivo (junto a los otros `from modules...`):

```python
from modules.extraction_reconciler import ExtractionFields, reconcile
```

Nuevo método (misma lógica de pasadas, pero construye y devuelve `ExtractionFields`):

```python
    def _extract_blue_quote_ai_fields(self, att) -> "Optional[ExtractionFields]":
        """Extrae la Blue Quote por IA y DEVUELVE ExtractionFields (sin mutar).
        Pasada 1 texto; si no hay business_name, pasada 2 forzando visión.
        Devuelve None si no hay datos usables."""
        content = self._extract_content(att["filename"], att["data"])
        self._debug_content("BLUE QUOTE", att["filename"], content)
        ai_data = self._extract_ai_document("BLUE QUOTE", content) if content else None
        business_name = (ai_data or {}).get("business_name") if ai_data else None

        if (not business_name) and content and content.get("type") == "text":
            print("    Blue Quote: text pass returned empty business_name → retrying with vision")
            content = self._extract_content(att["filename"], att["data"], force_vision=True)
            self._debug_content("BLUE QUOTE", att["filename"], content)
            if content:
                ai_data = self._extract_ai_document("BLUE QUOTE", content)

        if not ai_data or not ai_data.get("business_name"):
            return None

        business_years = ai_data.get("business_years")
        is_nv = ai_data.get("is_new_venture")
        if is_nv is None:
            is_nv = business_years is None or business_years == 0

        applicant = ApplicantProfile(
            business_name=ai_data.get("business_name") or "",
            owner_name=ai_data.get("owner_name") or "",
            owner_age=ai_data.get("owner_age"),
            usdot=ai_data.get("usdot") or "",
            business_years=business_years,
            is_new_venture=bool(is_nv),
        )
        drivers = [
            DriverProfile(name=d.get("name") or "", cdl_years=d.get("exp_years"))
            for d in (ai_data.get("drivers") or [])
        ]
        return ExtractionFields(
            applicant=applicant,
            commodity=_resolve_commodity(ai_data.get("commodity"), ai_data.get("destinations")),
            coverages=ai_data.get("coverages") or [],
            units=UnitsProfile(
                count=ai_data.get("unit_count") or 0,
                trailer_types=ai_data.get("trailer_types") or [],
            ),
            drivers=drivers,
            coverages_detail=None,
        )
```

(Borrar el método viejo `_extract_blue_quote_with_ai`. Su único llamador se reescribe en Task 3.)

- [ ] **Step 4: Run test to verify it passes**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/test_blue_quote_reconciliation.py::test_ai_fields_returns_extractionfields -q`
Expected: PASS

- [ ] **Step 5: Run pyflakes + commit**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pyflakes modules/document_ai_extractor.py`
Expected: sin nuevos errores (referencias a `_extract_blue_quote_with_ai` deben haber desaparecido).

```bash
git add modules/document_ai_extractor.py tests/test_blue_quote_reconciliation.py
git commit -m "refactor(extract): _extract_blue_quote_ai_fields devuelve ExtractionFields"
```

---

## Task 3: Integrar la reconciliación en `extract_all`

**Files:**
- Modify: `modules/document_ai_extractor.py` (bloque `if "BLUE QUOTE" in classified:`, ~L920–972)
- Test: `tests/test_blue_quote_reconciliation.py` (agregar test de integración)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_blue_quote_reconciliation.py  (agregar)
from modules.quote_profile import ApplicantProfile, UnitsProfile, DriverProfile
from modules.extraction_reconciler import ExtractionFields


def test_extract_all_form_drivers_win(monkeypatch):
    ex = DocumentAIExtractor()

    # form-based: 4 drivers (mapeado)
    def fake_map(_self, _bq):
        return (ApplicantProfile(business_name="ELITE", usdot="2857089"),
                "BUILDING MATERIALS", ["AL"], UnitsProfile(count=4),
                [DriverProfile(name=f"D{i}") for i in range(4)], None)
    monkeypatch.setattr(DocumentAIExtractor, "_map_blue_quote_to_profile", fake_map)

    # BlueQuotePDFExtractor.extract -> dict cualquiera (no se usa por el fake_map)
    import modules.document_ai_extractor as mod
    class _FakeBQ:
        def __init__(self, *a, **k): pass
        def extract(self): return {"driver_information": [1, 2, 3, 4]}
    monkeypatch.setattr(mod, "BlueQuotePDFExtractor", _FakeBQ)

    # IA: solo 2 drivers (subconteo)
    monkeypatch.setattr(ex, "_extract_blue_quote_ai_fields", lambda att:
        ExtractionFields(applicant=ApplicantProfile(business_name="ELITE"),
                         commodity="BUILDING MATERIALS", coverages=["AL"],
                         units=UnitsProfile(count=4),
                         drivers=[DriverProfile(name="D0"), DriverProfile(name="D1")]))

    att = {"filename": "20260622 BLUE QUOTE.pdf", "data": b"%PDF-1.4"}
    profile = ex.extract_all([att])
    assert len(profile.drivers) == 4          # gana el form
    assert profile.applicant.business_name == "ELITE"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/test_blue_quote_reconciliation.py::test_extract_all_form_drivers_win -q`
Expected: FAIL (hoy el bloque no reconcilia; con el form sufficiente igual daría 4, pero el test fija la NUEVA ruta — si falla por estructura, seguir al Step 3).

- [ ] **Step 3: Reescribir el bloque "BLUE QUOTE"**

Reemplazar el bloque actual (`# Try the form-based BlueQuotePDFExtractor first; fall back to AI vision…` hasta el final del `if bq_fallback_reason:` de la AI fallback) por:

```python
        if "BLUE QUOTE" in classified:
            att = classified["BLUE QUOTE"]

            # --- Fuente 1: form-based (best-effort) ---
            form_fields = None
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                    tmp.write(att["data"])
                    tmp_path = tmp.name
                try:
                    bq_data = BlueQuotePDFExtractor(tmp_path).extract()
                finally:
                    Path(tmp_path).unlink(missing_ok=True)
                applicant, commodity, coverages, units, drivers, coverages_detail = \
                    self._map_blue_quote_to_profile(bq_data)
                form_fields = ExtractionFields(
                    applicant=applicant, commodity=commodity, coverages=coverages,
                    units=units, drivers=drivers, coverages_detail=coverages_detail)
            except Exception as e:
                print(f"    Blue Quote form extractor raised: {e}")

            # --- Fuente 2: IA (best-effort; si el proxy está caído NO rompe) ---
            ai_fields = None
            try:
                ai_fields = self._extract_blue_quote_ai_fields(att)
            except Exception as e:
                print(f"    Blue Quote AI extractor raised: {e}")

            # --- Reconciliación (form autoritativo, IA llena huecos) ---
            reconciled, discrepancies = reconcile(form_fields, ai_fields)
            for d in discrepancies:
                print(f"    [reconcile] {d.field}: form={d.form_value}, "
                      f"IA={d.ai_value} → {d.resolution}")

            if reconciled.applicant and reconciled.applicant.business_name:
                profile.applicant = reconciled.applicant
                profile.commodity = reconciled.commodity
                profile.coverages = reconciled.coverages
                profile.coverages_detail = reconciled.coverages_detail
                profile.units = reconciled.units
                profile.drivers = reconciled.drivers
                print(f"    Blue Quote extracted: {profile.applicant.business_name}, "
                      f"commodity={profile.commodity} "
                      f"(drivers={len(profile.drivers)}, units={profile.units.count})")
            else:
                print("    Blue Quote: ni form ni IA produjeron datos usables")
```

Nota: si quedaron referencias a `_is_blue_quote_sufficient` solo usadas por el bloque viejo, dejarlas (no molestan) o borrarlas si pyflakes marca import/método sin uso. NO borrar `_map_blue_quote_to_profile`.

- [ ] **Step 4: Run the integration test + full extractor suite**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/test_blue_quote_reconciliation.py tests/test_commodity_extraction.py -q`
Expected: PASS

- [ ] **Step 5: Regresión + pyflakes**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/ -q`
Expected: misma cantidad de fallos que el baseline (solo las 2 pre-existentes de rule_engine), cero regresiones nuevas.
Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pyflakes modules/document_ai_extractor.py modules/extraction_reconciler.py`

- [ ] **Step 6: Commit**

```bash
git add modules/document_ai_extractor.py tests/test_blue_quote_reconciliation.py
git commit -m "feat(extract): reconciliacion form<->IA en extract_all (Blue Quote)"
```

---

## Self-Review

**Spec coverage:**
- Reconciliación form↔IA con form autoritativo → Task 1 (`reconcile`) + Task 3 (wiring). ✓
- Auto-corregir + loguear discrepancias → Task 3 (loop de `discrepancies`). ✓
- Best-effort / degradación (IA o form None) → Task 1 (ramas None) + Task 3 (try/except por fuente). ✓
- Alcance: drivers, unidades (count), commodity, coverages, escalares → Task 1. ✓
- Costo: 1 llamada IA extra → Task 3 (siempre corre `_extract_blue_quote_ai_fields`). ✓

**Placeholder scan:** sin TBD/TODO; todo el código está completo. ✓

**Type consistency:** `ExtractionFields`/`Discrepancy`/`reconcile` usados igual en Task 1/2/3; `_extract_blue_quote_ai_fields(att) -> ExtractionFields` consistente; `_map_blue_quote_to_profile` devuelve la 6-tupla usada en Task 3. ✓

**Notas de riesgo:** `extract_all` es grande; los tests de integración usan monkeypatch para aislar las dos fuentes. Verificar en el Step 5 que no haya quedado código muerto referenciando `_extract_blue_quote_with_ai`.
