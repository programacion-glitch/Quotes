"""Integración: el extractor de IA devuelve ExtractionFields y la reconciliación
hace ganar al form."""
from modules.document_ai_extractor import DocumentAIExtractor
from modules.extraction_reconciler import ExtractionFields
from modules.quote_profile import ApplicantProfile, UnitsProfile, DriverProfile


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


def test_ai_fields_vision_fallback(monkeypatch):
    ex = DocumentAIExtractor()

    def fake_content(filename, data, force_vision=False):
        return {"type": "vision"} if force_vision else {"type": "text"}

    def fake_ai(doc_type, content):
        # pass 1 (text) -> sin business_name; pass 2 (vision) -> poblado
        if content.get("type") == "text":
            return {"business_name": ""}
        return {"business_name": "RYD",
                "drivers": [{"name": "A", "exp_years": 3}],
                "unit_count": 1}

    monkeypatch.setattr(ex, "_extract_content", fake_content)
    monkeypatch.setattr(ex, "_extract_ai_document", fake_ai)
    fields = ex._extract_blue_quote_ai_fields({"filename": "BQ.pdf", "data": b"x"})
    assert fields is not None
    assert fields.applicant.business_name == "RYD"
    assert len(fields.drivers) == 1


def test_ai_fields_returns_none_when_no_business_name(monkeypatch):
    ex = DocumentAIExtractor()
    monkeypatch.setattr(ex, "_extract_content", lambda *a, **k: {"type": "text"})
    monkeypatch.setattr(ex, "_extract_ai_document", lambda *a, **k: {"business_name": ""})
    fields = ex._extract_blue_quote_ai_fields({"filename": "BQ.pdf", "data": b"x"})
    assert fields is None


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
