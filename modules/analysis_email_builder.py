"""
Analysis Email Builder

Builds the pre-dispatch HTML summary email with full MGA eligibility analysis.
"""

from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime

from modules.quote_profile import QuoteProfile
from modules.rule_engine import MGAEvaluation, FailedRule


def _baseline_missing_docs(profile: QuoteProfile) -> List[FailedRule]:
    """
    Return the list of baseline document failures for the profile.

    Required docs for ANY MGA to receive an email submission:
      - CDL: always required (even for NV - the owner-driver still needs it)
      - MVR: required only for established businesses (NV has no driving history)
      - Loss Run: required only for established businesses (NV has no losses)

    Returns empty list if all baseline docs are present.
    """
    failures: List[FailedRule] = []
    docs = {d.upper() for d in profile.documents_present}
    is_nv = profile.applicant.is_new_venture

    if "CDL" not in docs:
        failures.append(FailedRule("REQUIRES_CDL", "Falta documento: CDL"))
    if "MVR" not in docs and not is_nv:
        failures.append(FailedRule("REQUIRES_MVR", "Falta documento: MVR"))
    if "LOSS RUN" not in docs and not is_nv:
        failures.append(FailedRule("REQUIRES_LOSS_RUN", "Falta documento: Loss Run"))
    return failures


def _baseline_eval_for_no_rules(mga_name: str, profile: QuoteProfile) -> MGAEvaluation:
    """
    Build an MGAEvaluation for an MGA that has NO specific REGLAS rows,
    applying only baseline document requirements.
    """
    failures = _baseline_missing_docs(profile)
    return MGAEvaluation(
        mga_name=mga_name,
        eligible=(len(failures) == 0),
        failed_rules=failures,
    )


def _apply_baseline_to_eligible(ev: MGAEvaluation, profile: QuoteProfile) -> MGAEvaluation:
    """
    If an MGA passed rule engine but baseline docs are missing, downgrade it
    to ineligible with the corresponding FailedRules appended. This ensures
    'Eligible' in the analysis email always means 'can actually receive an email'.
    """
    if not ev.eligible:
        return ev
    missing = _baseline_missing_docs(profile)
    if not missing:
        return ev
    # Avoid duplicating FailedRules that the rule engine already added
    existing_rules = {fr.rule for fr in ev.failed_rules}
    new_failures = [fr for fr in missing if fr.rule not in existing_rules]
    return MGAEvaluation(
        mga_name=ev.mga_name,
        eligible=False,
        passed_rules=ev.passed_rules,
        failed_rules=ev.failed_rules + new_failures,
        warnings=ev.warnings,
        informational=ev.informational,
    )


def _is_only_missing_docs(ev: MGAEvaluation) -> bool:
    """
    True if EVERY failed_rule on this evaluation is about a missing document
    (reason starts with 'Falta'). Used to route these MGAs to the 'fixes'
    section instead of the 'no elegibles' list.
    """
    if not ev.failed_rules:
        return False
    return all(
        (fr.reason or "").strip().lower().startswith("falta")
        for fr in ev.failed_rules
    )

TEMPLATE_PATH = Path(__file__).parent.parent / "config" / "templates" / "analysis_email.html"


def _badge(text: str, bg: str = "#e8eaee", color: str = "#0a1628") -> str:
    """Generate an inline-styled badge span for email."""
    return (
        f'<span style="display:inline-block;background-color:{bg};color:{color};'
        f'font-family:Arial,Helvetica,sans-serif;font-size:11px;font-weight:bold;'
        f'padding:4px 10px;border-radius:3px;margin:2px 4px 2px 0;letter-spacing:0.5px;">'
        f'{text}</span>'
    )


def _doc_row(name: str, present: bool) -> str:
    """Generate a document checklist row."""
    if present:
        icon = '<span style="color:#0d7a3f;font-size:16px;">&#10003;</span>'
        style = "color:#0a1628;"
    else:
        icon = '<span style="color:#c4291c;font-size:16px;">&#10007;</span>'
        style = "color:#c4291c;font-weight:bold;"
    return (
        f'<tr><td width="28" style="padding:6px 0 6px 4px;{style}">{icon}</td>'
        f'<td style="padding:6px 8px;font-family:Arial,Helvetica,sans-serif;font-size:13px;{style}">{name}</td></tr>'
    )


def _driver_row(name: str, cdl_years, mvr_years, cdl_doc_missing: bool = False) -> str:
    """Generate a driver info row.

    If cdl_doc_missing is True and the driver has cdl_years (from BlueQuote),
    mark the CDL cell with an amber * to indicate the value came from fallback.
    """
    cdl_text = str(cdl_years) if cdl_years is not None else "?"
    if cdl_doc_missing and cdl_years is not None:
        cdl_cell = (
            f'<span style="color:#b8860b;">{cdl_text}<span title="Tomado del Blue Quote - falta CDL">*</span></span>'
        )
    else:
        cdl_cell = cdl_text
    mvr = str(mvr_years) if mvr_years is not None else "?"
    return (
        f'<tr>'
        f'<td style="padding:10px 12px;font-family:Arial,Helvetica,sans-serif;font-size:13px;color:#0a1628;border-top:1px solid #e8eaee;">{name}</td>'
        f'<td align="center" style="padding:10px 12px;font-family:Arial,Helvetica,sans-serif;font-size:14px;font-weight:bold;color:#0a1628;border-top:1px solid #e8eaee;">{cdl_cell}</td>'
        f'<td align="center" style="padding:10px 12px;font-family:Arial,Helvetica,sans-serif;font-size:14px;font-weight:bold;color:#0a1628;border-top:1px solid #e8eaee;">{mvr}</td>'
        f'</tr>'
    )


def _warnings_banner(html_warnings: list) -> str:
    """Build the top-of-email warnings banner. Empty string if no warnings."""
    if not html_warnings:
        return ""
    rows = "".join(
        f'<p style="margin:0 0 6px 0;font-family:Arial,Helvetica,sans-serif;font-size:13px;color:#8a5a00;line-height:1.5;">&#9888; {w}</p>'
        for w in html_warnings
    )
    return (
        '<tr>'
        '<td style="padding:18px 32px;background-color:#fff8e1;border-bottom:1px solid #f0deb0;">'
        f'{rows}'
        '</td>'
        '</tr>'
    )


def _eligible_row(ev: MGAEvaluation) -> str:
    """Generate an eligible MGA row."""
    lines = [
        f'<tr style="background-color:#f0faf4;">',
        f'<td style="padding:12px 16px;border-bottom:1px solid #c6e9d2;">',
        f'<p style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:14px;font-weight:bold;color:#0d7a3f;">{ev.mga_name}</p>',
    ]
    # Warnings
    for w in ev.warnings:
        lines.append(
            f'<p style="margin:4px 0 0 0;font-family:Arial,Helvetica,sans-serif;font-size:11px;color:#b8860b;">'
            f'&#9888; {w}</p>'
        )
    # Informational
    info_parts = []
    info = ev.informational or {}
    if info.get("routing"):
        info_parts.append(f"Ruta: {info['routing']}")
    if info.get("down_payment_pct"):
        info_parts.append(f"Enganche: {info['down_payment_pct']}%")
    if info.get("min_price"):
        info_parts.append(f"Precio min: ${info['min_price']:,}")
    if info.get("special_form"):
        info_parts.append(f"Formulario: {info['special_form']}")
    if info.get("notas_extra"):
        note = str(info['notas_extra'])[:100]
        info_parts.append(note)
    if info_parts:
        lines.append(
            f'<p style="margin:4px 0 0 0;font-family:Arial,Helvetica,sans-serif;font-size:11px;color:#5a6577;">'
            f'{" | ".join(info_parts)}</p>'
        )
    lines.append('</td></tr>')
    return "\n".join(lines)


def _ineligible_row(ev: MGAEvaluation) -> str:
    """Generate an ineligible MGA row."""
    lines = [
        f'<tr style="background-color:#fdf5f4;">',
        f'<td style="padding:12px 16px;border-bottom:1px solid #f0c6c3;">',
        f'<p style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:14px;font-weight:bold;color:#c4291c;">{ev.mga_name}</p>',
    ]
    for fr in ev.failed_rules:
        lines.append(
            f'<p style="margin:4px 0 0 0;font-family:Arial,Helvetica,sans-serif;font-size:12px;color:#5a6577;">'
            f'&#8226; {fr.reason}</p>'
        )
    lines.append('</td></tr>')
    return "\n".join(lines)


def _fix_row(fix: str, mgas: List[str]) -> str:
    """Generate a 'what's needed' fix row."""
    mga_text = ", ".join(mgas)
    return (
        f'<tr style="background-color:#fffbf0;">'
        f'<td style="padding:12px 16px;border-bottom:1px solid #f0deb0;">'
        f'<p style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:13px;color:#0a1628;font-weight:bold;">'
        f'&#8594; {fix}</p>'
        f'<p style="margin:3px 0 0 0;font-family:Arial,Helvetica,sans-serif;font-size:11px;color:#8c95a6;">'
        f'Desbloquea: {mga_text}</p>'
        f'</td></tr>'
    )


def _no_data_row(message: str, bg: str = "#f7f8fa", border: str = "#e8eaee") -> str:
    """Placeholder row when no data."""
    return (
        f'<tr style="background-color:{bg};">'
        f'<td style="padding:14px 16px;border-bottom:1px solid {border};">'
        f'<p style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:13px;color:#8c95a6;font-style:italic;">{message}</p>'
        f'</td></tr>'
    )


def build_analysis_email(
    profile: QuoteProfile,
    commodity: str,
    tipo_negocio: str,
    evaluations: List[MGAEvaluation],
    mga_list: List[Dict[str, str]],
    original_subject: str,
    confirmation_keyword: str = "APROBAR",
) -> Dict[str, str]:
    """
    Build HTML analysis summary email for human review before MGA dispatch.

    Returns dict with 'subject' and 'body'.
    """
    # Filter strategy:
    #   - Hide MGAs that failed by IS_NEW_VENTURE only when it's a CATEGORICAL
    #     mismatch (MGA only takes NV but business is established) — years are
    #     irrelevant there, so showing it adds noise.
    #   - SHOW MGAs that failed because of business YEARS, even if the failure
    #     is reported as IS_NEW_VENTURE (e.g. "Requiere minimo 2 ano(s)...") —
    #     these tell the user when the business would become eligible.
    def _should_hide(ev: MGAEvaluation) -> bool:
        for fr in ev.failed_rules:
            if fr.rule != "IS_NEW_VENTURE":
                continue
            reason = (fr.reason or "").lower()
            # Year-based rejections stay visible (contain digits/"ano" or "minimo")
            if any(tok in reason for tok in ("minimo", "ano", "año", "year")):
                return False
            # Pure "solo aplica para New Venture" → hide
            if "solo aplica para new venture" in reason or "new_venture" in reason:
                return True
        return False

    relevant = [ev for ev in evaluations if not _should_hide(ev)]

    # MGAs listed in the MGA sheet but without specific REGLAS rows for the
    # current tipo_negocio: apply BASELINE document requirements (MVR/CDL/Loss Run)
    # instead of showing them as "approved by default".
    evaluated_names = {ev.mga_name for ev in evaluations}
    no_rules_mgas = [m for m in mga_list if m['mga'] not in evaluated_names]
    baseline_evals = [
        _baseline_eval_for_no_rules(m['mga'], profile) for m in no_rules_mgas
    ]
    relevant += baseline_evals

    # SAFETY NET: even MGAs that passed all REGLAS rules can't actually receive
    # an email without the baseline documents (CDL always; MVR/Loss Run unless NV).
    # Downgrade any "eligible" MGA that's missing those docs.
    relevant = [_apply_baseline_to_eligible(ev, profile) for ev in relevant]

    # CURRENT CARRIER filter: if the Blue Quote lists a current_carrier, that MGA
    # is already insuring the client — we cannot offer them again.
    current_carrier_norm = (profile.applicant.current_carrier or "").strip().upper()

    def _is_current_carrier(mga_name: str) -> bool:
        if not current_carrier_norm:
            return False
        n = (mga_name or "").strip().upper()
        return current_carrier_norm in n or n in current_carrier_norm

    current_carrier_hits = [ev for ev in relevant if _is_current_carrier(ev.mga_name)]
    relevant = [ev for ev in relevant if not _is_current_carrier(ev.mga_name)]

    eligible = [ev for ev in relevant if ev.eligible]
    ineligible_all = [ev for ev in relevant if not ev.eligible]

    # Split ineligibles: those failing ONLY by missing docs go to the "fixes"
    # section only; the rest show up in the "no elegibles" list as before.
    ineligible = [ev for ev in ineligible_all if not _is_only_missing_docs(ev)]
    missing_docs_only = [ev for ev in ineligible_all if _is_only_missing_docs(ev)]
    no_rules = []  # no longer shown as "approved by default"

    # Load template
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    # -- Coverages badges --
    cov_colors = {"AL": "#1a5276", "MTC": "#6c3483", "APD": "#0e6655", "GL": "#b8860b"}
    coverages_badges = ""
    for cov in (profile.coverages or []):
        bg = cov_colors.get(cov.upper(), "#5a6577")
        coverages_badges += _badge(cov.upper(), bg=bg, color="#ffffff")
    if not coverages_badges:
        coverages_badges = '<span style="font-family:Arial,sans-serif;font-size:13px;color:#8c95a6;">N/A</span>'

    # -- Documents --
    expected = ["BLUE QUOTE", "MVR", "CDL", "IFTAS", "LOSS RUN", "NEW VENTURE APP"]
    docs_present = [d.upper() for d in profile.documents_present]
    documents_rows = ""
    for doc in expected:
        documents_rows += _doc_row(doc, doc in docs_present)

    cdl_missing = "CDL" not in docs_present
    cdl_has_fallback = cdl_missing and any(
        drv.cdl_years is not None for drv in (profile.drivers or [])
    )

    # -- Drivers --
    drivers_rows = ""
    if profile.drivers:
        for drv in profile.drivers:
            drivers_rows += _driver_row(
                drv.name or "Sin nombre",
                drv.cdl_years,
                drv.mvr_years_covered,
                cdl_doc_missing=cdl_missing,
            )
    else:
        drivers_rows = _no_data_row("Sin informacion de conductores")

    # -- Warnings banner --
    warnings_list = []
    if cdl_missing and cdl_has_fallback:
        warnings_list.append(
            "<strong>Falta CDL</strong> &mdash; requerido para la cotizacion final "
            "con los MGAs. Los anos del conductor se tomaron del Blue Quote "
            "(marcados con <span style=\"color:#b8860b;\">*</span> en la tabla)."
        )
    elif cdl_missing:
        warnings_list.append(
            "<strong>Falta CDL</strong> &mdash; requerido para la cotizacion final con los MGAs."
        )
    if current_carrier_norm:
        hit_names = ", ".join(ev.mga_name for ev in current_carrier_hits) if current_carrier_hits else "ninguna coincidencia"
        warnings_list.append(
            f"<strong>Carrier actual:</strong> {profile.applicant.current_carrier} &mdash; "
            f"excluido(s) del analisis para no ofrecer la misma compa&ntilde;&iacute;a: {hit_names}."
        )
    warnings_banner = _warnings_banner(warnings_list)

    # -- Loss Run --
    if profile.loss_run.present:
        lr_years = profile.loss_run.years_covered or "?"
        lr_status = "Limpio (sin reclamos)" if profile.loss_run.is_clean else "Con reclamos"
        loss_run_summary = f"{lr_years} ano(s) cubiertos &mdash; {lr_status}"
    elif profile.applicant.is_new_venture:
        loss_run_summary = '<span style="color:#666;">No aplica (New Venture)</span>'
    else:
        loss_run_summary = '<span style="color:#c4291c;font-weight:bold;">No recibido</span>'

    # -- Eligible rows --
    eligible_rows = ""
    for ev in eligible:
        eligible_rows += _eligible_row(ev)
    for m in no_rules:
        eligible_rows += (
            f'<tr style="background-color:#f0faf4;">'
            f'<td style="padding:12px 16px;border-bottom:1px solid #c6e9d2;">'
            f'<p style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:14px;font-weight:bold;color:#0d7a3f;">{m["mga"]}</p>'
            f'<p style="margin:2px 0 0 0;font-family:Arial,Helvetica,sans-serif;font-size:11px;color:#5a6577;">Sin reglas definidas &mdash; aprobado por defecto</p>'
            f'</td></tr>'
        )
    if not eligible and not no_rules:
        eligible_rows = _no_data_row("Ninguna MGA califica para esta cotizacion", bg="#f0faf4", border="#c6e9d2")

    # -- Ineligible rows --
    ineligible_rows = ""
    for ev in ineligible:
        ineligible_rows += _ineligible_row(ev)
    if not ineligible:
        ineligible_rows = _no_data_row("Todas las MGAs califican", bg="#fdf5f4", border="#f0c6c3")

    # -- Fixes (what's needed to unblock) --
    # ONLY include MGAs that are blocked purely by missing documents — those are
    # the ones that can actually be unlocked by providing the file. MGAs that
    # also fail by years/commodity/etc stay in the "No Elegibles" list because
    # no amount of documents will unlock them.
    fix_map = {}
    for ev in missing_docs_only:
        for fr in ev.failed_rules:
            reason = (fr.reason or "").strip()
            if not reason.lower().startswith("falta"):
                continue
            if reason not in fix_map:
                fix_map[reason] = []
            if ev.mga_name not in fix_map[reason]:
                fix_map[reason].append(ev.mga_name)

    fixes_rows = ""
    if fix_map:
        sorted_fixes = sorted(fix_map.items(), key=lambda x: len(x[1]), reverse=True)
        for fix, mgas in sorted_fixes:
            fixes_rows += _fix_row(fix, mgas)
    else:
        fixes_rows = _no_data_row("No hay MGAs pendientes por desbloquear", bg="#fffbf0", border="#f0deb0")

    # -- NV color --
    nv_color = "#c4291c" if profile.applicant.is_new_venture else "#0d7a3f"

    # -- Render template --
    body = template.format(
        warnings_banner=warnings_banner,
        business_name=profile.applicant.business_name or "N/A",
        owner_name=profile.applicant.owner_name or "N/A",
        usdot=profile.applicant.usdot or "N/A",
        business_years=profile.applicant.business_years if profile.applicant.business_years is not None else "N/A",
        is_new_venture="SI" if profile.applicant.is_new_venture else "NO",
        nv_color=nv_color,
        unit_count=profile.units.count,
        commodity=commodity or "N/A",
        tipo_negocio=tipo_negocio or "N/A",
        coverages_badges=coverages_badges,
        documents_rows=documents_rows,
        drivers_rows=drivers_rows,
        loss_run_summary=loss_run_summary,
        eligible_count=len(eligible) + len(no_rules),
        eligible_rows=eligible_rows,
        ineligible_count=len(ineligible),
        ineligible_rows=ineligible_rows,
        fixes_rows=fixes_rows,
        confirmation_keyword=confirmation_keyword,
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )

    subject = f"[ANALISIS] {original_subject}"

    return {"subject": subject, "body": body, "is_html": True}
