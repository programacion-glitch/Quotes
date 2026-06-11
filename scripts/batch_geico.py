"""
Batch-run every Blue Quote PDF in a folder through the live GEICO flow.

Each PDF runs in its OWN subprocess (full isolation: a browser crash, hang,
or HALT in one quote never kills the sweep). Per-quote timeout guards against
a page that stays loading forever; on timeout, orphaned Chromium processes
are killed (they wedge later quotes — Progressive lesson 2026-06-10).
Results are written incrementally to JSON + Markdown so partial progress
survives an interruption.

The persistent GEICO session (data/geico_session.json) means the FIRST quote
may do a login/OTP and the rest reuse it — do NOT run anything else against
the GEICO portal while a batch is running (single session per agent).

Usage:
    python scripts/batch_geico.py [folder] [effective_date]

Defaults:
    folder         = "data/input 10 Junio"
    effective_date = (none -> GEICO default, tomorrow)
"""

import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_geico_from_pdf.py"

DEFAULT_FOLDER = ROOT / "data" / "input 10 Junio"
PER_QUOTE_TIMEOUT = 900  # 15 min hard cap per quote (then marked TIMEOUT)

OUT_DIR = ROOT / "logs" / "geico_batch"
LOG_DIR = OUT_DIR / "runs"
REPORT_JSON = OUT_DIR / "report.json"
REPORT_MD = OUT_DIR / "report.md"


def _parse_result(stdout: str) -> dict:
    """Pull the key fields out of the runner's RESULT block."""
    def grab(label):
        m = re.search(rf"^\s*{re.escape(label)}\s*:\s*(.*)$", stdout, re.MULTILINE)
        return m.group(1).strip() if m else None

    warnings = re.findall(r"^\s{4}- (.+)$", stdout, re.MULTILINE)
    return {
        "success": grab("success"),
        "step_reached": grab("step_reached"),
        "error": grab("error"),
        "halted": grab("halted"),
        "screenshot_path": grab("screenshot_path"),
        "pdf_path": grab("pdf_path"),
        "annual_premium": grab("annual_premium"),
        "quote_number": grab("quote_number"),
        "warnings": warnings,
    }


def main() -> int:
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_FOLDER
    effective = sys.argv[2] if len(sys.argv) > 2 else None

    pdfs = sorted(folder.glob("*.pdf"))
    if not pdfs:
        print(f"[batch] no PDFs in {folder}")
        return 1

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[batch] {len(pdfs)} PDFs in {folder.name}  "
          f"effective={effective or 'GEICO default'}")
    print(f"[batch] logs -> {LOG_DIR}")

    results = []
    for i, pdf in enumerate(pdfs, 1):
        stem = pdf.stem
        log_path = LOG_DIR / f"{stem}.log"
        print(f"\n[batch] ({i}/{len(pdfs)}) {pdf.name}")
        t0 = time.time()
        status = "OK"
        cmd = [sys.executable, "-u", str(RUNNER), str(pdf)]
        if effective:
            cmd.append(effective)
        try:
            proc = subprocess.run(
                cmd,
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
            # Killing the python child ORPHANS its Chromium — the zombie
            # holds the single GEICO agent session and wedges later quotes.
            subprocess.run(
                ["taskkill", "/F", "/IM", "headless_shell.exe", "/T"],
                capture_output=True,
            )
            subprocess.run(
                ["taskkill", "/F", "/IM", "chrome.exe", "/T"],
                capture_output=True,
            )

        elapsed = round(time.time() - t0, 1)
        log_path.write_text(
            f"=== STDOUT ===\n{stdout}\n\n=== STDERR ===\n{stderr}",
            encoding="utf-8",
        )

        parsed = _parse_result(stdout)
        if status != "TIMEOUT":
            if parsed.get("success") == "True":
                status = "QUOTED"
            elif parsed.get("halted") == "True":
                status = "HALT"
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
    lines = ["# GEICO batch", ""]
    quoted = [r for r in results if r["status"] == "QUOTED"]
    halted = [r for r in results if r["status"] == "HALT"]
    other = [r for r in results if r["status"] in ("FAILED", "TIMEOUT")]
    lines.append(
        f"Processed {len(results)}/{total} — **{len(quoted)} quoted**, "
        f"{len(halted)} halted (not eligible / manual), {len(other)} failed"
    )
    lines.append("")
    lines.append("| # | File | Status | Premium | Quote# | PDF | Step | Warn | Time |")
    lines.append("|---|------|--------|---------|--------|-----|------|------|------|")
    for i, r in enumerate(results, 1):
        pdf_ok = "✓" if (r.get("pdf_path") or "None") != "None" else "—"
        lines.append(
            f"| {i} | {r['file']} | {r['status']} | "
            f"{r.get('annual_premium') or '—'} | {r.get('quote_number') or '—'} | "
            f"{pdf_ok} | {r.get('step_reached') or '—'} | "
            f"{len(r.get('warnings') or [])} | {r['elapsed_s']}s |"
        )
    lines.append("")
    lines.append("## Detail (non-quoted + warnings)")
    for r in results:
        if r["status"] == "QUOTED" and not r.get("warnings"):
            continue
        lines.append(f"\n### {r['file']} — {r['status']}")
        if r["status"] != "QUOTED":
            lines.append(f"- step_reached: {r.get('step_reached')}")
            lines.append(f"- error: {r.get('error')}")
            lines.append(f"- screenshot: {r.get('screenshot_path')}")
            lines.append(f"- log: {r['log']}")
        for w in r.get("warnings") or []:
            lines.append(f"- WARN: {w}")
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
