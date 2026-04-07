# Rule Engine Design — H2O Quote RPA

## Problem

The MGA sheet in the Excel has ~74 free-text comments describing requirements for each MGA to accept a quote. These need to be:
1. Evaluated automatically against data extracted from 6 documents (pre-filter)
2. Used to inform the client what requirements are missing (informative)

Currently only document presence is validated. The actual business rules (min years, CDL experience, coverage types, etc.) are not evaluated.

## Solution: AI Extraction + Deterministic Rule Engine

Split the problem into two parts:
- **AI handles the hard part**: extracting structured data from varied document formats
- **Deterministic engine handles the critical part**: evaluating rules with 100% accuracy

## Architecture

```
Email with 6 documents
        |
        v
+----------------------------+
| document_ai_extractor.py   |  <-- NEW: AI-powered extraction
| - Classifies document type |
| - Detects PDF text vs scan |
| - Uses GPT-5.4 via proxy   |
| - Per-document prompts      |
+----------------------------+
        |
        v
  Quote Profile (JSON)
        |
        v
+----------------------------+
| rule_engine.py             |  <-- NEW: Deterministic evaluation
| - Reads REGLAS sheet       |
| - Compares profile vs rules|
| - Returns pass/fail + why  |
+----------------------------+
        |
        v
  Eligible MGAs + Missing Requirements
        |
        v
  (existing) workflow_orchestrator.py
  - Sends to eligible MGAs
  - Informs client of missing items
  - Uploads to Google Drive (unchanged)
```

## Component 1: document_ai_extractor.py

### Purpose
Extract structured data from all 6 document types into a single standardized JSON.

### Input
List of email attachments (filename + binary data)

### Document Classification

Two-step approach to determine document type:

1. **Filename matching (primary)**: Reuse the existing pattern matching from `AttachmentValidator._matches_document()`. Filenames follow the convention `YYYYMMDD [DOC TYPE].PDF` (e.g., `20260126 BLUE QUOTE.pdf`, `20260126 MVR.pdf`).

2. **AI classification (fallback)**: When filename does not match any known pattern, send the first page to GPT-5.4 with a classification prompt: "This is one of: BLUE QUOTE, MVR, CDL, IFTAS, LOSS RUN, NEW VENTURE APP. Which one is it? Return only the document type name."

If neither method identifies the document, it is skipped and logged as unclassified.

### Content Detection Logic
1. If file is PDF: try pdfplumber text extraction first
2. If extracted text is empty/minimal (< 50 chars): treat as scanned PDF, convert first page to image via `pymupdf` (fitz)
3. If file is image (JPG, PNG): use directly as base64
4. Send content to GPT-5.4 via local proxy (localhost:3000/v1)

### Blue Quote Extraction Strategy

The existing `BlueQuotePDFExtractor` (pdf_extractor.py) uses form-field extraction which works well for structured Blue Quote PDFs. The new extractor uses it as the **primary method** for Blue Quote documents:

1. Try `BlueQuotePDFExtractor.extract()` first
2. Map its output to the Quote Profile schema (field name translation: `years_in_business` → `business_years`, coverage booleans → coverage list, vehicle lists → unit count, etc.)
3. If the existing extractor fails or returns insufficient data (e.g., flattened/scanned PDF), fall back to AI extraction

For the other 5 documents (MVR, CDL, IFTAS, Loss Run, APP), always use AI extraction since there is no existing parser for them.

### Per-Document Prompts
Each document type has a specific system prompt requesting specific fields as JSON:

**BLUE QUOTE prompt extracts** (AI fallback only):
- business_years (int or null)
- commodity (string)
- coverages (list: AL, MTC, APD, GL)
- unit_count (int)
- owner_age (int or null)
- owner_name (string)
- business_name (string)
- trailer_types (list: DRY VAN, END DUMP, LOWBOY, SANDBOX, etc.)
- is_new_venture (bool)
- usdot (string)
- drivers (list of driver objects)

**CDL prompt extracts:**
- driver_name (string)
- issue_date (string YYYY-MM-DD)
- cdl_years (int, calculated from issue_date)
- cdl_class (string: A, B, C)
- state (string)
- is_residential (bool)

**MVR prompt extracts:**
- driver_name (string)
- years_covered (int)
- violations (list or empty)
- is_clean (bool)

**LOSS RUN prompt extracts:**
- years_covered (int)
- has_losses (bool)
- is_clean (bool)
- total_claims (int)

**IFTAS prompt extracts:**
- is_registered (bool)
- state (string or null)

**APP (New Venture Application) prompt extracts:**
- ein (string or null)
- industry_experience_years (int or null)
- additional_questions_filled (bool)

### Multi-Driver Handling

Commercial trucking quotes often have multiple drivers. The system handles this as follows:

- The Blue Quote lists all drivers with basic info
- CDL and MVR documents may arrive as one per driver, or as a combined report
- The AI prompt for CDL/MVR includes `driver_name` to enable matching
- The Quote Profile stores driver-level data in the `drivers` array
- **Rule evaluation uses the LEAST favorable driver**: if any driver fails a rule (e.g., CDL years < 2), the MGA is marked as ineligible for that rule. This is the conservative approach required for 100% accuracy.

### Output: Quote Profile JSON
```json
{
  "applicant": {
    "business_name": "Y K G TRUCKING",
    "owner_name": "ANGELA Y ZALDANA",
    "owner_age": 35,
    "usdot": "3594095",
    "business_years": 3,
    "is_new_venture": false,
    "industry_experience_years": 5
  },
  "commodity": "DIRT, SAND & GRAVEL",
  "coverages": ["AL", "MTC", "APD"],
  "units": {
    "count": 4,
    "trailer_types": ["END DUMP"]
  },
  "drivers": [
    {
      "name": "ANGELA ZALDANA",
      "cdl_present": true,
      "cdl_years": 2,
      "cdl_class": "A",
      "cdl_is_residential": false,
      "mvr_present": true,
      "mvr_years_covered": 5,
      "mvr_is_clean": true
    }
  ],
  "loss_run": {
    "present": true,
    "years_covered": 5,
    "is_clean": true
  },
  "iftas": {
    "present": true,
    "is_registered": true
  },
  "app": {
    "present": true,
    "ein_included": true,
    "questions_filled": true
  },
  "documents_present": ["BLUE QUOTE", "MVR", "CDL", "IFTAS", "LOSS RUN", "APP"],
  "extraction_confidence": {
    "overall": "high",
    "flags": []
  }
}
```

### Confidence Handling
When the AI cannot extract a field with confidence:
- Set field to null
- Add entry to `extraction_confidence.flags` array: `{"field": "cdl_years", "reason": "Document quality too low to read date"}`
- If any critical field has null, overall confidence drops to "low"
- Critical fields: business_years, cdl_years, commodity
- When confidence is "low", the orchestrator halts the workflow and sends a notification requesting human review instead of proceeding automatically

### Error Handling

- **Proxy unreachable**: Retry up to 3 times with 5-second delay. If still unreachable, mark document as "extraction_failed" and halt workflow with notification.
- **Timeout**: 60-second timeout per document extraction call. On timeout, retry once, then mark as failed.
- **Malformed JSON from AI**: Attempt to parse with json.loads(). If it fails, strip markdown code fences and retry parse. If still invalid, retry the AI call once with an explicit "return only valid JSON" instruction. If still failing, mark field as null and flag.
- **Proxy down for all documents**: Halt entire workflow, log error, send admin notification.

## Component 2: Excel Sheet "REGLAS"

### Purpose
Replace free-text COMENTARIOS with structured, machine-readable columns.

### Location
New sheet "REGLAS" in the existing `config/CHECK LIST (2)_ESTANDARIZADO.xlsx`

### Relationship with MGA Sheet

The MGA sheet continues to handle the **routing** (tipo_negocio → list of candidate MGAs with NEW VENTURE filter). The REGLAS sheet handles the **eligibility evaluation** for each candidate.

Join strategy: The orchestrator gets candidate MGAs from the MGA sheet (existing behavior via `mga_reader.py`). Then for each candidate MGA, it looks up the matching row in REGLAS by `MGA + TIPO_DE_NEGOCIO` for rule evaluation. If no REGLAS row exists for a given MGA + tipo_negocio combination, the MGA is treated as eligible with no additional requirements (backwards-compatible behavior).

### Columns

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| MGA | string | MGA name (links to MGA sheet) | CANAL |
| TIPO_DE_NEGOCIO | string | Business type (links to MGA sheet) | DIRT, SAND & GRAVEL |
| MIN_BUSINESS_YEARS | int or empty | Minimum years in business | 2 |
| MIN_CDL_YEARS | int or empty | Minimum CDL experience years | 2 |
| REQUIRES_MVR | YES/NO | Must have MVR document | YES |
| MVR_MIN_YEARS | int or empty | Minimum years MVR must cover | 5 |
| REQUIRES_IFTAS | YES/NO/SI_APLICA | IFTAS requirement | SI_APLICA |
| REQUIRES_LOSS_RUN | YES/NO/SI_APLICA | Loss run requirement | YES |
| LOSS_RUN_MIN_YEARS | int or empty | Min years loss run must cover | 5 |
| LOSSES_MUST_BE_CLEAN | YES/NO | Requires clean loss history | NO |
| REQUIRES_APP | YES/NO | Requires filled application | YES |
| REQUIRES_EIN | YES/NO | Requires EIN document | NO |
| REQUIRES_QUESTIONS | YES/NO | Requires questionnaire | NO |
| REQUIRES_REGISTRATIONS | YES/NO | Requires vehicle registrations | NO |
| MIN_UNITS | int or empty | Minimum number of units | 5 |
| MIN_OWNER_AGE | int or empty | Minimum owner age | 30 |
| MIN_INDUSTRY_EXP_YEARS | int or empty | Min industry experience | 3 |
| ALLOWED_COVERAGES | comma list or empty | If set, only these coverages accepted | APD,MTC,GL |
| BLOCKED_TRAILER_TYPES | comma list or empty | Trailer types NOT accepted | DUMP |
| BLOCKED_COMMODITIES | comma list or empty | Keywords that disqualify | FERTILIZANTES |
| ALLOWED_TRAILER_TYPES | comma list or empty | If set, ONLY these trailers accepted | LOWBOY,SANDBOX |
| ROUTING | string or empty | Informational: internal routing note | SOLO_NICO |
| DOWN_PAYMENT_PCT | int or empty | Informational: down payment % | 25 |
| MIN_PRICE | int or empty | Informational: minimum premium | 25000 |
| SPECIAL_FORM | string or empty | Informational: special form needed | FORM_5C |
| NOTES | string | Human-readable notes (not evaluated) | Condados prohibidos: Harris... |

### Column Behavior Rules
- Empty cell = no restriction for that dimension
- `SI_APLICA` = treated as a soft pass with warning. The rule engine marks it as "conditionally required" in the evaluation output rather than pass/fail. The IFTAS example: if `REQUIRES_IFTAS = SI_APLICA` and IFTAS is not present, the MGA is still eligible but the evaluation includes a warning: "IFTAS may be required if interstate operations apply."
- Comma-separated lists for multi-value fields
- `ALLOWED_*` columns are allow-lists: if populated, only the listed values are accepted. If empty, everything is accepted. Allow-lists take precedence over block-lists if both are populated for the same dimension (the block-list is ignored).
- `ROUTING`, `DOWN_PAYMENT_PCT`, `MIN_PRICE`, `SPECIAL_FORM` are **informational columns**: they are NOT evaluated by the rule engine. They are passed through to the client communication email so the client knows about these conditions. This keeps the rule engine focused on evaluable criteria.
- `NOTES` is informational only, included in client email for context.

### Data Migration

The initial population of the REGLAS sheet will be done by:
1. Script reads existing COMENTARIOS from MGA sheet
2. Uses AI (GPT-5.4) to decompose each free-text comment into the structured columns
3. Human reviews and validates the AI-generated structured data
4. Validated data is written to the REGLAS sheet

A validation script runs on startup to check:
- Every MGA + TIPO_DE_NEGOCIO in REGLAS has a corresponding row in the MGA sheet
- No unknown values in YES/NO/SI_APLICA columns
- Numeric columns contain only numbers or are empty

## Component 3: rule_engine.py

### Purpose
Deterministic evaluation of quote profile against MGA rules.

### Input
- Quote Profile JSON (from document_ai_extractor)
- Tipo de negocio (from commodity mapper, using the `commodity` field from the Quote Profile)

### Commodity Mapper Integration

The commodity value fed to `COMMTDNMapper.map_commodity_to_type()` comes from the Quote Profile's `commodity` field. When the Blue Quote is extracted via the existing `BlueQuotePDFExtractor` (primary path), this field is mapped from `applicant_info.commodities`. When extracted via AI fallback, the prompt explicitly requests the commodity in the same format. The commodity mapper itself is unchanged.

### Logic

```python
class RuleEngine:
    def evaluate(self, profile: dict, tipo_negocio: str) -> list[MGAEvaluation]:
        """
        Evaluate all MGAs for a business type against the quote profile.

        Returns list of MGAEvaluation with:
        - mga_name: str
        - eligible: bool
        - passed_rules: list[str]
        - failed_rules: list[FailedRule]  # rule_name + reason + current_value + required_value
        - warnings: list[str]  # SI_APLICA and informational items
        - informational: dict  # ROUTING, DOWN_PAYMENT_PCT, MIN_PRICE, SPECIAL_FORM, NOTES
        """
```

### Evaluation per rule (pseudocode):
```
For each MGA row matching tipo_negocio in REGLAS sheet:
  failures = []
  warnings = []

  # --- Numeric thresholds ---
  if MIN_BUSINESS_YEARS and profile.applicant.business_years < MIN_BUSINESS_YEARS:
      failures.append("Business years: has {X}, needs {Y}")

  if MIN_OWNER_AGE and profile.applicant.owner_age < MIN_OWNER_AGE:
      failures.append("Owner age: is {X}, needs min {Y}")

  if MIN_UNITS and profile.units.count < MIN_UNITS:
      failures.append("Unit count: has {X}, needs min {Y}")

  if MIN_INDUSTRY_EXP_YEARS and profile.applicant.industry_experience_years < MIN_INDUSTRY_EXP_YEARS:
      failures.append("Industry experience: has {X} years, needs {Y}")

  # --- Driver-level rules (use least favorable) ---
  if MIN_CDL_YEARS:
      for driver in profile.drivers:
          if driver.cdl_years < MIN_CDL_YEARS:
              failures.append("Driver {name}: CDL {X} years, needs {Y}")

  # --- Document presence ---
  if REQUIRES_MVR == "YES" and not any(d.mvr_present for d in profile.drivers):
      failures.append("Missing document: MVR")

  if REQUIRES_IFTAS == "YES" and not profile.iftas.present:
      failures.append("Missing document: IFTAS")
  elif REQUIRES_IFTAS == "SI_APLICA" and not profile.iftas.present:
      warnings.append("IFTAS may be required if interstate operations apply")

  if REQUIRES_LOSS_RUN == "YES" and not profile.loss_run.present:
      failures.append("Missing document: LOSS RUN")
  elif REQUIRES_LOSS_RUN == "SI_APLICA" and not profile.loss_run.present:
      warnings.append("Loss run may be required depending on history")

  if MVR_MIN_YEARS:
      for driver in profile.drivers:
          if driver.mvr_present and driver.mvr_years_covered < MVR_MIN_YEARS:
              failures.append("Driver {name}: MVR covers {X} years, needs {Y}")

  if LOSS_RUN_MIN_YEARS and profile.loss_run.years_covered < LOSS_RUN_MIN_YEARS:
      failures.append("Loss run covers {X} years, needs {Y}")

  if LOSSES_MUST_BE_CLEAN == "YES" and not profile.loss_run.is_clean:
      failures.append("Loss run must be clean (no claims)")

  if REQUIRES_APP == "YES" and not profile.app.present:
      failures.append("Missing document: APP")

  if REQUIRES_EIN == "YES" and not profile.app.ein_included:
      failures.append("Missing: EIN")

  if REQUIRES_QUESTIONS == "YES" and not profile.app.questions_filled:
      failures.append("Missing: questionnaire not filled")

  # --- Coverage rules ---
  if ALLOWED_COVERAGES:
      allowed = set(ALLOWED_COVERAGES.split(","))
      requested = set(profile.coverages)
      disallowed = requested - allowed
      if disallowed:
          failures.append("Coverage not accepted: {disallowed}")

  # --- Trailer rules (ALLOWED takes precedence over BLOCKED) ---
  if ALLOWED_TRAILER_TYPES:
      allowed = set(ALLOWED_TRAILER_TYPES.split(","))
      actual = set(profile.units.trailer_types)
      disallowed = actual - allowed
      if disallowed:
          failures.append("Trailer type not in allow list: {disallowed}")
  elif BLOCKED_TRAILER_TYPES:
      blocked = set(BLOCKED_TRAILER_TYPES.split(","))
      actual = set(profile.units.trailer_types)
      overlap = blocked & actual
      if overlap:
          failures.append("Blocked trailer type: {overlap}")

  # --- Commodity restrictions ---
  if BLOCKED_COMMODITIES:
      for keyword in BLOCKED_COMMODITIES.split(","):
          if keyword.strip().upper() in profile.commodity.upper():
              failures.append("Blocked commodity keyword: {keyword}")

  # --- Collect informational columns ---
  informational = {
      "routing": row.ROUTING or None,
      "down_payment_pct": row.DOWN_PAYMENT_PCT or None,
      "min_price": row.MIN_PRICE or None,
      "special_form": row.SPECIAL_FORM or None,
      "notes": row.NOTES or None
  }

  mga_evaluation = MGAEvaluation(
      mga_name=row.MGA,
      eligible=len(failures) == 0,
      passed_rules=[...],
      failed_rules=failures,
      warnings=warnings,
      informational=informational
  )
```

### Output: List of MGAEvaluation
```python
[
    MGAEvaluation(
        mga_name="INVO",
        eligible=True,
        passed_rules=["MIN_CDL_YEARS", "REQUIRES_MVR", ...],
        failed_rules=[],
        warnings=["IFTAS may be required if interstate operations apply"],
        informational={"routing": None, "down_payment_pct": None, ...}
    ),
    MGAEvaluation(
        mga_name="CANAL",
        eligible=False,
        passed_rules=["MIN_CDL_YEARS", ...],
        failed_rules=[
            FailedRule(
                rule="MIN_BUSINESS_YEARS",
                reason="Business has 1 year, minimum is 2",
                current_value=1,
                required_value=2
            )
        ],
        warnings=[],
        informational={"routing": "SOLO_NICO", "down_payment_pct": 25, ...}
    )
]
```

## Integration with Existing Workflow

### Changes to workflow_orchestrator.py

The orchestrator gets new steps between document finding and MGA email sending:

```
Current flow:
  1. Find PDF → 2. Extract commodity → 3. Map to tipo_negocio →
  4. Get MGAs → 5. Validate documents exist → 6. Send to MGAs → 7. Upload to Drive

New flow:
  1. Find all attachments
  2. Classify + extract data from ALL documents via AI → Quote Profile
  3. Map commodity to tipo_negocio (existing, using profile.commodity)
  4. Get candidate MGAs (existing, from MGA sheet)
  5. Evaluate rules for each candidate MGA (NEW, from REGLAS sheet)
  6. For eligible MGAs: send email with documents (existing)
  7. For ineligible MGAs: log why, include in client summary (NEW)
  8. Upload to Google Drive (existing, unchanged)
```

### Changes to attachment_validator.py
- Simplified: only checks document presence, no longer the primary gatekeeper
- Rule engine handles the business logic validation

### Client Communication
When MGAs fail rule evaluation, the client email includes:
- Which MGAs were eligible and received documents
- Which MGAs were not eligible and why (human-readable reasons from FailedRule)
- Warnings for SI_APLICA conditions
- Informational items (down payment, min price, special forms, notes)

## Files to Create/Modify

### New files:
- `modules/document_ai_extractor.py` — AI document extraction with classification
- `modules/rule_engine.py` — Deterministic rule evaluation

### Modified files:
- `workflow_orchestrator.py` — Add extraction + rule evaluation steps
- `modules/attachment_validator.py` — Simplify to presence-only check
- `config/CHECK LIST (2)_ESTANDARIZADO.xlsx` — Add REGLAS sheet
- `config/settings.yaml` — Add rule engine settings
- `requirements.txt` — Add: `pymupdf` (PDF to image), `Pillow` (image handling). Note: `openai` is already used but should be explicitly listed.

### Unchanged:
- `modules/comm_tdn_mapper.py` — Still maps commodity → tipo_negocio
- `modules/mga_reader.py` — Still reads MGA list from MGA sheet
- `modules/email_sender.py` — Still sends emails
- `modules/ai_commodity_classifier.py` — Still classifies commodities
- `modules/mga_email_reader.py` — Still reads MGA emails
- `modules/drive_manager.py` — Still uploads to Google Drive
