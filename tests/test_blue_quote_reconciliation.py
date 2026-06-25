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
