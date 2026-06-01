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
    IftasProfile, AppProfile, UnitsProfile, VehicleProfile, CoveragesProfile,
    ExtractionConfidence, ConfidenceFlag,
)


# Document type constants
DOC_TYPES = ["BLUE QUOTE", "MVR", "CDL", "IFTAS", "LOSS RUN", "NEW VENTURE APP"]


# USPS street suffix abbreviations (most common). The street boundary in a
# single-line address sits at the last token in this set; everything after
# is the city.
_STREET_SUFFIXES = {
    "ST", "STREET", "AVE", "AV", "AVENUE", "BLVD", "BOULEVARD",
    "RD", "ROAD", "DR", "DRIVE", "LN", "LANE", "CT", "COURT",
    "CIR", "CIRCLE", "WAY", "PL", "PLACE", "TER", "TERRACE",
    "TRL", "TRAIL", "HWY", "HIGHWAY", "PKWY", "PARKWAY",
    "CV", "COVE", "CTR", "CENTER", "CRES", "CRESCENT",
    "LOOP", "ALY", "ALLEY", "ROW", "RUN", "XING", "CROSSING",
    "SQ", "SQUARE", "PT", "POINT", "FWY", "FREEWAY", "RT", "ROUTE",
}


def _parse_us_address(addr: str) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Split a US address string into (street, city, state, zip).

    Handles the common Blue Quote formats:
        "585 NOLAN ST BEAUMONT, TX 77705"
        "319 CARLITO CV UNIVERSAL CTY, TX   78148"
        "8464 BRAHMA DR JUSTIN, TX 76247"

    Split anchors:
      * trailing 5 (or 5+4) digit ZIP
      * 2-letter state code immediately before the ZIP
      * the comma between city and state
      * within the pre-comma segment: the LAST street-suffix token (ST, DR,
        CV, ...) ends the street; remaining tokens are the city.

    Returns (None, None, None, None) on unparseable input.
    """
    import re as _re
    if not addr or not isinstance(addr, str):
        return (None, None, None, None)
    s = " ".join(addr.split())
    m = _re.search(r"^(.*?),\s*([A-Z]{2})\s+(\d{5})(?:-\d{4})?\s*$", s, _re.IGNORECASE)
    if not m:
        return (None, None, None, None)
    left, state, zipc = m.group(1).strip(), m.group(2).upper(), m.group(3)
    tokens = left.split()
    if len(tokens) < 2:
        return (None, left or None, state, zipc)

    # Find LAST street suffix; everything up to and including it = street.
    suffix_idx = -1
    for i, tok in enumerate(tokens):
        if tok.upper().strip(".") in _STREET_SUFFIXES:
            suffix_idx = i

    if suffix_idx >= 0 and suffix_idx < len(tokens) - 1:
        street = " ".join(tokens[: suffix_idx + 1]).strip() or None
        city = " ".join(tokens[suffix_idx + 1:]).strip() or None
    else:
        # No recognized suffix; fall back to "last 1 token is city" heuristic.
        street = " ".join(tokens[:-1]).strip() or None
        city = tokens[-1] or None
    return (street, city, state, zipc)

# System prompts per document type — each requests specific fields as JSON
EXTRACTION_PROMPTS = {
    "CDL": """You are an expert at reading Commercial Driver License (CDL) documents.
Extract the following fields from this document and return ONLY valid JSON, no extra text:
{
  "driver_name": "string",
  "issue_date": "YYYY-MM-DD or null (the FIRST/ORIGINAL issue date, NOT renewal/expiration)",
  "cdl_years": integer (years between issue_date and today's date 2026-04-08, or null),
  "cdl_class": "A, B, or C",
  "state": "two-letter state code",
  "is_residential": true/false (true if address shows residential)
}

IMPORTANT for cdl_years:
- Look for labels like "ORIG ISS", "Original Issue", "ISS DATE", "Date Issued", "First Issued",
  "DL ISS", "CDL ISS", "Class A Since", or simply "ISSUED".
- DO NOT use the renewal or expiration date — those are typically only 4-8 years apart.
- If the document shows multiple dates, choose the earliest one tied to a CDL class.
- Compute the integer number of full years from that date to 2026-04-08.
- If you genuinely cannot find an issue date, use null. NEVER guess 0.

If a field cannot be determined, use null.""",

    "MVR": """You are an expert at reading Motor Vehicle Records (MVR) / Driving Records.
Extract the following fields and return ONLY valid JSON, no extra text:
{
  "driver_name": "string",
  "years_covered": integer (number of years the report spans),
  "violations": ["list of violation descriptions"] or [],
  "is_clean": true/false (true if there are NO violations, accidents, suspensions, or convictions)
}

IMPORTANT for years_covered:
- Look for labels like "Report Period", "Date Range", "From / To", "Records From",
  "Issued for the period", or a title like "3-Year Driving Record" or "5-year MVR".
- If you see a date range (e.g., "01/01/2023 to 04/08/2026"), compute the difference in years.
- If you only see a "report date", assume the standard MVR coverage of 3 years.
- Result must be a positive integer. NEVER return 0.

IMPORTANT for is_clean:
- true ONLY if the violations/convictions section is explicitly empty or says "No records found", "Clean record", "No violations".
- false if ANY violation, accident, suspension, conviction, or warning is listed.
- If you cannot tell, use null (not false).

If a field cannot be determined, use null.""",

    "LOSS RUN": """You are an expert at reading insurance Loss Run / Claims History reports.
Extract the following fields and return ONLY valid JSON, no extra text:
{
  "years_covered": integer (number of years the report covers),
  "has_losses": true/false,
  "is_clean": true/false (true if NO claims, NO losses, NO incidents),
  "total_claims": integer (count of distinct claims/losses listed)
}

IMPORTANT for years_covered:
- Look across ALL pages — Loss Runs often have one page per policy year.
- Look for policy effective/expiration dates listed (e.g., "Policy Period 01/01/2023 - 01/01/2024").
- Count distinct policy years OR compute the span between the earliest and latest dates.
- A "5-Year Loss Run" report covers 5 years even if only some years have claims.
- If only one period is visible, default to 1.
- Result must be a positive integer. NEVER return 0 or null when at least one date is visible.

IMPORTANT for is_clean:
- true ONLY if every period explicitly shows zero claims/losses (e.g., "No Loss", "Loss Free",
  "No claims reported", "0 claims", "$0 incurred").
- false if there is at least ONE claim, paid amount > 0, or incurred amount > 0.

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
        Determine document type by FILENAME only. No AI fallback.

        Returns one of DOC_TYPES or None.
        """
        for doc_type in DOC_TYPES:
            if self.validator._matches_document(filename, doc_type):
                return doc_type

        # Check APP variants
        if self.validator._matches_app_invo(filename):
            return "NEW VENTURE APP"
        if self.validator._matches_app_general(filename):
            return "NEW VENTURE APP"

        return None

    # ---- Content Extraction ----

    # Limits for vision fallback
    MAX_PAGES_VISION = 8     # max PDF pages to render as images
    VISION_DPI = 180         # DPI for rendered images (JPEG) — higher = better OCR for scanned docs
    JPEG_QUALITY = 80        # JPEG quality (1-100)
    MAX_PAYLOAD_BYTES = 8 * 1024 * 1024  # 8 MB safety budget for images (raw, pre-base64)

    def _extract_content(self, filename: str, data: bytes, force_vision: bool = False) -> Optional[dict]:
        """
        Extract content from file, returning either text or one-or-more images.

        Args:
            filename: original filename (used to detect extension)
            data: raw bytes
            force_vision: if True, skip the text-extraction path and always render
                pages as images. Useful for PDFs where the text layer only contains
                form labels (e.g. flattened Blue Quotes).

        Returns one of:
            {"type": "text", "text": "..."}
            {"type": "images", "images": [{"base64": "...", "mime": "image/jpeg"}, ...]}
        """
        ext = Path(filename).suffix.lower()

        if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
            mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "gif": "gif", "webp": "webp"}
            mime_type = mime.get(ext.lstrip("."), "png")
            b64 = base64.b64encode(data).decode("utf-8")
            return {"type": "images", "images": [{"base64": b64, "mime": f"image/{mime_type}"}]}

        if ext == ".pdf":
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(data)
                tmp_path = tmp.name

            try:
                # Step 1: try text extraction from ALL pages (skip if force_vision)
                page_count = 0
                if not force_vision:
                    text_pages: List[str] = []
                    try:
                        with pdfplumber.open(tmp_path) as pdf:
                            page_count = len(pdf.pages)
                            for page in pdf.pages:
                                page_text = page.extract_text() or ""
                                text_pages.append(page_text)
                    except Exception as e:
                        print(f"    pdfplumber failed for {filename}: {e}")

                    total_text = "\n".join(text_pages).strip()
                    avg_per_page = (len(total_text) / max(page_count, 1)) if page_count else 0

                    if (
                        page_count > 0
                        and avg_per_page >= self.min_text_threshold
                        and len(total_text) >= self.min_text_threshold * 2
                    ):
                        return {"type": "text", "text": total_text}

                # Step 2: fallback to multi-page image rendering
                images: List[dict] = []
                total_bytes = 0
                try:
                    with fitz.open(tmp_path) as doc:
                        n = min(self.MAX_PAGES_VISION, len(doc))
                        for i in range(n):
                            page = doc[i]
                            pix = page.get_pixmap(dpi=self.VISION_DPI)
                            # PyMuPDF tobytes supports "jpeg" with quality via jpg_quality kwarg
                            try:
                                img_bytes = pix.tobytes("jpeg", jpg_quality=self.JPEG_QUALITY)
                                mime = "image/jpeg"
                            except TypeError:
                                # Older PyMuPDF: fall back to PNG
                                img_bytes = pix.tobytes("png")
                                mime = "image/png"
                            # Stop if we'd blow the payload budget
                            if total_bytes + len(img_bytes) > self.MAX_PAYLOAD_BYTES:
                                print(f"    Vision payload limit reached after {i} page(s) for {filename}")
                                break
                            total_bytes += len(img_bytes)
                            b64 = base64.b64encode(img_bytes).decode("utf-8")
                            images.append({"base64": b64, "mime": mime})
                except Exception as e:
                    print(f"    PyMuPDF render failed for {filename}: {e}")
                    return None

                if not images:
                    return None
                return {"type": "images", "images": images}
            finally:
                Path(tmp_path).unlink(missing_ok=True)

        return None

    # ---- Debug ----

    def _debug_content(self, doc_type: str, filename: str, content: Optional[dict]) -> None:
        """Print a one-line summary of how the document was prepared for the AI."""
        if not content:
            print(f"    [{doc_type}] no content extracted from {filename}")
            return
        ctype = content.get("type")
        if ctype == "text":
            txt = content.get("text", "")
            print(f"    [{doc_type}] sending text ({len(txt)} chars) from {filename}")
        elif ctype == "images":
            n = len(content.get("images", []))
            print(f"    [{doc_type}] sending {n} page image(s) from {filename}")
        else:
            print(f"    [{doc_type}] unknown content type for {filename}")

    # ---- AI Call ----

    def _call_ai(self, system_prompt: str, content: dict) -> Optional[str]:
        """
        Call the model with text or one-or-more images. Retries on failure.
        """
        ctype = content.get("type")
        if ctype == "text":
            user_content = content["text"]
        elif ctype == "images":
            parts = [{"type": "text",
                      "text": "Extract the requested data from this document. "
                              "All pages of the document are provided below in order."}]
            for img in content.get("images", []):
                parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{img['mime']};base64,{img['base64']}"}
                })
            user_content = parts
        elif ctype == "image":  # back-compat for legacy single-image payloads
            user_content = [
                {"type": "text", "text": "Extract the requested data from this document."},
                {"type": "image_url", "image_url": {
                    "url": f"data:{content['mime']};base64,{content['base64']}"
                }}
            ]
        else:
            return None

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

    def _map_blue_quote_to_profile(self, extracted: dict) -> Tuple[ApplicantProfile, str, List[str], UnitsProfile, List[DriverProfile], CoveragesProfile]:
        """Map BlueQuotePDFExtractor output to profile components."""
        app_info = extracted.get("applicant_info", {})

        # Applicant
        # The Blue Quote often stores years as "3 YEARS" / "3 anos" / "3" — pull
        # the first integer from the string instead of strict int parsing.
        import re as _re
        def _first_int(value) -> Optional[int]:
            if value is None:
                return None
            m = _re.search(r"\d+", str(value))
            return int(m.group(0)) if m else None

        business_years = _first_int(app_info.get("years_in_business"))

        # Current carrier: if filled with a REAL carrier name, the client is
        # already insured. But the Blue Quote uses sentinel strings like
        # "NEW VENTURE" / "N/A" / "NONE" / "TBD" to mean "no prior carrier" —
        # those must NOT be treated as a real carrier (otherwise we'd answer
        # GEICO's "currently insured?" question Yes and mis-rate the policy).
        _NO_CARRIER_SENTINELS = {"", "N/A", "NA", "NONE", "NEW VENTURE", "TBD"}
        current_carrier = (app_info.get("current_carrier") or "").strip()
        if current_carrier.upper() in _NO_CARRIER_SENTINELS:
            current_carrier = ""
        years_cov = _first_int(app_info.get("years_continuous_coverage"))

        is_nv = (business_years is None or business_years == 0) and not current_carrier

        # Parse address. Prefer mailing_address (what GEICO/Progressive use for the
        # owner contact section); fall back to physical_address. The Blue Quote
        # stores them as a single line like "585 NOLAN ST BEAUMONT, TX 77705".
        addr_src = (app_info.get("mailing_address")
                    or app_info.get("physical_address")
                    or "")
        street, city, state_code, zip_code = _parse_us_address(addr_src)

        applicant = ApplicantProfile(
            business_name=app_info.get("business_name") or "",
            owner_name=app_info.get("owners_name") or "",
            usdot=app_info.get("usdot") or "",
            business_years=business_years,
            is_new_venture=is_nv,
            current_carrier=current_carrier,
            years_continuous_coverage=years_cov,
            street_address=street,
            city=city,
            state=state_code or "TX",
            zip_code=zip_code,
            phone=(app_info.get("phone") or "").strip() or None,
            email=(app_info.get("email") or "").strip() or None,
        )

        # Commodity
        commodity = app_info.get("commodities") or ""

        # Coverages — two parallel structures:
        #   * `coverages` (List[str]) — short codes for rule_engine compat
        #   * `coverages_detail` (CoveragesProfile) — full per-field values
        #     used by the MGA field_mappers (Progressive / GEICO) to fill
        #     coverage selections in each portal.
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

        # Build CoveragesProfile from the BlueQuote coverage block.
        # Empty / None values are left at the CoveragesProfile defaults.
        def _str_or_none(v) -> Optional[str]:
            if v is None:
                return None
            s = str(v).strip()
            return s or None

        bi_limit = _str_or_none(cov_data.get("auto_liability_limits"))
        pd_ded = _str_or_none(cov_data.get("physical_damage_deductible"))
        cov_kwargs = {}
        if bi_limit:
            cov_kwargs["bodily_injury_limit"] = bi_limit
        # BlueQuote stores ONE deductible for Phys Damage; apply to both Comp+Coll.
        # If the BQ value is null, leave the CoveragesProfile defaults (which
        # opt-in to $1,000 deductible). Distinguish explicit-null (decline) from
        # missing by checking the raw cov_data key.
        if "physical_damage_deductible" in cov_data:
            if pd_ded:
                cov_kwargs["comp_deductible"] = f"${pd_ded}" if not pd_ded.startswith("$") else pd_ded
                cov_kwargs["coll_deductible"] = cov_kwargs["comp_deductible"]
            else:
                cov_kwargs["comp_deductible"] = None
                cov_kwargs["coll_deductible"] = None
        cargo_limit = _str_or_none(cov_data.get("cargo_limit"))
        if cargo_limit:
            cov_kwargs["motor_truck_cargo_limit"] = cargo_limit
        coverages_detail = CoveragesProfile(**cov_kwargs)

        # Units
        vehicles = extracted.get("vehicles", {})
        trucks = vehicles.get("tractors_trucks_pickup", [])
        trailers = vehicles.get("trailers", [])
        trailer_types = []
        for t in trailers:
            # `type` may be present with an explicit null, so `.get(key, "")`
            # can still return None — coalesce before calling string methods.
            t_type = (t.get("type") or "").upper().strip()
            if t_type and t_type != "UNKNOWN":
                trailer_types.append(t_type)

        # Radius of operation lives at the coverage level in the BlueQuote
        # (one value for the whole policy, e.g. "101-200" or "150 MILES"),
        # not per-vehicle. Propagate it to every VehicleProfile so the MGA
        # mappers can bucket the one-way distance correctly.
        radius_src = (cov_data.get("radius_of_operation")
                      or app_info.get("destinations")
                      or None)
        radius_str = str(radius_src).strip() if radius_src else None

        # Build per-vehicle records (VehicleProfile list). These carry VIN,
        # year, make, etc. that the MGA flows (GEICO VIN decode, Progressive
        # AddVehicle) need. Trucks + trailers are treated uniformly here;
        # downstream mappers split them by trailer_type as needed.
        veh_records: List[VehicleProfile] = []
        for src in (trucks, trailers):
            for t in src:
                year_int = _first_int(t.get("year"))
                veh_records.append(VehicleProfile(
                    vin=(t.get("vin") or "").strip() or None,
                    year=year_int,
                    make=(t.get("make") or "").strip() or None,
                    model=(t.get("model") or "").strip() or None,
                    trailer_type=(t.get("type") or "").strip().upper() or None,
                    gvw=(t.get("gvw") or "").strip() or None,
                    radius_miles=radius_str,
                ))

        units = UnitsProfile(
            count=len(trucks) + len(trailers),
            trailer_types=list(set(trailer_types)),
            vehicles=veh_records,
        )

        # Drivers
        drivers = []
        # 2-letter US state code → full state name (GEICO License State combobox
        # uses full names; some BlueQuotes store codes). Minimal map covering
        # the states we operate in.
        _US_STATE_NAMES = {
            "TX": "Texas", "OK": "Oklahoma", "LA": "Louisiana", "AR": "Arkansas",
            "NM": "New Mexico", "CO": "Colorado", "KS": "Kansas", "MS": "Mississippi",
        }
        for d in extracted.get("driver_information", []):
            exp_raw = d.get("exp_years")
            exp_years = None
            if exp_raw:
                try:
                    exp_years = int(str(exp_raw).strip().lstrip("+"))
                except (ValueError, TypeError):
                    pass
            # BlueQuote stores excluded as "YES"/"NO"/"0"/"1". Treat YES/1/TRUE
            # (case-insensitive) as excluded; everything else (including the
            # bare "0") as not excluded.
            excluded_raw = str(d.get("excluded", "")).strip().upper()
            is_excluded = excluded_raw in {"YES", "Y", "1", "TRUE"}
            # CDL class A/B is the commercial driver standard; treat presence
            # of a class letter as "has CDL".
            cdl_class_raw = (d.get("class") or "").strip().upper()
            # Driver License State: accept 2-letter code or full name; the form
            # mappers normalize as needed.
            dl_state_raw = (d.get("state") or "").strip().upper()
            dl_state_full = _US_STATE_NAMES.get(dl_state_raw, dl_state_raw or None)
            drivers.append(DriverProfile(
                name=(d.get("name") or "").strip(),
                cdl_present=bool(cdl_class_raw),
                cdl_years=exp_years,
                cdl_class=cdl_class_raw or None,
                license_number=(d.get("dl_number") or "").strip() or None,
                license_state=dl_state_full,
                date_of_birth=(d.get("dob") or "").strip() or None,
                exclude_from_policy=is_excluded,
            ))

        return applicant, commodity, coverages, units, drivers, coverages_detail

    # ---- Blue Quote helpers ----

    def _is_blue_quote_sufficient(
        self,
        applicant: ApplicantProfile,
        commodity: str,
        units: UnitsProfile,
        drivers: List[DriverProfile],
        coverages: List[str],
    ) -> bool:
        """
        Decide whether the form-based BlueQuote extraction produced enough data.

        We consider the result sufficient if BOTH:
          - business_name is non-empty
          - at least one of (commodity, drivers, units, coverages) has data
        """
        if not (applicant.business_name and applicant.business_name.strip()):
            return False
        has_payload = bool(
            (commodity and commodity.strip())
            or drivers
            or units.count > 0
            or coverages
        )
        return has_payload

    def _extract_blue_quote_with_ai(self, att: dict, profile: QuoteProfile) -> bool:
        """
        Vision/text fallback for Blue Quote: send the PDF to the AI and map the
        result into the profile. Returns True if at least business_name was set.

        Strategy:
          1. Try with the default content extraction (text-first).
          2. If that returns no usable business_name (common with flattened forms
             where the text layer only contains labels), retry forcing vision.
        """
        # Pass 1: default (text first, vision if no text)
        content = self._extract_content(att["filename"], att["data"])
        self._debug_content("BLUE QUOTE", att["filename"], content)

        ai_data = self._extract_ai_document("BLUE QUOTE", content) if content else None
        business_name = (ai_data or {}).get("business_name") if ai_data else None

        # Pass 2: if first pass was text-only and produced no business_name,
        # retry forcing vision — flattened Blue Quote PDFs hide values from text.
        if (not business_name) and content and content.get("type") == "text":
            print(f"    Blue Quote: text pass returned empty business_name → retrying with vision")
            content = self._extract_content(att["filename"], att["data"], force_vision=True)
            self._debug_content("BLUE QUOTE", att["filename"], content)
            if content:
                ai_data = self._extract_ai_document("BLUE QUOTE", content)

        if not ai_data:
            return False

        business_years = ai_data.get("business_years")
        is_nv = ai_data.get("is_new_venture")
        if is_nv is None:
            is_nv = business_years is None or business_years == 0

        profile.applicant = ApplicantProfile(
            business_name=ai_data.get("business_name") or "",
            owner_name=ai_data.get("owner_name") or "",
            owner_age=ai_data.get("owner_age"),
            usdot=ai_data.get("usdot") or "",
            business_years=business_years,
            is_new_venture=bool(is_nv),
        )
        profile.commodity = ai_data.get("commodity") or ""
        profile.coverages = ai_data.get("coverages") or []
        profile.units = UnitsProfile(
            count=ai_data.get("unit_count") or 0,
            trailer_types=ai_data.get("trailer_types") or [],
        )
        # Replace drivers entirely (don't append) so a retry doesn't duplicate
        profile.drivers = []
        for d in (ai_data.get("drivers") or []):
            profile.drivers.append(DriverProfile(
                name=d.get("name") or "",
                cdl_years=d.get("exp_years"),
            ))

        return bool(profile.applicant.business_name)

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

        # Step 1: Classify attachments by FILENAME only.
        # No AI fallback — avoids misclassifying unrelated docs as CDL, Loss Run, etc.
        classified: dict = {}  # doc_type -> attachment
        unclassified: list = []

        for att in attachments:
            filename = att["filename"]
            matched_type: Optional[str] = None
            for doc_type in DOC_TYPES:
                if self.validator._matches_document(filename, doc_type):
                    matched_type = doc_type
                    break
            if matched_type is None:
                # Check APP variants
                if self.validator._matches_app_invo(filename) or self.validator._matches_app_general(filename):
                    matched_type = "NEW VENTURE APP"

            if matched_type is None:
                unclassified.append(filename)
                print(f"    Skipped (no match): {filename}")
                continue

            if matched_type in classified:
                # Slot already taken — keep the first match
                print(f"    Skipped (duplicate {matched_type}): {filename}")
                continue

            classified[matched_type] = att
            profile.documents_present.append(matched_type)
            print(f"    Classified: {filename} → {matched_type}")

        # Step 2: Extract Blue Quote
        # Try the form-based BlueQuotePDFExtractor first; fall back to AI vision
        # if it raises OR if the extracted data is insufficient (flat/scanned PDF).
        if "BLUE QUOTE" in classified:
            att = classified["BLUE QUOTE"]
            bq_used_ai = False
            bq_fallback_reason = None

            # --- 2a) Try the form-based extractor ---
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                    tmp.write(att["data"])
                    tmp_path = tmp.name

                try:
                    extractor = BlueQuotePDFExtractor(tmp_path)
                    bq_data = extractor.extract()
                finally:
                    Path(tmp_path).unlink(missing_ok=True)

                applicant, commodity, coverages, units, drivers, coverages_detail = self._map_blue_quote_to_profile(bq_data)

                if self._is_blue_quote_sufficient(applicant, commodity, units, drivers, coverages):
                    profile.applicant = applicant
                    profile.commodity = commodity
                    profile.coverages = coverages
                    profile.coverages_detail = coverages_detail
                    profile.units = units
                    profile.drivers = drivers
                    print(f"    Blue Quote extracted: {applicant.business_name}, commodity={commodity}")
                else:
                    bq_fallback_reason = (
                        f"insufficient form data "
                        f"(business_name='{applicant.business_name}', commodity='{commodity}', "
                        f"drivers={len(drivers)}, units={units.count}, coverages={len(coverages)})"
                    )
            except Exception as e:
                bq_fallback_reason = f"extractor raised: {e}"

            # --- 2b) AI fallback ---
            if bq_fallback_reason:
                print(f"    Blue Quote: {bq_fallback_reason} → trying AI fallback")
                if self._extract_blue_quote_with_ai(att, profile):
                    bq_used_ai = True
                    print(
                        f"    Blue Quote (AI): {profile.applicant.business_name}, "
                        f"commodity={profile.commodity}, drivers={len(profile.drivers)}, "
                        f"units={profile.units.count}"
                    )
                else:
                    print(f"    WARN: Blue Quote AI fallback also failed")
                    confidence_flags.append(
                        ConfidenceFlag("blue_quote", "Blue Quote could not be extracted by form parser or AI")
                    )

        # Step 3: Extract CDL (AI) — update driver-level data
        if "CDL" in classified:
            att = classified["CDL"]
            content = self._extract_content(att["filename"], att["data"])
            self._debug_content("CDL", att["filename"], content)
            if content:
                ai_data = self._extract_ai_document("CDL", content)
                if ai_data:
                    driver_name = (ai_data.get("driver_name") or "").upper()
                    ai_years = ai_data.get("cdl_years")
                    ai_class = ai_data.get("cdl_class")
                    # Try to match to existing driver
                    matched = False
                    target_drv = None
                    for drv in profile.drivers:
                        if driver_name and driver_name in drv.name.upper():
                            target_drv = drv
                            matched = True
                            break
                    if not matched and profile.drivers:
                        target_drv = profile.drivers[0]
                    if target_drv is None:
                        target_drv = DriverProfile(name=ai_data.get("driver_name") or "")
                        profile.drivers.append(target_drv)

                    target_drv.cdl_present = True
                    if ai_years:  # only override if AI returned a real number
                        target_drv.cdl_years = ai_years
                    if ai_class:
                        target_drv.cdl_class = ai_class
                    target_drv.cdl_is_residential = ai_data.get("is_residential", False)

                    final_years = target_drv.cdl_years
                    src = "AI" if ai_years else ("BlueQuote" if final_years is not None else "missing")
                    print(f"    CDL extracted: {target_drv.name or ai_data.get('driver_name')}, {final_years} years (source: {src})")
                    if final_years is None or final_years == 0:
                        print(f"    WARN: CDL years could not be determined for {target_drv.name}")
                        # Note: the critical 'cdl_years' flag is added centrally in Step 8
                        # to avoid duplicates; here we only keep an informational flag.
                        # Note: critical 'cdl_years' flag is added centrally in Step 8.
                else:
                    print(f"    WARN: AI returned no data for CDL document")
                    # Note: critical 'cdl_years' flag is added centrally in Step 8.

        # Step 4: Extract MVR (AI) — update driver-level data
        if "MVR" in classified:
            att = classified["MVR"]
            content = self._extract_content(att["filename"], att["data"])
            self._debug_content("MVR", att["filename"], content)
            if content:
                ai_data = self._extract_ai_document("MVR", content)
                if ai_data:
                    driver_name = (ai_data.get("driver_name") or "").upper()
                    ai_years = ai_data.get("years_covered")
                    ai_clean = ai_data.get("is_clean")

                    target_drv = None
                    for drv in profile.drivers:
                        if driver_name and driver_name in drv.name.upper():
                            target_drv = drv
                            break
                    if target_drv is None and profile.drivers:
                        target_drv = profile.drivers[0]

                    if target_drv is not None:
                        target_drv.mvr_present = True
                        target_drv.mvr_years_covered = ai_years
                        target_drv.mvr_is_clean = bool(ai_clean) if ai_clean is not None else False

                    print(f"    MVR extracted: {ai_years} years, clean={ai_clean}")
                    if ai_years is None or ai_years == 0:
                        print(f"    WARN: MVR years_covered could not be determined")
                        confidence_flags.append(ConfidenceFlag("mvr_years", "MVR years_covered could not be determined"))
                    if ai_clean is None:
                        print(f"    WARN: MVR is_clean could not be determined")
                        confidence_flags.append(ConfidenceFlag("mvr_clean", "MVR is_clean could not be determined"))
                else:
                    print(f"    WARN: AI returned no data for MVR document")
                    confidence_flags.append(ConfidenceFlag("mvr", "AI failed to extract MVR data"))

        # Step 5: Extract Loss Run (AI)
        if "LOSS RUN" in classified:
            att = classified["LOSS RUN"]
            content = self._extract_content(att["filename"], att["data"])
            self._debug_content("LOSS RUN", att["filename"], content)
            if content:
                ai_data = self._extract_ai_document("LOSS RUN", content)
                if ai_data:
                    ai_years = ai_data.get("years_covered")
                    ai_clean = ai_data.get("is_clean")
                    profile.loss_run = LossRunProfile(
                        present=True,
                        years_covered=ai_years,
                        is_clean=bool(ai_clean) if ai_clean is not None else False,
                        total_claims=ai_data.get("total_claims") or 0,
                    )
                    print(f"    Loss Run extracted: {ai_years} years, clean={ai_clean}, claims={profile.loss_run.total_claims}")
                    if ai_years is None or ai_years == 0:
                        print(f"    WARN: Loss Run years_covered could not be determined")
                        confidence_flags.append(ConfidenceFlag("loss_run_years", "Loss Run years_covered could not be determined"))
                    if ai_clean is None:
                        print(f"    WARN: Loss Run is_clean could not be determined")
                        confidence_flags.append(ConfidenceFlag("loss_run_clean", "Loss Run is_clean could not be determined"))
                else:
                    profile.loss_run.present = True  # Document exists but extraction failed
                    print(f"    WARN: AI returned no data for Loss Run document")
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
            ("commodity", profile.commodity),
        ]
        # business_years only critical for established businesses (New Venture has no years by definition)
        if not profile.applicant.is_new_venture:
            critical_fields.append(("business_years", profile.applicant.business_years))
        # cdl_years only critical when a CDL document was actually attached.
        # If the email had no CDL doc, we trust whatever the BlueQuote driver section
        # provided (even if empty) and let the rule engine handle missing years.
        if profile.drivers and "CDL" in classified:
            critical_fields.append(("cdl_years", profile.drivers[0].cdl_years))

        for field_name, value in critical_fields:
            if value is None or value == "":
                confidence_flags.append(ConfidenceFlag(field_name, f"Critical field '{field_name}' is missing"))

        profile.extraction_confidence = ExtractionConfidence(
            overall="low" if any(f.field in ["business_years", "cdl_years", "commodity"] for f in confidence_flags) else "high",
            flags=confidence_flags
        )

        return profile
