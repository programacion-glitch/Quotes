"""
Catálogo de mensajes humanizados de la cola RPA, dirigidos al AGENTE interno.

Dos capas: la TÉCNICA (status + reason code + detail crudo) vive en DB/logs;
esta capa traduce a español claro, con instrucción de acción/escalamiento,
SIN jerga ni rutas de archivo. El correo de análisis lo lee el agente, no el
cliente final.
"""

from dataclasses import dataclass
from typing import List, Optional


# Marcador que el orquestador deja en el cuerpo del correo (pre-render) y que
# el worker reemplaza por la sección RPA real una vez cotizado.
RPA_SECTION_MARKER = "<!--RPA_QUOTES_SECTION-->"


@dataclass
class RpaQuoteOutcome:
    """Desenlace de una cotización RPA para una MGA (lo que entra al correo)."""
    mga: str
    status: str                      # JobStatus value: quoted/failed/halted/deferred
    reason: str                      # reason code: ok/ok_no_pdf/needs_ssn/not_eligible/pending_retry/error
    premium: Optional[str] = None
    pdf_path: Optional[str] = None
    detail: Optional[str] = None     # detalle técnico — NUNCA se muestra al agente
    decisions: Optional[List[dict]] = None   # entradas del decision_ledger (solo quoted)


def _is_dudosa(d: dict) -> bool:
    """Dudosa = decisión que NO está validada por negocio (RULE) ni es un
    simple mapeo del dato del BlueQuote (MATCHED). Van arriba con ⚠ para
    que negocios las revise primero.

    OJO: los defaults técnicos EN-DUDA (source=DEFAULT) SÍ traen rule_id
    (citan la regla R-0XX que documenta el default en
    config/mga_decision_rules.xlsx), así que `rule_id` presente NO implica
    que la decisión esté validada — solo `source` distingue eso. Fuentes
    conocidas: RULE (regla de negocio con Diana) y MATCHED (mapeo directo
    del BlueQuote, vía choice_resolver o field_mapper) no llevan warning;
    DEFAULT/DEFAULTED (default técnico), AI (clasificador) y HARDCODED
    (sin source explícito) sí."""
    return d.get("source") not in ("RULE", "MATCHED")


def _decisions_table(decisions: List[dict]) -> str:
    """Tabla 'Decisiones tomadas' bajo la fila de una MGA que cotizó."""
    ordered = sorted(decisions, key=lambda d: 0 if _is_dudosa(d) else 1)
    rows = ""
    for d in ordered:
        warn = "&#9888; " if _is_dudosa(d) else ""
        fuente = d.get("rule_id") or d.get("source", "")
        page = f' <span style="color:#8c95a6;">({d["page"]})</span>' if d.get("page") else ""
        rows += (
            f'<tr>'
            f'<td style="padding:4px 8px;font-family:Arial,Helvetica,sans-serif;'
            f'font-size:11px;color:#0a1628;border-top:1px solid #e8eaee;">'
            f'{warn}{d.get("field", "?")}{page}</td>'
            f'<td style="padding:4px 8px;font-family:Arial,Helvetica,sans-serif;'
            f'font-size:11px;font-weight:bold;color:#0a1628;border-top:1px solid #e8eaee;">'
            f'{d.get("chosen", "?")}</td>'
            f'<td style="padding:4px 8px;font-family:Arial,Helvetica,sans-serif;'
            f'font-size:11px;color:#5a6577;border-top:1px solid #e8eaee;">{fuente}</td>'
            f'</tr>'
        )
    return (
        '<p style="margin:8px 0 4px 0;font-family:Arial,Helvetica,sans-serif;'
        'font-size:11px;font-weight:bold;letter-spacing:1px;text-transform:uppercase;'
        'color:#8c95a6;">Decisiones tomadas</p>'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="border:1px solid #e8eaee;border-radius:4px;">'
        '<tr>'
        '<td style="padding:4px 8px;font-family:Arial,Helvetica,sans-serif;font-size:10px;'
        'text-transform:uppercase;color:#8c95a6;">Campo</td>'
        '<td style="padding:4px 8px;font-family:Arial,Helvetica,sans-serif;font-size:10px;'
        'text-transform:uppercase;color:#8c95a6;">Valor</td>'
        '<td style="padding:4px 8px;font-family:Arial,Helvetica,sans-serif;font-size:10px;'
        'text-transform:uppercase;color:#8c95a6;">Fuente</td>'
        '</tr>'
        f'{rows}'
        '</table>'
    )


def humanize(outcome: "RpaQuoteOutcome") -> str:
    """Mensaje claro para el agente. El `detail` técnico nunca se incluye."""
    mga = outcome.mga
    premium = outcome.premium or "(precio no capturado)"
    reason = outcome.reason

    if reason == "ok":
        return f"{mga} cotizó: {premium}. Impresión de la página de precio adjunta."
    if reason == "ok_no_pdf":
        return (f"{mga} cotizó: {premium}. No se pudo generar la impresión esta "
                f"vez; el precio quedó confirmado.")
    if reason == "needs_ssn":
        return (f"{mga} requiere el SSN del titular para verificar su identidad "
                f"antes de cotizar. Acción: solicitar el SSN al cliente y "
                f"reintentar — no se autocompleta por política de seguridad.")
    if reason == "not_eligible":
        return (f"{mga} no puede cotizar este negocio por sus reglas de "
                f"elegibilidad (verificación FMCSA/USDOT). No requiere reintento; "
                f"evaluar un MGA alternativo.")
    if reason == "pending_retry":
        return (f"Cotización de {mga} pendiente (producto no disponible o espera "
                f"de OTP). Se reintentará automáticamente; no requiere acción.")
    # reason == "error" (o desconocido)
    return (f"No se pudo completar la cotización de {mga} automáticamente. "
            f"Acción: revisar manualmente (detalle técnico en los logs internos).")


def _row(outcome: "RpaQuoteOutcome") -> str:
    quoted = outcome.reason in ("ok", "ok_no_pdf")
    accent = "#0d7a3f" if quoted else "#b8860b"
    decisions_html = ""
    if quoted and outcome.decisions:
        decisions_html = _decisions_table(outcome.decisions)
    return (
        f'<tr><td style="padding:12px 16px;border-bottom:1px solid #e8eaee;">'
        f'<p style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:14px;'
        f'font-weight:bold;color:{accent};">{outcome.mga}</p>'
        f'<p style="margin:4px 0 0 0;font-family:Arial,Helvetica,sans-serif;'
        f'font-size:13px;color:#0a1628;line-height:1.5;">{humanize(outcome)}</p>'
        f'{decisions_html}'
        f'</td></tr>'
    )


def render_rpa_section(outcomes: List["RpaQuoteOutcome"]) -> str:
    """Bloque HTML con las cotizaciones RPA, al estilo del resto del correo."""
    if not outcomes:
        return ""
    rows = "".join(_row(o) for o in outcomes)
    return (
        '<tr><td style="padding:8px 32px 4px 32px;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'border="0" style="background-color:#1a5276;border-radius:6px 6px 0 0;">'
        '<tr><td style="padding:14px 20px;">'
        '<p style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:12px;'
        'font-weight:bold;letter-spacing:1.5px;text-transform:uppercase;color:#ffffff;">'
        '&#9679; Cotizaciones automáticas (RPA)</p>'
        '</td></tr></table></td></tr>'
        '<tr><td style="padding:0 32px 20px 32px;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'border="0" style="border:1px solid #bcd2e8;border-top:none;'
        'border-radius:0 0 6px 6px;overflow:hidden;">'
        f'{rows}'
        '</table></td></tr>'
    )
