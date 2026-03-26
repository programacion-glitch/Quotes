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
