"""Los adjuntos que se reenvian a negocio tienen que ser los del cliente.

Caso real T&S Logistics (2026-08-06): el correo del agente traia 5 imagenes
inline de la firma. Gmail las entrega a todas con filename 'noname', asi que
_persist_attachments las escribio sobre la MISMA ruta (4 se perdieron) y
devolvio ese path repetido 5 veces. Diana recibio 8 adjuntos, 5 de ellos el
mismo logo de 7 KB: *"al nombrarlo va a causar confusion"*. R-094.
"""
from __future__ import annotations

from workflow_orchestrator import QuoteWorkflowOrchestrator


def _persist(tmp_path, attachments, monkeypatch):
    import workflow_orchestrator as wo
    monkeypatch.setattr(wo, "SUBMISSIONS_DIR", tmp_path)
    return QuoteWorkflowOrchestrator._persist_attachments(
        object.__new__(QuoteWorkflowOrchestrator), "<msg-id@mail>", attachments)


def _att(name, data=b"x" * 100, ctype="application/pdf"):
    return {"filename": name, "data": data, "content_type": ctype}


# --------------------------------------------------------------------------
# Firmas inline: no son documentos del cliente
# --------------------------------------------------------------------------

def test_imagenes_inline_de_firma_no_se_reenvian(tmp_path, monkeypatch):
    paths = _persist(tmp_path, [
        _att("noname", b"\x89PNG" + b"0" * 7000, "image/png"),
        _att("20260805 BLUE QUOTE.pdf"),
    ], monkeypatch)
    assert len(paths) == 1
    assert paths[0].endswith("20260805 BLUE QUOTE.pdf")


def test_las_cinco_firmas_de_ts_desaparecen(tmp_path, monkeypatch):
    """Reproduccion literal del correo de T&S."""
    firmas = [_att("noname", b"\x89PNG" + bytes([i]) * 1000, "image/png")
              for i in range(5)]
    reales = [_att("20260805 DL.pdf"), _att("20260805 BLUE QUOTE.pdf"),
              _att("20260805 BLUE QUOTE 750K AL.pdf")]
    paths = _persist(tmp_path, firmas + reales, monkeypatch)
    assert len(paths) == 3
    assert not any("noname" in p for p in paths)


# --------------------------------------------------------------------------
# Nombres repetidos: no se pueden pisar
# --------------------------------------------------------------------------

def test_nombres_repetidos_no_se_pisan(tmp_path, monkeypatch):
    paths = _persist(tmp_path, [
        _att("BLUE QUOTE.pdf", b"primero"),
        _att("BLUE QUOTE.pdf", b"segundo"),
    ], monkeypatch)
    assert len(paths) == 2
    assert len(set(paths)) == 2, "dos adjuntos distintos, dos rutas distintas"
    contenidos = {open(p, "rb").read() for p in paths}
    assert contenidos == {b"primero", b"segundo"}


def test_documentos_reales_conservan_su_nombre(tmp_path, monkeypatch):
    """El nombre del cliente es informacion: '750K AL' dice el limite pedido."""
    paths = _persist(tmp_path, [_att("20260805 BLUE QUOTE 750K AL.pdf")],
                     monkeypatch)
    assert paths[0].endswith("20260805 BLUE QUOTE 750K AL.pdf")


def test_adjunto_sin_datos_se_ignora(tmp_path, monkeypatch):
    paths = _persist(tmp_path, [{"filename": "vacio.pdf", "data": None}],
                     monkeypatch)
    assert paths == []
