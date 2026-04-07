"""
Migration Script: COMENTARIOS -> REGLAS columns (v2)

Reads the MGA sheet from the xlsb checklist, sends each unique COMENTARIOS
to AI for decomposition, validates completeness, auto-corrects, and outputs CSV.

Usage:
    python scripts/migrate_rules.py
"""

import csv
import json
import os
import re
import sys
import time
from pathlib import Path

import openai
from pyxlsb import open_workbook
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
XLSB_PATH = PROJECT_ROOT / "Reglas de Negocio" / "CHECK LIST (1) (2).xlsb"
MGA_SHEET_NAME = "MGA"
OUTPUT_CSV = Path(__file__).resolve().parent / "reglas_migrated_v2.csv"

AI_MODEL = "openai/gpt-5.4"
AI_DELAY_SECONDS = 2

RULE_COLUMNS = [
    "MGA",
    "TIPO_DE_NEGOCIO",
    "NEW_VENTURE_COLUMN",
    "COMENTARIO_ORIGINAL",
    "IS_NEW_VENTURE",
    "MIN_BUSINESS_YEARS",
    "MIN_CDL_YEARS",
    "REQUIRES_MVR",
    "MVR_MIN_YEARS",
    "REQUIRES_IFTAS",
    "REQUIRES_LOSS_RUN",
    "LOSS_RUN_MIN_YEARS",
    "LOSSES_MUST_BE_CLEAN",
    "REQUIRES_APP",
    "REQUIRES_EIN",
    "REQUIRES_QUESTIONS",
    "REQUIRES_REGISTRATIONS",
    "MIN_UNITS",
    "MIN_OWNER_AGE",
    "MIN_INDUSTRY_EXP_YEARS",
    "ALLOWED_COVERAGES",
    "BLOCKED_TRAILER_TYPES",
    "BLOCKED_COMMODITIES",
    "ALLOWED_TRAILER_TYPES",
    "ROUTING",
    "DOWN_PAYMENT_PCT",
    "MIN_PRICE",
    "SPECIAL_FORM",
    "NOTAS_EXTRA",
]

AI_FIELDS = RULE_COLUMNS[4:]  # Everything after COMENTARIO_ORIGINAL

DECOMPOSE_PROMPT = """You are an expert underwriter for commercial trucking insurance in the USA.
You must decompose an MGA requirement comment into structured fields. Be EXHAUSTIVE — every piece of information in the comment MUST appear in one of the fields below or in NOTAS_EXTRA. Nothing can be lost.

RULES FOR CLASSIFICATION:
- IS_NEW_VENTURE: "YES" ONLY if the comment explicitly says "NV", "New Venture", or "nuevo negocio". If it asks for years in business (e.g., "2+ años en el negocio"), that means it is NOT new venture, set to "NO". If unclear, set "UNKNOWN".
- ROUTING: if comment says "Solo con NICO", "Solo NICO", "NV solo NICO", set to "SOLO_NICO". If says "Canal test drive", include "TEST_DRIVE_CANAL". Otherwise null.
- NOTAS_EXTRA: ANY part of the comment that does NOT fit into the other structured fields MUST go here. Do NOT leave information out. This includes special conditions, exceptions, company-specific rules, geographic restrictions, vehicle type restrictions, etc.

Return ONLY valid JSON:
{{
  "IS_NEW_VENTURE": "YES" or "NO" or "UNKNOWN",
  "MIN_BUSINESS_YEARS": int or null,
  "MIN_CDL_YEARS": int or null,
  "REQUIRES_MVR": "YES" or "NO",
  "MVR_MIN_YEARS": int or null,
  "REQUIRES_IFTAS": "YES" or "NO" or "SI_APLICA",
  "REQUIRES_LOSS_RUN": "YES" or "NO" or "SI_APLICA",
  "LOSS_RUN_MIN_YEARS": int or null,
  "LOSSES_MUST_BE_CLEAN": "YES" or "NO",
  "REQUIRES_APP": "YES" or "NO",
  "REQUIRES_EIN": "YES" or "NO",
  "REQUIRES_QUESTIONS": "YES" or "NO",
  "REQUIRES_REGISTRATIONS": "YES" or "NO",
  "MIN_UNITS": int or null,
  "MIN_OWNER_AGE": int or null,
  "MIN_INDUSTRY_EXP_YEARS": int or null,
  "ALLOWED_COVERAGES": "comma separated" or null,
  "BLOCKED_TRAILER_TYPES": "comma separated" or null,
  "BLOCKED_COMMODITIES": "comma separated" or null,
  "ALLOWED_TRAILER_TYPES": "comma separated" or null,
  "ROUTING": string or null,
  "DOWN_PAYMENT_PCT": int or null,
  "MIN_PRICE": int or null,
  "SPECIAL_FORM": string or null,
  "NOTAS_EXTRA": string or null
}}

Comment: "{comment_text}"
"""

VALIDATION_PROMPT = """You are a QA validator. I have an original insurance MGA requirement comment and a structured decomposition of it.

Your job: check if ALL information from the original comment is captured in the structured fields. If anything is MISSING, return a corrected JSON with the missing info added. If everything is captured, return the exact same JSON unchanged.

Original comment: "{comment_text}"

Current decomposition:
{current_json}

RULES:
- Every concept, condition, restriction, number, or requirement in the original comment MUST appear in one of the structured fields OR in NOTAS_EXTRA.
- If something is missing, add it to the appropriate field or to NOTAS_EXTRA.
- Return ONLY the corrected JSON (same structure), nothing else.
"""


# ---------------------------------------------------------------------------
# AI client
# ---------------------------------------------------------------------------
def build_openai_client() -> openai.OpenAI:
    base_url = os.getenv("OPENAI_BASE_URL", "http://localhost:3000/v1")
    api_key = os.getenv("OPENAI_API_KEY", "sk-local-proxy")
    return openai.OpenAI(base_url=base_url, api_key=api_key)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def strip_markdown_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def parse_ai_json(raw: str) -> dict:
    if not raw:
        return {}
    cleaned = strip_markdown_fences(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        print(f"  [WARN] JSON parse error: {exc}")
        print(f"  [WARN] Raw (first 200): {raw[:200]}")
        return {}


def call_ai(client: openai.OpenAI, prompt: str) -> str:
    """Call AI with retry."""
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=AI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"  [RETRY {attempt+1}/3] {e}")
            time.sleep(3)
    return ""


# ---------------------------------------------------------------------------
# Excel reading (xlsb)
# ---------------------------------------------------------------------------
def read_mga_sheet() -> list[dict]:
    print(f"Opening: {XLSB_PATH}")
    wb = open_workbook(str(XLSB_PATH))

    with wb.get_sheet(MGA_SHEET_NAME) as sheet:
        all_rows = list(sheet.rows())

    print(f"Total rows: {len(all_rows)} (including header)")

    rows = []
    for row in all_rows[1:]:  # skip header
        vals = [str(c.v).strip() if c.v is not None else "" for c in row[:4]]
        tipo, mga, nv, comment = vals

        if not tipo and not mga and not comment:
            continue

        rows.append({
            "TIPO_DE_NEGOCIO": tipo,
            "MGA": mga,
            "NEW_VENTURE_COLUMN": nv,
            "COMENTARIOS": comment,
        })

    print(f"Data rows: {len(rows)}")
    return rows


# ---------------------------------------------------------------------------
# Decompose + Validate
# ---------------------------------------------------------------------------
def decompose_and_validate(client: openai.OpenAI, comment: str) -> dict:
    """
    Step 1: Decompose comment into structured fields.
    Step 2: Validate that ALL info is captured, auto-correct if not.
    """
    if not comment.strip() or comment.strip() == "-":
        return {field: None for field in AI_FIELDS}

    # Step 1: Decompose
    prompt1 = DECOMPOSE_PROMPT.format(comment_text=comment)
    raw1 = call_ai(client, prompt1)
    fields = parse_ai_json(raw1)

    if not fields:
        print("  [WARN] Decompose returned empty, skipping validation")
        return {field: None for field in AI_FIELDS}

    # Step 2: Validate & auto-correct
    current_json = json.dumps(fields, ensure_ascii=False, indent=2)
    prompt2 = VALIDATION_PROMPT.format(
        comment_text=comment,
        current_json=current_json
    )
    raw2 = call_ai(client, prompt2)
    corrected = parse_ai_json(raw2)

    if corrected:
        return corrected

    # If validation parse failed, use original decomposition
    return fields


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    print("=" * 60)
    print("  COMENTARIOS -> REGLAS Migration (v2)")
    print("  With auto-validation and correction")
    print("=" * 60)

    rows = read_mga_sheet()

    # Collect unique comments
    unique_comments = []
    seen = set()
    for row in rows:
        c = row["COMENTARIOS"]
        if c and c not in seen:
            unique_comments.append(c)
            seen.add(c)

    non_empty = [c for c in unique_comments if c.strip() and c.strip() != "-"]
    print(f"\nUnique comments to process with AI: {len(non_empty)}")
    print(f"Skipped (empty or '-'): {len(unique_comments) - len(non_empty)}")

    client = build_openai_client()

    # Process each unique comment (2 AI calls each: decompose + validate)
    comment_to_fields = {}
    for idx, comment in enumerate(unique_comments, 1):
        short = comment[:80].replace("\n", " ")

        if not comment.strip() or comment.strip() == "-":
            comment_to_fields[comment] = {f: None for f in AI_FIELDS}
            print(f"\n[{idx}/{len(unique_comments)}] Skipped: '{short}'")
            continue

        print(f"\n[{idx}/{len(unique_comments)}] Processing: '{short}'")
        fields = decompose_and_validate(client, comment)
        comment_to_fields[comment] = fields

        if idx < len(unique_comments):
            time.sleep(AI_DELAY_SECONDS)

    # Build output rows
    output_rows = []
    for row in rows:
        record = {
            "MGA": row["MGA"],
            "TIPO_DE_NEGOCIO": row["TIPO_DE_NEGOCIO"],
            "NEW_VENTURE_COLUMN": row["NEW_VENTURE_COLUMN"],
            "COMENTARIO_ORIGINAL": row["COMENTARIOS"],
        }

        ai_fields = comment_to_fields.get(row["COMENTARIOS"], {})
        for field in AI_FIELDS:
            val = ai_fields.get(field)
            record[field] = "" if val is None else str(val)

        output_rows.append(record)

    # Write CSV
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=RULE_COLUMNS)
        writer.writeheader()
        writer.writerows(output_rows)

    # Summary
    print("\n" + "=" * 60)
    print(f"  Migration complete.")
    print(f"  Total rows        : {len(rows)}")
    print(f"  AI calls (x2 each): {len(non_empty)} comments x 2 = {len(non_empty)*2}")
    print(f"  Output CSV        : {OUTPUT_CSV}")
    print("=" * 60)


if __name__ == "__main__":
    main()
