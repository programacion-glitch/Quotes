# Rule Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add AI-powered document extraction + deterministic rule engine to pre-filter which MGAs are eligible for each quote.

**Architecture:** AI extracts structured data from 5 document types (MVR, CDL, IFTAS, Loss Run, APP) via GPT-5.4 local proxy. Blue Quote uses existing `BlueQuotePDFExtractor`. A rule engine reads structured columns from a new REGLAS Excel sheet and evaluates the quote profile deterministically.

**Tech Stack:** Python 3.x, OpenAI SDK (via localhost:3000 proxy), pdfplumber, pymupdf (fitz), openpyxl, Pillow

**Spec:** `docs/superpowers/specs/2026-03-25-rule-engine-design.md`

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| CREATE | `modules/document_ai_extractor.py` | Classify documents, extract data via AI, build Quote Profile JSON |
| CREATE | `modules/rule_engine.py` | Read REGLAS sheet, evaluate profile vs rules, return eligible/ineligible MGAs |
| CREATE | `tests/test_rule_engine.py` | Unit tests for rule engine |
| CREATE | `tests/test_document_ai_extractor.py` | Unit tests for extractor (mocked AI) |
| CREATE | `scripts/migrate_rules.py` | One-time script: convert COMENTARIOS → REGLAS sheet via AI |
| MODIFY | `workflow_orchestrator.py` | Wire in extractor + rule engine between steps 2-5 |
| MODIFY | `modules/attachment_validator.py` | Add `classify_attachments()` method for document type detection |
| MODIFY | `config/settings.yaml` | Add `rule_engine` and `ai_extraction` config sections |
| MODIFY | `requirements.txt` | Add pymupdf, Pillow, openai |
| MODIFY | `modules/__init__.py` | Export new modules |

---

## Task 1: Update Dependencies

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add new dependencies**

```
# PDF Processing
pdfplumber>=0.9.0

# Excel Processing
openpyxl>=3.1.0

# Configuration Management
PyYAML>=6.0
python-dotenv>=1.0.0

# AI Extraction
openai>=1.0.0
PyMuPDF>=1.23.0
Pillow>=10.0.0
```

- [ ] **Step 2: Install dependencies**

Run: `pip install -r requirements.txt`

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "deps: add openai, pymupdf, pillow for AI document extraction"
```

---

## Task 2: Add Config Settings

**Files:**
- Modify: `config/settings.yaml`

- [ ] **Step 1: Add AI extraction and rule engine sections**

Append after the `workflow:` section at the end of `config/settings.yaml`:

```yaml
# ============================================================================
# AI DOCUMENT EXTRACTION
# ============================================================================
ai_extraction:
  # Proxy settings (credentials from .env: OPENAI_BASE_URL, OPENAI_API_KEY)
  model: "gpt-4o"
  timeout_seconds: 60
  max_retries: 3
  retry_delay_seconds: 5
  # Minimum text chars from PDF before falling back to vision
  min_text_threshold: 50

# ============================================================================
# RULE ENGINE
# ============================================================================
rule_engine:
  # Excel sheet name for structured rules
  sheet_name: "REGLAS"
  # Enable/disable rule evaluation
  enabled: true
  # Halt workflow when AI extraction confidence is low
  halt_on_low_confidence: true
```

- [ ] **Step 2: Commit**

```bash
git add config/settings.yaml
git commit -m "config: add ai_extraction and rule_engine settings"
```

---

## Task 3: Quote Profile Data Model

**Files:**
- Create: `modules/quote_profile.py`

- [ ] **Step 1: Create dataclasses for Quote Profile**

```python
"""
Quote Profile Data Model

Standardized data structure for all extracted document data.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict


@dataclass
class DriverProfile:
    """Data extracted for a single driver."""
    name: str = ""
    cdl_present: bool = False
    cdl_years: Optional[int] = None
    cdl_class: Optional[str] = None
    cdl_is_residential: bool = False
    mvr_present: bool = False
    mvr_years_covered: Optional[int] = None
    mvr_is_clean: bool = False


@dataclass
class LossRunProfile:
    """Data extracted from Loss Run document."""
    present: bool = False
    years_covered: Optional[int] = None
    is_clean: bool = False
    total_claims: int = 0


@dataclass
class IftasProfile:
    """Data extracted from IFTAS document."""
    present: bool = False
    is_registered: bool = False


@dataclass
class AppProfile:
    """Data extracted from New Venture Application."""
    present: bool = False
    ein_included: bool = False
    questions_filled: bool = False


@dataclass
class ApplicantProfile:
    """Applicant info from Blue Quote."""
    business_name: str = ""
    owner_name: str = ""
    owner_age: Optional[int] = None
    usdot: str = ""
    business_years: Optional[int] = None
    is_new_venture: bool = True
    industry_experience_years: Optional[int] = None


@dataclass
class UnitsProfile:
    """Vehicle/trailer info."""
    count: int = 0
    trailer_types: List[str] = field(default_factory=list)


@dataclass
class ConfidenceFlag:
    """A flag indicating extraction uncertainty."""
    field: str
    reason: str


@dataclass
class ExtractionConfidence:
    """Overall extraction confidence."""
    overall: str = "high"  # "high" or "low"
    flags: List[ConfidenceFlag] = field(default_factory=list)


@dataclass
class QuoteProfile:
    """Complete quote profile assembled from all 6 documents."""
    applicant: ApplicantProfile = field(default_factory=ApplicantProfile)
    commodity: str = ""
    coverages: List[str] = field(default_factory=list)
    units: UnitsProfile = field(default_factory=UnitsProfile)
    drivers: List[DriverProfile] = field(default_factory=list)
    loss_run: LossRunProfile = field(default_factory=LossRunProfile)
    iftas: IftasProfile = field(default_factory=IftasProfile)
    app: AppProfile = field(default_factory=AppProfile)
    documents_present: List[str] = field(default_factory=list)
    extraction_confidence: ExtractionConfidence = field(default_factory=ExtractionConfidence)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        from dataclasses import asdict
        return asdict(self)
```

- [ ] **Step 2: Commit**

```bash
git add modules/quote_profile.py
git commit -m "feat: add QuoteProfile data model for standardized extraction output"
```

---

## Task 4: Document AI Extractor — Core

**Files:**
- Create: `modules/document_ai_extractor.py`

- [ ] **Step 1: Create extractor with document classification and content detection**

```python
"""
Document AI Extractor

Extracts structured data from insurance documents (MVR, CDL, IFTAS, Loss Run, APP)
using GPT-5.4 via local proxy. Blue Quote uses existing BlueQuotePDFExtractor.
"""

import json
import base64
import time
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import fitz  # pymupdf
import pdfplumber
import openai

from modules.config_manager import get_config
from modules.pdf_extractor import BlueQuotePDFExtractor
from modules.attachment_validator import AttachmentValidator
from modules.quote_profile import (
    QuoteProfile, ApplicantProfile, DriverProfile, LossRunProfile,
    IftasProfile, AppProfile, UnitsProfile, ExtractionConfidence, ConfidenceFlag
)


# Document type constants
DOC_TYPES = ["BLUE QUOTE", "MVR", "CDL", "IFTAS", "LOSS RUN", "NEW VENTURE APP"]

# System prompts per document type — each requests specific fields as JSON
EXTRACTION_PROMPTS = {
    "CDL": """You are an expert at reading Commercial Driver License (CDL) documents.
Extract the following fields from this document and return ONLY valid JSON, no extra text:
{
  "driver_name": "string",
  "issue_date": "YYYY-MM-DD or null",
  "cdl_years": integer (years since issue_date to today, or null),
  "cdl_class": "A, B, or C",
  "state": "two-letter state code",
  "is_residential": true/false (true if address shows residential)
}
If a field cannot be determined, use null.""",

    "MVR": """You are an expert at reading Motor Vehicle Records (MVR).
Extract the following fields and return ONLY valid JSON, no extra text:
{
  "driver_name": "string",
  "years_covered": integer (how many years the report covers),
  "violations": ["list of violation descriptions"] or [],
  "is_clean": true/false (true if no violations or accidents)
}
If a field cannot be determined, use null.""",

    "LOSS RUN": """You are an expert at reading insurance Loss Run reports.
Extract the following fields and return ONLY valid JSON, no extra text:
{
  "years_covered": integer (how many years the report covers),
  "has_losses": true/false,
  "is_clean": true/false (true if no claims),
  "total_claims": integer
}
If a field cannot be determined, use null.""",

    "IFTAS": """You are an expert at reading IFTA (International Fuel Tax Agreement) documents.
Extract the following fields and return ONLY valid JSON, no extra text:
{
  "is_registered": true/false,
  "state": "two-letter state code or null"
}
If a field cannot be determined, use null.""",

    "NEW VENTURE APP": """You are an expert at reading New Venture insurance applications.
Extract the following fields and return ONLY valid JSON, no extra text:
{
  "ein": "EIN number string or null",
  "industry_experience_years": integer or null,
  "additional_questions_filled": true/false
}
If a field cannot be determined, use null.""",

    "BLUE QUOTE": """You are an expert at reading Commercial Auto Quote Sheet (Blue Quote) PDFs.
Extract the following fields and return ONLY valid JSON, no extra text:
{
  "business_name": "string",
  "owner_name": "string",
  "owner_age": integer or null,
  "usdot": "string",
  "business_years": integer or null,
  "commodity": "string (the commodities field)",
  "coverages": ["AL", "MTC", "APD", "GL"] (list of coverage codes found),
  "unit_count": integer,
  "trailer_types": ["DRY VAN", "END DUMP", etc.],
  "is_new_venture": true/false,
  "drivers": [{"name": "string", "age": integer or null, "exp_years": integer or null}]
}
If a field cannot be determined, use null."""
}


class DocumentAIExtractor:
    """Extracts structured data from insurance documents using AI."""

    def __init__(self):
        config = get_config()
        self.client = openai.OpenAI(
            base_url=config.openai_base_url,
            api_key=config.openai_api_key
        )
        self.model = config.get("ai_extraction.model", "gpt-4o")
        self.timeout = config.get("ai_extraction.timeout_seconds", 60)
        self.max_retries = config.get("ai_extraction.max_retries", 3)
        self.retry_delay = config.get("ai_extraction.retry_delay_seconds", 5)
        self.min_text_threshold = config.get("ai_extraction.min_text_threshold", 50)
        self.validator = AttachmentValidator()

    # ---- Document Classification ----

    def classify_attachment(self, filename: str, data: bytes) -> Optional[str]:
        """
        Determine document type. Filename matching first, AI fallback.

        Returns one of DOC_TYPES or None.
        """
        # 1. Filename matching (reuse existing logic)
        for doc_type in DOC_TYPES:
            if self.validator._matches_document(filename, doc_type):
                return doc_type

        # Check APP variants
        if self.validator._matches_app_invo(filename):
            return "NEW VENTURE APP"
        if self.validator._matches_app_general(filename):
            return "NEW VENTURE APP"

        # 2. AI fallback: send first page to classify
        content = self._extract_content(filename, data)
        if not content:
            return None

        prompt = (
            "This insurance document is one of: BLUE QUOTE, MVR, CDL, IFTAS, LOSS RUN, NEW VENTURE APP. "
            "Which one is it? Return ONLY the document type name, nothing else."
        )
        result = self._call_ai(prompt, content)
        if result:
            result_upper = result.strip().upper()
            for dt in DOC_TYPES:
                if dt in result_upper:
                    return dt
        return None

    # ---- Content Extraction ----

    def _extract_content(self, filename: str, data: bytes) -> Optional[dict]:
        """
        Extract content from file, returning either text or base64 image.

        Returns: {"type": "text", "text": "..."} or {"type": "image", "base64": "...", "mime": "..."}
        """
        ext = Path(filename).suffix.lower()

        if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
            mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "gif": "gif", "webp": "webp"}
            mime_type = mime.get(ext.lstrip("."), "png")
            b64 = base64.b64encode(data).decode("utf-8")
            return {"type": "image", "base64": b64, "mime": f"image/{mime_type}"}

        if ext == ".pdf":
            # Try text extraction first
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(data)
                tmp_path = tmp.name

            try:
                text = ""
                with pdfplumber.open(tmp_path) as pdf:
                    for page in pdf.pages[:3]:  # First 3 pages max
                        page_text = page.extract_text() or ""
                        text += page_text + "\n"

                if len(text.strip()) >= self.min_text_threshold:
                    return {"type": "text", "text": text.strip()}

                # Fallback: convert first page to image
                doc = fitz.open(tmp_path)
                page = doc[0]
                pix = page.get_pixmap(dpi=200)
                img_bytes = pix.tobytes("png")
                doc.close()
                b64 = base64.b64encode(img_bytes).decode("utf-8")
                return {"type": "image", "base64": b64, "mime": "image/png"}
            finally:
                Path(tmp_path).unlink(missing_ok=True)

        return None

    # ---- AI Call ----

    def _call_ai(self, system_prompt: str, content: dict) -> Optional[str]:
        """
        Call GPT-5.4 via proxy with text or image content. Retries on failure.
        """
        if content["type"] == "text":
            user_content = content["text"]
        else:
            user_content = [
                {"type": "text", "text": "Extract the requested data from this document."},
                {"type": "image_url", "image_url": {
                    "url": f"data:{content['mime']};base64,{content['base64']}"
                }}
            ]

        for attempt in range(self.max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content}
                    ],
                    temperature=0.0
                )
                return response.choices[0].message.content.strip()
            except Exception as e:
                print(f"    AI call attempt {attempt + 1}/{self.max_retries} failed: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
        return None

    def _parse_ai_json(self, raw: str) -> Optional[dict]:
        """Parse JSON from AI response, handling markdown fences."""
        if not raw:
            return None
        # Strip markdown code fences
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return None

    # ---- Per-Document Extraction ----

    def _extract_ai_document(self, doc_type: str, content: dict) -> Optional[dict]:
        """Extract data from a single document using AI."""
        prompt = EXTRACTION_PROMPTS.get(doc_type)
        if not prompt:
            return None
        raw = self._call_ai(prompt, content)
        result = self._parse_ai_json(raw)
        if result is None and raw:
            # Retry once with explicit JSON instruction
            retry_prompt = prompt + "\n\nIMPORTANT: Return ONLY valid JSON. No markdown, no explanation."
            raw = self._call_ai(retry_prompt, content)
            result = self._parse_ai_json(raw)
        return result

    # ---- Blue Quote: Existing Extractor → Profile Mapping ----

    def _map_blue_quote_to_profile(self, extracted: dict) -> Tuple[ApplicantProfile, str, List[str], UnitsProfile, List[DriverProfile]]:
        """Map BlueQuotePDFExtractor output to profile components."""
        app_info = extracted.get("applicant_info", {})

        # Applicant
        years_raw = app_info.get("years_in_business")
        business_years = None
        if years_raw:
            try:
                business_years = int(str(years_raw).strip())
            except (ValueError, TypeError):
                pass

        applicant = ApplicantProfile(
            business_name=app_info.get("business_name") or "",
            owner_name=app_info.get("owners_name") or "",
            usdot=app_info.get("usdot") or "",
            business_years=business_years,
            is_new_venture=business_years is None or business_years == 0,
        )

        # Commodity
        commodity = app_info.get("commodities") or ""

        # Coverages — map from checkbox booleans to list
        cov_data = extracted.get("coverages", {})
        coverages = []
        if cov_data.get("auto_liability_limits"):
            coverages.append("AL")
        if cov_data.get("general_liability"):
            coverages.append("GL")
        if cov_data.get("cargo_limit"):
            coverages.append("MTC")
        if cov_data.get("physical_damage_deductible"):
            coverages.append("APD")

        # Units
        vehicles = extracted.get("vehicles", {})
        trucks = vehicles.get("tractors_trucks_pickup", [])
        trailers = vehicles.get("trailers", [])
        trailer_types = []
        for t in trailers:
            t_type = t.get("type", "").upper().strip()
            if t_type and t_type != "UNKNOWN":
                trailer_types.append(t_type)

        units = UnitsProfile(
            count=len(trucks) + len(trailers),
            trailer_types=list(set(trailer_types))
        )

        # Drivers
        drivers = []
        for d in extracted.get("driver_information", []):
            exp_raw = d.get("exp_years")
            exp_years = None
            if exp_raw:
                try:
                    exp_years = int(str(exp_raw).strip())
                except (ValueError, TypeError):
                    pass
            drivers.append(DriverProfile(
                name=d.get("name") or "",
                cdl_present=False,  # Will be updated when CDL doc is processed
                cdl_years=exp_years,
                cdl_class=d.get("class"),
            ))

        return applicant, commodity, coverages, units, drivers

    # ---- Main Entry Point ----

    def extract_all(self, attachments: List[dict]) -> QuoteProfile:
        """
        Extract data from all attachments and build a QuoteProfile.

        Args:
            attachments: List of dicts with 'filename' and 'data' keys

        Returns:
            QuoteProfile with all extracted data
        """
        profile = QuoteProfile()
        confidence_flags = []

        # Step 1: Classify all attachments
        classified = {}  # doc_type -> attachment
        unclassified = []

        for att in attachments:
            doc_type = self.classify_attachment(att["filename"], att["data"])
            if doc_type:
                classified[doc_type] = att
                profile.documents_present.append(doc_type)
                print(f"    Classified: {att['filename']} → {doc_type}")
            else:
                unclassified.append(att["filename"])
                print(f"    Unclassified: {att['filename']} (skipped)")

        # Step 2: Extract Blue Quote (existing extractor)
        if "BLUE QUOTE" in classified:
            att = classified["BLUE QUOTE"]
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                    tmp.write(att["data"])
                    tmp_path = tmp.name

                extractor = BlueQuotePDFExtractor(tmp_path)
                bq_data = extractor.extract()
                Path(tmp_path).unlink(missing_ok=True)

                applicant, commodity, coverages, units, drivers = self._map_blue_quote_to_profile(bq_data)
                profile.applicant = applicant
                profile.commodity = commodity
                profile.coverages = coverages
                profile.units = units
                profile.drivers = drivers

                print(f"    Blue Quote extracted: {applicant.business_name}, commodity={commodity}")
            except Exception as e:
                print(f"    Blue Quote extraction failed, trying AI fallback: {e}")
                content = self._extract_content(att["filename"], att["data"])
                if content:
                    ai_data = self._extract_ai_document("BLUE QUOTE", content)
                    if ai_data:
                        profile.applicant = ApplicantProfile(
                            business_name=ai_data.get("business_name") or "",
                            owner_name=ai_data.get("owner_name") or "",
                            owner_age=ai_data.get("owner_age"),
                            usdot=ai_data.get("usdot") or "",
                            business_years=ai_data.get("business_years"),
                            is_new_venture=ai_data.get("is_new_venture", True),
                        )
                        profile.commodity = ai_data.get("commodity") or ""
                        profile.coverages = ai_data.get("coverages") or []
                        profile.units = UnitsProfile(
                            count=ai_data.get("unit_count") or 0,
                            trailer_types=ai_data.get("trailer_types") or []
                        )
                        for d in (ai_data.get("drivers") or []):
                            profile.drivers.append(DriverProfile(
                                name=d.get("name") or "",
                                cdl_years=d.get("exp_years"),
                            ))

        # Step 3: Extract CDL (AI) — update driver-level data
        if "CDL" in classified:
            content = self._extract_content(classified["CDL"]["filename"], classified["CDL"]["data"])
            if content:
                ai_data = self._extract_ai_document("CDL", content)
                if ai_data:
                    driver_name = (ai_data.get("driver_name") or "").upper()
                    # Try to match to existing driver
                    matched = False
                    for drv in profile.drivers:
                        if driver_name and driver_name in drv.name.upper():
                            drv.cdl_present = True
                            drv.cdl_years = ai_data.get("cdl_years") or drv.cdl_years
                            drv.cdl_class = ai_data.get("cdl_class") or drv.cdl_class
                            drv.cdl_is_residential = ai_data.get("is_residential", False)
                            matched = True
                            break
                    if not matched and profile.drivers:
                        # Default: apply to first driver
                        profile.drivers[0].cdl_present = True
                        profile.drivers[0].cdl_years = ai_data.get("cdl_years") or profile.drivers[0].cdl_years
                        profile.drivers[0].cdl_class = ai_data.get("cdl_class") or profile.drivers[0].cdl_class
                        profile.drivers[0].cdl_is_residential = ai_data.get("is_residential", False)
                    elif not profile.drivers:
                        profile.drivers.append(DriverProfile(
                            name=ai_data.get("driver_name") or "",
                            cdl_present=True,
                            cdl_years=ai_data.get("cdl_years"),
                            cdl_class=ai_data.get("cdl_class"),
                            cdl_is_residential=ai_data.get("is_residential", False),
                        ))
                    print(f"    CDL extracted: {ai_data.get('driver_name')}, {ai_data.get('cdl_years')} years")
                else:
                    confidence_flags.append(ConfidenceFlag("cdl_years", "AI failed to extract CDL data"))

        # Step 4: Extract MVR (AI) — update driver-level data
        if "MVR" in classified:
            content = self._extract_content(classified["MVR"]["filename"], classified["MVR"]["data"])
            if content:
                ai_data = self._extract_ai_document("MVR", content)
                if ai_data:
                    driver_name = (ai_data.get("driver_name") or "").upper()
                    matched = False
                    for drv in profile.drivers:
                        if driver_name and driver_name in drv.name.upper():
                            drv.mvr_present = True
                            drv.mvr_years_covered = ai_data.get("years_covered")
                            drv.mvr_is_clean = ai_data.get("is_clean", False)
                            matched = True
                            break
                    if not matched and profile.drivers:
                        profile.drivers[0].mvr_present = True
                        profile.drivers[0].mvr_years_covered = ai_data.get("years_covered")
                        profile.drivers[0].mvr_is_clean = ai_data.get("is_clean", False)
                    print(f"    MVR extracted: {ai_data.get('years_covered')} years, clean={ai_data.get('is_clean')}")
                else:
                    confidence_flags.append(ConfidenceFlag("mvr", "AI failed to extract MVR data"))

        # Step 5: Extract Loss Run (AI)
        if "LOSS RUN" in classified:
            content = self._extract_content(classified["LOSS RUN"]["filename"], classified["LOSS RUN"]["data"])
            if content:
                ai_data = self._extract_ai_document("LOSS RUN", content)
                if ai_data:
                    profile.loss_run = LossRunProfile(
                        present=True,
                        years_covered=ai_data.get("years_covered"),
                        is_clean=ai_data.get("is_clean", False),
                        total_claims=ai_data.get("total_claims") or 0,
                    )
                    print(f"    Loss Run extracted: {ai_data.get('years_covered')} years, clean={ai_data.get('is_clean')}")
                else:
                    profile.loss_run.present = True  # Document exists but extraction failed
                    confidence_flags.append(ConfidenceFlag("loss_run", "AI failed to extract Loss Run data"))

        # Step 6: Extract IFTAS (AI)
        if "IFTAS" in classified:
            content = self._extract_content(classified["IFTAS"]["filename"], classified["IFTAS"]["data"])
            if content:
                ai_data = self._extract_ai_document("IFTAS", content)
                if ai_data:
                    profile.iftas = IftasProfile(
                        present=True,
                        is_registered=ai_data.get("is_registered", False),
                    )
                    print(f"    IFTAS extracted: registered={ai_data.get('is_registered')}")
                else:
                    profile.iftas.present = True

        # Step 7: Extract APP (AI)
        if "NEW VENTURE APP" in classified:
            content = self._extract_content(classified["NEW VENTURE APP"]["filename"], classified["NEW VENTURE APP"]["data"])
            if content:
                ai_data = self._extract_ai_document("NEW VENTURE APP", content)
                if ai_data:
                    profile.app = AppProfile(
                        present=True,
                        ein_included=bool(ai_data.get("ein")),
                        questions_filled=ai_data.get("additional_questions_filled", False),
                    )
                    # Update industry experience if available
                    if ai_data.get("industry_experience_years") is not None:
                        profile.applicant.industry_experience_years = ai_data["industry_experience_years"]
                    print(f"    APP extracted: EIN={bool(ai_data.get('ein'))}, questions={ai_data.get('additional_questions_filled')}")
                else:
                    profile.app.present = True

        # Step 8: Determine confidence
        critical_fields = [
            ("business_years", profile.applicant.business_years),
            ("commodity", profile.commodity),
        ]
        if profile.drivers:
            critical_fields.append(("cdl_years", profile.drivers[0].cdl_years))

        for field_name, value in critical_fields:
            if value is None or value == "":
                confidence_flags.append(ConfidenceFlag(field_name, f"Critical field '{field_name}' is missing"))

        profile.extraction_confidence = ExtractionConfidence(
            overall="low" if any(f.field in ["business_years", "cdl_years", "commodity"] for f in confidence_flags) else "high",
            flags=confidence_flags
        )

        return profile
```

- [ ] **Step 2: Commit**

```bash
git add modules/document_ai_extractor.py
git commit -m "feat: add DocumentAIExtractor for AI-powered document data extraction"
```

---

## Task 5: Rule Engine

**Files:**
- Create: `modules/rule_engine.py`

- [ ] **Step 1: Create rule engine with Excel reader and deterministic evaluation**

```python
"""
Rule Engine Module

Deterministic evaluation of QuoteProfile against structured rules from REGLAS Excel sheet.
"""

import openpyxl
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field

from modules.quote_profile import QuoteProfile


@dataclass
class FailedRule:
    """A single rule that failed evaluation."""
    rule: str
    reason: str
    current_value: Any = None
    required_value: Any = None


@dataclass
class MGAEvaluation:
    """Evaluation result for a single MGA."""
    mga_name: str
    eligible: bool
    passed_rules: List[str] = field(default_factory=list)
    failed_rules: List[FailedRule] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    informational: Dict[str, Any] = field(default_factory=dict)


class RuleEngine:
    """Evaluates quote profiles against MGA rules from REGLAS sheet."""

    # Columns in REGLAS sheet (order matters for reading)
    COLUMNS = [
        "MGA", "TIPO_DE_NEGOCIO", "MIN_BUSINESS_YEARS", "MIN_CDL_YEARS",
        "REQUIRES_MVR", "MVR_MIN_YEARS", "REQUIRES_IFTAS", "REQUIRES_LOSS_RUN",
        "LOSS_RUN_MIN_YEARS", "LOSSES_MUST_BE_CLEAN", "REQUIRES_APP",
        "REQUIRES_EIN", "REQUIRES_QUESTIONS", "REQUIRES_REGISTRATIONS",
        "MIN_UNITS", "MIN_OWNER_AGE", "MIN_INDUSTRY_EXP_YEARS",
        "ALLOWED_COVERAGES", "BLOCKED_TRAILER_TYPES", "BLOCKED_COMMODITIES",
        "ALLOWED_TRAILER_TYPES", "ROUTING", "DOWN_PAYMENT_PCT", "MIN_PRICE",
        "SPECIAL_FORM", "NOTES"
    ]

    def __init__(self, excel_path: str, sheet_name: str = "REGLAS"):
        self.excel_path = Path(excel_path)
        if not self.excel_path.exists():
            raise FileNotFoundError(f"Excel not found: {excel_path}")
        self.sheet_name = sheet_name
        self._rules_cache = None

    def _load_rules(self) -> List[Dict[str, Any]]:
        """Load all rules from REGLAS sheet."""
        if self._rules_cache is not None:
            return self._rules_cache

        wb = openpyxl.load_workbook(self.excel_path, data_only=True)
        if self.sheet_name not in wb.sheetnames:
            wb.close()
            raise ValueError(f"Sheet '{self.sheet_name}' not found. Available: {wb.sheetnames}")

        ws = wb[self.sheet_name]

        # Read headers from first row
        headers = [cell.value for cell in ws[1]]
        header_map = {}
        for i, h in enumerate(headers):
            if h:
                # Normalize: strip, replace spaces with underscores
                normalized = str(h).strip().upper().replace(" ", "_")
                header_map[normalized] = i

        rules = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            rule = {}
            for col_name in self.COLUMNS:
                idx = header_map.get(col_name)
                if idx is not None and idx < len(row):
                    val = row[idx]
                    rule[col_name] = str(val).strip() if val is not None else None
                else:
                    rule[col_name] = None
            # Only add if MGA has a value
            if rule.get("MGA"):
                rules.append(rule)

        wb.close()
        self._rules_cache = rules
        return rules

    def _get_int(self, value: Optional[str]) -> Optional[int]:
        """Safely parse int from string."""
        if value is None:
            return None
        try:
            return int(float(str(value).strip()))
        except (ValueError, TypeError):
            return None

    def _parse_list(self, value: Optional[str]) -> List[str]:
        """Parse comma-separated list, uppercased and stripped."""
        if not value:
            return []
        return [v.strip().upper() for v in value.split(",") if v.strip()]

    def _is_yes(self, value: Optional[str]) -> bool:
        """Check if value is YES."""
        return value is not None and value.strip().upper() == "YES"

    def _is_si_aplica(self, value: Optional[str]) -> bool:
        """Check if value is SI_APLICA."""
        return value is not None and value.strip().upper() == "SI_APLICA"

    def get_rules_for_mga(self, tipo_negocio: str) -> List[Dict[str, Any]]:
        """Get all REGLAS rows matching a tipo_negocio."""
        rules = self._load_rules()
        normalized = tipo_negocio.strip().upper()
        return [r for r in rules if (r.get("TIPO_DE_NEGOCIO") or "").strip().upper() == normalized]

    def evaluate(self, profile: QuoteProfile, tipo_negocio: str) -> List[MGAEvaluation]:
        """
        Evaluate all MGAs for a business type against the quote profile.

        Returns list of MGAEvaluation.
        """
        matching_rules = self.get_rules_for_mga(tipo_negocio)
        results = []

        for rule in matching_rules:
            mga_name = rule["MGA"]
            failures = []
            passed = []
            warnings = []

            # --- Numeric thresholds ---
            min_biz = self._get_int(rule.get("MIN_BUSINESS_YEARS"))
            if min_biz is not None:
                biz_years = profile.applicant.business_years
                if biz_years is not None and biz_years < min_biz:
                    failures.append(FailedRule("MIN_BUSINESS_YEARS",
                        f"Business has {biz_years} year(s), needs {min_biz}+",
                        biz_years, min_biz))
                elif biz_years is not None:
                    passed.append("MIN_BUSINESS_YEARS")

            min_age = self._get_int(rule.get("MIN_OWNER_AGE"))
            if min_age is not None:
                owner_age = profile.applicant.owner_age
                if owner_age is not None and owner_age < min_age:
                    failures.append(FailedRule("MIN_OWNER_AGE",
                        f"Owner is {owner_age}, needs min {min_age}",
                        owner_age, min_age))
                elif owner_age is not None:
                    passed.append("MIN_OWNER_AGE")

            min_units = self._get_int(rule.get("MIN_UNITS"))
            if min_units is not None:
                if profile.units.count < min_units:
                    failures.append(FailedRule("MIN_UNITS",
                        f"Has {profile.units.count} units, needs {min_units}+",
                        profile.units.count, min_units))
                else:
                    passed.append("MIN_UNITS")

            min_exp = self._get_int(rule.get("MIN_INDUSTRY_EXP_YEARS"))
            if min_exp is not None:
                exp = profile.applicant.industry_experience_years
                if exp is not None and exp < min_exp:
                    failures.append(FailedRule("MIN_INDUSTRY_EXP_YEARS",
                        f"Industry exp: {exp} years, needs {min_exp}+",
                        exp, min_exp))
                elif exp is not None:
                    passed.append("MIN_INDUSTRY_EXP_YEARS")

            # --- Driver-level rules (least favorable) ---
            min_cdl = self._get_int(rule.get("MIN_CDL_YEARS"))
            if min_cdl is not None and profile.drivers:
                all_pass = True
                for drv in profile.drivers:
                    if drv.cdl_years is not None and drv.cdl_years < min_cdl:
                        failures.append(FailedRule("MIN_CDL_YEARS",
                            f"Driver '{drv.name}': CDL {drv.cdl_years} yr, needs {min_cdl}+",
                            drv.cdl_years, min_cdl))
                        all_pass = False
                if all_pass:
                    passed.append("MIN_CDL_YEARS")

            # --- Document presence ---
            if self._is_yes(rule.get("REQUIRES_MVR")):
                has_mvr = any(d.mvr_present for d in profile.drivers)
                if not has_mvr:
                    failures.append(FailedRule("REQUIRES_MVR", "Missing document: MVR"))
                else:
                    passed.append("REQUIRES_MVR")

            # IFTAS
            iftas_rule = rule.get("REQUIRES_IFTAS")
            if self._is_yes(iftas_rule):
                if not profile.iftas.present:
                    failures.append(FailedRule("REQUIRES_IFTAS", "Missing document: IFTAS"))
                else:
                    passed.append("REQUIRES_IFTAS")
            elif self._is_si_aplica(iftas_rule) and not profile.iftas.present:
                warnings.append("IFTAS may be required if interstate operations apply")

            # Loss Run
            lr_rule = rule.get("REQUIRES_LOSS_RUN")
            if self._is_yes(lr_rule):
                if not profile.loss_run.present:
                    failures.append(FailedRule("REQUIRES_LOSS_RUN", "Missing document: LOSS RUN"))
                else:
                    passed.append("REQUIRES_LOSS_RUN")
            elif self._is_si_aplica(lr_rule) and not profile.loss_run.present:
                warnings.append("Loss Run may be required depending on history")

            # MVR min years
            mvr_min = self._get_int(rule.get("MVR_MIN_YEARS"))
            if mvr_min is not None:
                for drv in profile.drivers:
                    if drv.mvr_present and drv.mvr_years_covered is not None and drv.mvr_years_covered < mvr_min:
                        failures.append(FailedRule("MVR_MIN_YEARS",
                            f"Driver '{drv.name}': MVR covers {drv.mvr_years_covered} yr, needs {mvr_min}+",
                            drv.mvr_years_covered, mvr_min))

            # Loss Run min years
            lr_min = self._get_int(rule.get("LOSS_RUN_MIN_YEARS"))
            if lr_min is not None and profile.loss_run.present:
                if profile.loss_run.years_covered is not None and profile.loss_run.years_covered < lr_min:
                    failures.append(FailedRule("LOSS_RUN_MIN_YEARS",
                        f"Loss Run covers {profile.loss_run.years_covered} yr, needs {lr_min}+",
                        profile.loss_run.years_covered, lr_min))

            # Losses must be clean
            if self._is_yes(rule.get("LOSSES_MUST_BE_CLEAN")):
                if profile.loss_run.present and not profile.loss_run.is_clean:
                    failures.append(FailedRule("LOSSES_MUST_BE_CLEAN", "Loss Run must be clean (no claims)"))
                elif profile.loss_run.present:
                    passed.append("LOSSES_MUST_BE_CLEAN")

            # APP
            if self._is_yes(rule.get("REQUIRES_APP")):
                if not profile.app.present:
                    failures.append(FailedRule("REQUIRES_APP", "Missing document: APP"))
                else:
                    passed.append("REQUIRES_APP")

            if self._is_yes(rule.get("REQUIRES_EIN")):
                if not profile.app.ein_included:
                    failures.append(FailedRule("REQUIRES_EIN", "Missing: EIN"))
                else:
                    passed.append("REQUIRES_EIN")

            if self._is_yes(rule.get("REQUIRES_QUESTIONS")):
                if not profile.app.questions_filled:
                    failures.append(FailedRule("REQUIRES_QUESTIONS", "Questionnaire not filled"))
                else:
                    passed.append("REQUIRES_QUESTIONS")

            if self._is_yes(rule.get("REQUIRES_REGISTRATIONS")):
                if "REGISTRATIONS" not in [d.upper() for d in profile.documents_present]:
                    failures.append(FailedRule("REQUIRES_REGISTRATIONS", "Missing: vehicle registrations"))
                else:
                    passed.append("REQUIRES_REGISTRATIONS")

            # --- Coverage rules ---
            allowed_cov = self._parse_list(rule.get("ALLOWED_COVERAGES"))
            if allowed_cov:
                requested = set(c.upper() for c in profile.coverages)
                allowed_set = set(allowed_cov)
                disallowed = requested - allowed_set
                if disallowed:
                    failures.append(FailedRule("ALLOWED_COVERAGES",
                        f"Coverage not accepted: {', '.join(disallowed)}",
                        list(requested), list(allowed_set)))
                else:
                    passed.append("ALLOWED_COVERAGES")

            # --- Trailer rules (ALLOWED takes precedence) ---
            allowed_trailers = self._parse_list(rule.get("ALLOWED_TRAILER_TYPES"))
            blocked_trailers = self._parse_list(rule.get("BLOCKED_TRAILER_TYPES"))

            if allowed_trailers:
                actual = set(t.upper() for t in profile.units.trailer_types)
                allowed_set = set(allowed_trailers)
                disallowed = actual - allowed_set
                if disallowed:
                    failures.append(FailedRule("ALLOWED_TRAILER_TYPES",
                        f"Trailer not in allow list: {', '.join(disallowed)}",
                        list(actual), list(allowed_set)))
                else:
                    passed.append("ALLOWED_TRAILER_TYPES")
            elif blocked_trailers:
                actual = set(t.upper() for t in profile.units.trailer_types)
                blocked_set = set(blocked_trailers)
                overlap = actual & blocked_set
                if overlap:
                    failures.append(FailedRule("BLOCKED_TRAILER_TYPES",
                        f"Blocked trailer type: {', '.join(overlap)}"))
                else:
                    passed.append("BLOCKED_TRAILER_TYPES")

            # --- Commodity restrictions ---
            blocked_comm = self._parse_list(rule.get("BLOCKED_COMMODITIES"))
            if blocked_comm:
                commodity_upper = profile.commodity.upper()
                blocked_found = [kw for kw in blocked_comm if kw in commodity_upper]
                if blocked_found:
                    failures.append(FailedRule("BLOCKED_COMMODITIES",
                        f"Blocked commodity: {', '.join(blocked_found)}"))
                else:
                    passed.append("BLOCKED_COMMODITIES")

            # --- Informational columns (not evaluated) ---
            informational = {
                "routing": rule.get("ROUTING"),
                "down_payment_pct": self._get_int(rule.get("DOWN_PAYMENT_PCT")),
                "min_price": self._get_int(rule.get("MIN_PRICE")),
                "special_form": rule.get("SPECIAL_FORM"),
                "notes": rule.get("NOTES"),
            }

            results.append(MGAEvaluation(
                mga_name=mga_name,
                eligible=len(failures) == 0,
                passed_rules=passed,
                failed_rules=failures,
                warnings=warnings,
                informational=informational,
            ))

        return results
```

- [ ] **Step 2: Commit**

```bash
git add modules/rule_engine.py
git commit -m "feat: add deterministic RuleEngine for MGA eligibility evaluation"
```

---

## Task 6: Unit Tests — Rule Engine

**Files:**
- Create: `tests/test_rule_engine.py`

- [ ] **Step 1: Create tests with mock profile and rules**

```python
"""Tests for rule_engine.py — uses mocked Excel data."""

import pytest
from unittest.mock import patch, MagicMock
from modules.rule_engine import RuleEngine, MGAEvaluation, FailedRule
from modules.quote_profile import (
    QuoteProfile, ApplicantProfile, DriverProfile, LossRunProfile,
    IftasProfile, AppProfile, UnitsProfile
)


def make_profile(**overrides) -> QuoteProfile:
    """Helper to build a QuoteProfile with sensible defaults."""
    p = QuoteProfile(
        applicant=ApplicantProfile(
            business_name="TEST TRUCKING",
            owner_name="JOHN DOE",
            owner_age=35,
            usdot="1234567",
            business_years=3,
            is_new_venture=False,
            industry_experience_years=5,
        ),
        commodity="DIRT, SAND & GRAVEL",
        coverages=["AL", "MTC", "APD"],
        units=UnitsProfile(count=4, trailer_types=["END DUMP"]),
        drivers=[DriverProfile(
            name="JOHN DOE",
            cdl_present=True, cdl_years=3, cdl_class="A",
            mvr_present=True, mvr_years_covered=5, mvr_is_clean=True,
        )],
        loss_run=LossRunProfile(present=True, years_covered=5, is_clean=True),
        iftas=IftasProfile(present=True, is_registered=True),
        app=AppProfile(present=True, ein_included=True, questions_filled=True),
        documents_present=["BLUE QUOTE", "MVR", "CDL", "IFTAS", "LOSS RUN", "APP"],
    )
    # Apply overrides
    for key, val in overrides.items():
        parts = key.split(".")
        obj = p
        for part in parts[:-1]:
            obj = getattr(obj, part)
        setattr(obj, parts[-1], val)
    return p


# Mock rules data
MOCK_RULES = [
    {
        "MGA": "TEST_MGA_A", "TIPO_DE_NEGOCIO": "DIRT, SAND & GRAVEL",
        "MIN_BUSINESS_YEARS": "2", "MIN_CDL_YEARS": "2",
        "REQUIRES_MVR": "YES", "MVR_MIN_YEARS": None,
        "REQUIRES_IFTAS": "SI_APLICA", "REQUIRES_LOSS_RUN": "YES",
        "LOSS_RUN_MIN_YEARS": "5", "LOSSES_MUST_BE_CLEAN": "NO",
        "REQUIRES_APP": "YES", "REQUIRES_EIN": "NO",
        "REQUIRES_QUESTIONS": "NO", "REQUIRES_REGISTRATIONS": "NO",
        "MIN_UNITS": None, "MIN_OWNER_AGE": None,
        "MIN_INDUSTRY_EXP_YEARS": None,
        "ALLOWED_COVERAGES": None, "BLOCKED_TRAILER_TYPES": "DUMP",
        "BLOCKED_COMMODITIES": None, "ALLOWED_TRAILER_TYPES": None,
        "ROUTING": None, "DOWN_PAYMENT_PCT": None,
        "MIN_PRICE": None, "SPECIAL_FORM": None, "NOTES": None,
    },
    {
        "MGA": "TEST_MGA_B", "TIPO_DE_NEGOCIO": "DIRT, SAND & GRAVEL",
        "MIN_BUSINESS_YEARS": "1", "MIN_CDL_YEARS": "1",
        "REQUIRES_MVR": "YES", "MVR_MIN_YEARS": None,
        "REQUIRES_IFTAS": "YES", "REQUIRES_LOSS_RUN": "SI_APLICA",
        "LOSS_RUN_MIN_YEARS": None, "LOSSES_MUST_BE_CLEAN": "NO",
        "REQUIRES_APP": "NO", "REQUIRES_EIN": "NO",
        "REQUIRES_QUESTIONS": "NO", "REQUIRES_REGISTRATIONS": "NO",
        "MIN_UNITS": None, "MIN_OWNER_AGE": "30",
        "MIN_INDUSTRY_EXP_YEARS": None,
        "ALLOWED_COVERAGES": "AL,MTC,APD,GL", "BLOCKED_TRAILER_TYPES": None,
        "BLOCKED_COMMODITIES": "FERTILIZANTES", "ALLOWED_TRAILER_TYPES": None,
        "ROUTING": "SOLO_NICO", "DOWN_PAYMENT_PCT": "25",
        "MIN_PRICE": "25000", "SPECIAL_FORM": None, "NOTES": "Test note",
    },
]


@pytest.fixture
def engine():
    """Create RuleEngine with mocked Excel data."""
    eng = RuleEngine.__new__(RuleEngine)
    eng.excel_path = "fake.xlsx"
    eng.sheet_name = "REGLAS"
    eng._rules_cache = MOCK_RULES
    return eng


class TestRuleEngineBasic:
    def test_eligible_profile_passes_all(self, engine):
        profile = make_profile()
        results = engine.evaluate(profile, "DIRT, SAND & GRAVEL")
        # MGA_B should pass (END DUMP not blocked, no FERTILIZANTES)
        mga_b = [r for r in results if r.mga_name == "TEST_MGA_B"][0]
        assert mga_b.eligible is True

    def test_business_years_too_low(self, engine):
        profile = make_profile(**{"applicant.business_years": 1})
        results = engine.evaluate(profile, "DIRT, SAND & GRAVEL")
        mga_a = [r for r in results if r.mga_name == "TEST_MGA_A"][0]
        assert mga_a.eligible is False
        assert any("Business" in f.reason for f in mga_a.failed_rules)

    def test_blocked_trailer_type(self, engine):
        profile = make_profile()
        profile.units.trailer_types = ["DUMP"]
        results = engine.evaluate(profile, "DIRT, SAND & GRAVEL")
        mga_a = [r for r in results if r.mga_name == "TEST_MGA_A"][0]
        assert mga_a.eligible is False
        assert any("DUMP" in f.reason for f in mga_a.failed_rules)

    def test_si_aplica_generates_warning(self, engine):
        profile = make_profile()
        profile.iftas.present = False
        results = engine.evaluate(profile, "DIRT, SAND & GRAVEL")
        mga_a = [r for r in results if r.mga_name == "TEST_MGA_A"][0]
        # SI_APLICA should not fail, just warn
        assert not any(f.rule == "REQUIRES_IFTAS" for f in mga_a.failed_rules)
        assert any("IFTAS" in w for w in mga_a.warnings)

    def test_missing_mvr_fails(self, engine):
        profile = make_profile()
        profile.drivers[0].mvr_present = False
        results = engine.evaluate(profile, "DIRT, SAND & GRAVEL")
        mga_a = [r for r in results if r.mga_name == "TEST_MGA_A"][0]
        assert mga_a.eligible is False
        assert any("MVR" in f.reason for f in mga_a.failed_rules)

    def test_blocked_commodity(self, engine):
        profile = make_profile()
        profile.commodity = "FERTILIZANTES QUIMICOS"
        results = engine.evaluate(profile, "DIRT, SAND & GRAVEL")
        mga_b = [r for r in results if r.mga_name == "TEST_MGA_B"][0]
        assert mga_b.eligible is False
        assert any("FERTILIZANTES" in f.reason for f in mga_b.failed_rules)

    def test_informational_passed_through(self, engine):
        profile = make_profile()
        results = engine.evaluate(profile, "DIRT, SAND & GRAVEL")
        mga_b = [r for r in results if r.mga_name == "TEST_MGA_B"][0]
        assert mga_b.informational["routing"] == "SOLO_NICO"
        assert mga_b.informational["down_payment_pct"] == 25
        assert mga_b.informational["notes"] == "Test note"

    def test_no_rules_returns_empty(self, engine):
        profile = make_profile()
        results = engine.evaluate(profile, "NONEXISTENT TYPE")
        assert results == []

    def test_owner_age_too_low(self, engine):
        profile = make_profile(**{"applicant.owner_age": 25})
        results = engine.evaluate(profile, "DIRT, SAND & GRAVEL")
        mga_b = [r for r in results if r.mga_name == "TEST_MGA_B"][0]
        assert mga_b.eligible is False
        assert any("Owner" in f.reason for f in mga_b.failed_rules)

    def test_cdl_years_too_low_per_driver(self, engine):
        profile = make_profile()
        profile.drivers[0].cdl_years = 1
        results = engine.evaluate(profile, "DIRT, SAND & GRAVEL")
        mga_a = [r for r in results if r.mga_name == "TEST_MGA_A"][0]
        assert mga_a.eligible is False
        assert any("CDL" in f.reason for f in mga_a.failed_rules)
```

- [ ] **Step 2: Run tests**

Run: `python -m pytest tests/test_rule_engine.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_rule_engine.py
git commit -m "test: add unit tests for RuleEngine"
```

---

## Task 7: Integrate into Workflow Orchestrator

**Files:**
- Modify: `workflow_orchestrator.py`

- [ ] **Step 1: Add imports**

Add at top of file after existing imports:

```python
from modules.document_ai_extractor import DocumentAIExtractor
from modules.rule_engine import RuleEngine
```

- [ ] **Step 2: Initialize new components in `__init__`**

Add after `self.drive_manager = DriveManager()`:

```python
self.document_extractor = DocumentAIExtractor()
self.rule_engine = RuleEngine(str(self.excel_path))
self.rule_engine_enabled = self.config.get("rule_engine.enabled", True)
self.halt_on_low_confidence = self.config.get("rule_engine.halt_on_low_confidence", True)
```

- [ ] **Step 3: Replace `process_email` method**

Replace the entire `process_email` method with the new flow that adds document extraction and rule evaluation between the existing steps. Key changes:

1. After finding attachments, call `self.document_extractor.extract_all(attachments)` to get the QuoteProfile
2. Use `profile.commodity` for commodity mapping instead of extracting only from Blue Quote
3. After getting candidate MGAs, call `self.rule_engine.evaluate(profile, tipo_negocio)` to filter
4. Only send to MGAs where `evaluation.eligible == True`
5. Include `evaluation.failed_rules` and `evaluation.warnings` in client summary

The full replacement for `process_email` should follow this flow:

```
1. Log email info
2. Extract all documents → QuoteProfile
3. Check confidence — halt if low and halt_on_low_confidence is True
4. Get commodity from profile, map to tipo_negocio
5. Get candidate MGAs from MGA sheet
6. If rule_engine_enabled: evaluate rules, filter to eligible only
7. For eligible MGAs: validate docs present, get email, send
8. Build summary with eligible/ineligible/warnings
9. Upload to Drive
```

- [ ] **Step 4: Commit**

```bash
git add workflow_orchestrator.py
git commit -m "feat: integrate document extraction and rule engine into workflow"
```

---

## Task 8: Data Migration Script

**Files:**
- Create: `scripts/migrate_rules.py`

- [ ] **Step 1: Create migration script**

Script that:
1. Reads all rows from MGA sheet (TIPO_DE_NEGOCIO, MGA, COMENTARIOS)
2. For each unique COMENTARIOS text, sends to GPT-5.4 with a prompt to decompose into structured columns
3. Outputs a CSV for human review
4. After review, writes to REGLAS sheet in the Excel

The AI prompt:
```
Given this insurance MGA requirement comment, decompose it into structured fields.
Return ONLY valid JSON with these fields (use null if not mentioned):
{
  "MIN_BUSINESS_YEARS": int or null,
  "MIN_CDL_YEARS": int or null,
  "REQUIRES_MVR": "YES" or "NO",
  "MVR_MIN_YEARS": int or null,
  "REQUIRES_IFTAS": "YES" or "NO" or "SI_APLICA",
  "REQUIRES_LOSS_RUN": "YES" or "NO" or "SI_APLICA",
  "LOSS_RUN_MIN_YEARS": int or null,
  "LOSSES_MUST_BE_CLEAN": "YES" or "NO",
  ...all other columns...
}

Comment: "{comentario}"
```

- [ ] **Step 2: Run migration, review output, write to Excel**

Run: `python scripts/migrate_rules.py`
Then: manually review the generated CSV before importing

- [ ] **Step 3: Commit**

```bash
git add scripts/migrate_rules.py
git commit -m "feat: add migration script to convert COMENTARIOS to REGLAS sheet"
```

---

## Task 9: Update Module Exports

**Files:**
- Modify: `modules/__init__.py`

- [ ] **Step 1: Update exports**

```python
"""
H2O Quote RPA - Modules Package

Core modules for automated quote processing.
"""

__version__ = "0.2.0"
__all__ = [
    "excel_config", "commodity_matcher", "pdf_extractor",
    "quote_profile", "document_ai_extractor", "rule_engine",
]
```

- [ ] **Step 2: Commit**

```bash
git add modules/__init__.py
git commit -m "chore: update module exports with new components"
```

---

## Summary — Execution Order

| Task | Component | Depends On |
|------|-----------|------------|
| 1 | Dependencies | — |
| 2 | Config settings | — |
| 3 | QuoteProfile data model | — |
| 4 | DocumentAIExtractor | Tasks 1, 2, 3 |
| 5 | RuleEngine | Task 3 |
| 6 | Tests for RuleEngine | Task 5 |
| 7 | Orchestrator integration | Tasks 4, 5 |
| 8 | Data migration script | Tasks 2, 5 |
| 9 | Module exports | Tasks 3, 4, 5 |

Tasks 1-3 can run in parallel. Tasks 4 and 5 can run in parallel after 3. Task 6 after 5. Task 7 after 4+5. Tasks 8-9 are independent.
