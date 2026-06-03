"""Captura métricas pre-refactor del módulo Progressive.

Cuenta wait_for_timeout sin justificar, _click_continue locales, y tamaños
de cada page. Output va a stdout en formato Markdown listo para pegar
en docs/superpowers/baselines/.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGES_DIR = ROOT / "modules" / "progressive" / "pages"

WAIT_RE = re.compile(r"wait_for_timeout\s*\(\s*(\d+)")
CONTINUE_RE = re.compile(r"def\s+_click_continue\s*\(")


def count_unjustified_waits(text: str) -> int:
    """Cuenta wait_for_timeout(N) cuyas líneas previas NO contienen comentario."""
    lines = text.splitlines()
    count = 0
    for i, line in enumerate(lines):
        if WAIT_RE.search(line):
            prev = lines[i - 1].strip() if i > 0 else ""
            if not prev.startswith("#"):
                count += 1
    return count


def main() -> None:
    print("# Progressive Baseline Metrics — 2026-06-02\n")
    print("| File | Lines | wait_for_timeout (unjustified) | _click_continue locales |")
    print("|---|---|---|---|")

    total_waits, total_continues, total_lines = 0, 0, 0
    for f in sorted(PAGES_DIR.glob("*.py")):
        if f.name.startswith("__") or f.name.startswith("_"):
            continue
        text = f.read_text(encoding="utf-8")
        lines = len(text.splitlines())
        waits = count_unjustified_waits(text)
        continues = len(CONTINUE_RE.findall(text))
        total_lines += lines
        total_waits += waits
        total_continues += continues
        print(f"| `{f.name}` | {lines} | {waits} | {continues} |")

    print(f"| **TOTAL** | **{total_lines}** | **{total_waits}** | **{total_continues}** |")


if __name__ == "__main__":
    main()
