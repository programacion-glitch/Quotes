"""
Re-run ONLY the eligible Blue Quotes that reached the GEICO wizard but did
not produce a quote — i.e. the ones the dashboard accepted (USDOT/ZIP
eligible) but that died inside the wizard (step_reached in the wizard
stages). HALT-at-dashboard (not eligible) and field_mapping failures are
skipped — re-running them changes nothing.

Reads the latest batch report (logs/geico_batch/report.json), reconstructs
each PDF path from the source folder, and re-runs each through the live
runner. Use this after a code fix (e.g. the comp/coll 'Total stated value'
field) so we conserve quote attempts: only the wizard-eligible profiles are
re-attempted, not the whole 28.

Usage:
    python scripts/rerun_eligible.py <source-folder> [limit]

    limit = N  -> re-run only the first N eligibles (live validation of a fix
                  before committing the rest; default: all eligibles).
"""

import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_geico_from_pdf.py"
REPORT_JSON = ROOT / "logs" / "geico_batch" / "report.json"
OUT_DIR = ROOT / "logs" / "geico_rerun"
LOG_DIR = OUT_DIR / "runs"
PER_QUOTE_TIMEOUT = 900

# Wizard stages: reaching one means the dashboard found the USDOT/ZIP
# eligible — worth re-running after a wizard-level fix.
WIZARD_STEPS = {
    "business_info", "business_class", "more_business",
    "vehicles", "drivers", "coverages", "final_details",
}


def _eligible_files(folder: Path) -> list[Path]:
    if not REPORT_JSON.exists():
        print(f"[rerun] no report at {REPORT_JSON}")
        return []
    report = json.loads(REPORT_JSON.read_text(encoding="utf-8"))
    out = []
    for r in report:
        if r.get("success") == "True":
            continue  # already quoted — don't re-burn it
        step = (r.get("step_reached") or "").strip()
        if step in WIZARD_STEPS:
            pdf = folder / r["file"]
            if pdf.exists():
                out.append(pdf)
            else:
                print(f"[rerun] WARN missing PDF for {r['file']}")
    return out


def _parse_result(stdout: str) -> dict:
    def grab(label):
        m = re.search(rf"^\s*{re.escape(label)}\s*:\s*(.*)$", stdout, re.MULTILINE)
        return m.group(1).strip() if m else None
    return {
        "success": grab("success"),
        "step_reached": grab("step_reached"),
        "error": grab("error"),
        "halted": grab("halted"),
        "pdf_path": grab("pdf_path"),
        "annual_premium": grab("annual_premium"),
        "quote_number": grab("quote_number"),
    }


def main() -> int:
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        ROOT / "data" / "input 10 Junio"
    )
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else None

    eligibles = _eligible_files(folder)
    if not eligibles:
        print("[rerun] no wizard-eligible profiles to re-run.")
        return 1
    if limit:
        print(f"[rerun] LIMIT {limit}: validating the first {limit} eligible(s)")
        eligibles = eligibles[:limit]

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[rerun] {len(eligibles)} wizard-eligible profile(s) to re-run")

    quoted = 0
    for i, pdf in enumerate(eligibles, 1):
        print(f"\n[rerun] ({i}/{len(eligibles)}) {pdf.name}")
        t0 = time.time()
        cmd = [sys.executable, "-u", str(RUNNER), str(pdf)]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=PER_QUOTE_TIMEOUT,
            )
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
        except subprocess.TimeoutExpired as e:
            stdout = (e.stdout or "") if isinstance(e.stdout, str) else ""
            stderr = (e.stderr or "") if isinstance(e.stderr, str) else ""
            subprocess.run(["taskkill", "/F", "/IM", "headless_shell.exe", "/T"],
                           capture_output=True)
            subprocess.run(["taskkill", "/F", "/IM", "chrome.exe", "/T"],
                           capture_output=True)
        elapsed = round(time.time() - t0, 1)
        (LOG_DIR / f"{pdf.stem}.log").write_text(
            f"=== STDOUT ===\n{stdout}\n\n=== STDERR ===\n{stderr}",
            encoding="utf-8",
        )
        p = _parse_result(stdout)
        status = ("QUOTED" if p.get("success") == "True"
                  else "HALT" if p.get("halted") == "True" else "FAILED")
        if status == "QUOTED":
            quoted += 1
        print(f"[rerun]   -> {status}  ({elapsed}s)  "
              f"premium={p.get('annual_premium')}  quote={p.get('quote_number')}  "
              f"step={p.get('step_reached')}")

    print(f"\n[rerun] DONE. {quoted}/{len(eligibles)} quoted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
