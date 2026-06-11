"""
Batch-run every Blue Quote PDF in a folder through the live Progressive flow.

Each PDF is processed in its OWN subprocess (full isolation: a browser crash,
hang, or HALT in one quote never kills the sweep). Per-quote timeout guards
against a page that stays "loading" forever. Results are written incrementally
to a JSON + Markdown report so partial progress survives an interruption.

Usage:
    python scripts/batch_progressive_june10.py [folder] [effective_date]

Defaults:
    folder         = "data/input 10 Junio"
    effective_date = 06/15/2026   (a valid future date for all quotes)
"""

import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_progressive_from_pdf.py"

DEFAULT_FOLDER = ROOT / "data" / "input 10 Junio"
DEFAULT_EFFECTIVE = "06/15/2026"
PER_QUOTE_TIMEOUT = 900  # 15 min hard cap per quote (then marked TIMEOUT)

OUT_DIR = ROOT / "logs" / "june10"
LOG_DIR = OUT_DIR / "runs"
REPORT_JSON = OUT_DIR / "report.json"
REPORT_MD = OUT_DIR / "report.md"


def _parse_result(stdout: str) -> dict:
    """Pull the key fields out of the runner's RESULT block."""
    def grab(label):
        m = re.search(rf"^\s*{re.escape(label)}\s*:\s*(.*)$", stdout, re.MULTILINE)
        return m.group(1).strip() if m else None

    return {
        "success": grab("success"),
        "step_reached": grab("step_reached"),
        "error": grab("error"),
        "screenshot_path": grab("screenshot_path"),
        "annual_premium": grab("annual_premium"),
        "quote_number": grab("quote_number"),
    }


def main() -> int:
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_FOLDER
    effective = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_EFFECTIVE

    pdfs = sorted(folder.glob("*.pdf"))
    if not pdfs:
        print(f"[batch] no PDFs in {folder}")
        return 1

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[batch] {len(pdfs)} PDFs in {folder.name}  effective={effective}")
    print(f"[batch] logs -> {LOG_DIR}")

    results = []
    for i, pdf in enumerate(pdfs, 1):
        stem = pdf.stem
        log_path = LOG_DIR / f"{stem}.log"
        print(f"\n[batch] ({i}/{len(pdfs)}) {pdf.name}")
        t0 = time.time()
        status = "OK"
        try:
            proc = subprocess.run(
                [sys.executable, str(RUNNER), str(pdf), effective],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=PER_QUOTE_TIMEOUT,
            )
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            returncode = proc.returncode
        except subprocess.TimeoutExpired as e:
            stdout = (e.stdout or "") if isinstance(e.stdout, str) else ""
            stderr = (e.stderr or "") if isinstance(e.stderr, str) else ""
            returncode = -1
            status = "TIMEOUT"

        elapsed = round(time.time() - t0, 1)
        log_path.write_text(
            f"=== STDOUT ===\n{stdout}\n\n=== STDERR ===\n{stderr}",
            encoding="utf-8",
        )

        parsed = _parse_result(stdout)
        if status != "TIMEOUT":
            if parsed.get("success") == "True":
                status = "QUOTED"
            elif returncode == 0:
                status = "OK"
            else:
                status = "FAILED"

        rec = {
            "file": pdf.name,
            "status": status,
            "returncode": returncode,
            "elapsed_s": elapsed,
            "log": str(log_path),
            **parsed,
        }
        results.append(rec)
        print(f"[batch]   -> {status}  ({elapsed}s)  "
              f"premium={parsed.get('annual_premium')}  "
              f"quote={parsed.get('quote_number')}  "
              f"step={parsed.get('step_reached')}")

        # Incremental write so partial progress survives an interruption.
        REPORT_JSON.write_text(json.dumps(results, indent=2), encoding="utf-8")
        _write_md(results, len(pdfs))

    print(f"\n[batch] DONE. Report: {REPORT_MD}")
    return 0


def _write_md(results, total):
    lines = ["# Progressive batch — June 10 folder", ""]
    quoted = [r for r in results if r["status"] == "QUOTED"]
    failed = [r for r in results if r["status"] in ("FAILED", "TIMEOUT", "OK")]
    lines.append(f"Processed {len(results)}/{total} — "
                 f"**{len(quoted)} quoted**, {len(failed)} not quoted")
    lines.append("")
    lines.append("| # | File | Status | Premium | Quote# | Step | Time |")
    lines.append("|---|------|--------|---------|--------|------|------|")
    for i, r in enumerate(results, 1):
        lines.append(
            f"| {i} | {r['file']} | {r['status']} | "
            f"{r.get('annual_premium') or '—'} | {r.get('quote_number') or '—'} | "
            f"{r.get('step_reached') or '—'} | {r['elapsed_s']}s |"
        )
    lines.append("")
    lines.append("## Not-quoted detail")
    for r in results:
        if r["status"] == "QUOTED":
            continue
        lines.append(f"\n### {r['file']} — {r['status']}")
        lines.append(f"- step_reached: {r.get('step_reached')}")
        lines.append(f"- error: {r.get('error')}")
        lines.append(f"- screenshot: {r.get('screenshot_path')}")
        lines.append(f"- log: {r['log']}")
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
