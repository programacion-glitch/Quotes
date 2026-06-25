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
