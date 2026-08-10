"""Correcciones de Diana 2026-08-10 — las MGAs de plataforma cuentan.

Caso real: T&S Logistics (New Venture, USDOT 9731476). El analisis salio con
"0 ELEGIBLE(S)" y "Ninguna MGA califica para esta cotizacion" mientras, dos
bloques mas arriba, el mismo correo decia que GEICO y PROGRESSIVE eran
"Elegible por reglas". Diana: *"en MGA elegible si aplica con Progressive,
Geico y Berkshire mas sin embargo, no lo toma en cuenta"*.

Berkshire entra al mismo grupo: es plataforma en linea (se cotiza en su portal),
asi que los documentos que se reenvian por correo a las MGAs de email no
pueden bajarla a no elegible. R-093.
"""
from modules.analysis_email_builder import build_analysis_email
from modules.quote_profile import QuoteProfile
from modules.rule_engine import FailedRule, MGAEvaluation


def _profile(**over):
    """Perfil de T&S: New Venture, sin CDL adjunto (llego como 'DL')."""
    p = QuoteProfile()
    p.applicant.business_name = "T&S Logistics"
    p.applicant.usdot = "9731476"
    p.applicant.is_new_venture = True
    p.documents_present = ["BLUE QUOTE"]
    for k, v in over.items():
        setattr(p.applicant, k, v)
    return p


def _build(evaluations, mga_list=None, profile=None):
    names = [{"mga": ev.mga_name} for ev in evaluations]
    return build_analysis_email(
        profile=profile or _profile(), commodity="CANNED GOODS",
        tipo_negocio="DRY VAN / REEFER", evaluations=evaluations,
        mga_list=mga_list if mga_list is not None else names,
        original_subject="Submission New venture /T&S Logistics",
    )


def _web(name):
    return MGAEvaluation(mga_name=name, eligible=True)


# --------------------------------------------------------------------------
# El encabezado no puede decir 0 cuando hay portales elegibles
# --------------------------------------------------------------------------

def test_web_mgas_cuentan_en_el_total():
    out = _build([_web("PROGRESSIVE"), _web("GEICO")])
    assert "2 ELEGIBLE(S)" in out["body"]


def test_no_dice_ninguna_mga_califica_si_hay_portales():
    out = _build([_web("PROGRESSIVE"), _web("GEICO")])
    assert "Ninguna MGA califica" not in out["body"]


def test_web_mga_no_elegible_no_suma():
    """Si el rule engine tumba el portal, no puede contarse como elegible."""
    caido = MGAEvaluation(
        mga_name="PROGRESSIVE", eligible=False,
        failed_rules=[FailedRule("ALLOWED_COVERAGES", "Cobertura no aceptada: AL")],
    )
    out = _build([caido])
    assert "0 ELEGIBLE(S)" in out["body"]


def test_bloque_de_mgas_web_sigue_existiendo():
    """El bloque explicativo previo no se pierde al empezar a contarlas."""
    out = _build([_web("PROGRESSIVE"), _web("GEICO")])
    assert "MGAs Web" in out["body"]


# --------------------------------------------------------------------------
# Berkshire: plataforma en linea, no MGA de correo
# --------------------------------------------------------------------------

def test_berkshire_no_se_cae_por_documentos_de_correo():
    """Sin CDL adjunto, una MGA de email cae; una plataforma no: los
    documentos se cargan en el portal, no se reenvian."""
    out = _build([MGAEvaluation(mga_name="BERKSHIRE", eligible=True)])
    assert "1 ELEGIBLE(S)" in out["body"]


def test_berkshire_se_muestra_como_plataforma():
    out = _build([MGAEvaluation(mga_name="BERKSHIRE", eligible=True)])
    assert "plataforma" in out["body"].lower()


def test_mga_de_correo_si_se_cae_sin_cdl():
    """Contraprueba: el guard de documentos sigue vivo para las de correo."""
    out = _build([MGAEvaluation(mga_name="ROCKLAKE", eligible=True)])
    assert "0 ELEGIBLE(S)" in out["body"]
