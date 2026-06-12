"""One-off: download SOLANO's PrintQuote PDF with the live MCP session cookies."""
import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
COOKIES_PATH = Path(sys.argv[1])
URL = ("https://sales.geico.com/PrintQuote?doctype=CommercialQuotePdfIAAgent"
       "&retentionKey=F118E7895C27C52155D025A35EE0134D7FE39DEC0AD44BCE50B8D6"
       "E0ADA445C5AF8DE76E80AF029A109239687556A88C&auth=t"
       "&conversationId=1f10901f-db00-4195-8e76-f73e51df728d&termLength=12")
OUT = ROOT / "data" / "output" / "geico_quote_OSCAR_SOLANO_17596.pdf"

cookies = {c["name"]: c["value"] for c in json.loads(COOKIES_PATH.read_text(encoding="utf-8"))}
resp = requests.get(URL, cookies=cookies, timeout=60, headers={
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
    "Referer": "https://sales.geico.com/quote",
})
print("status:", resp.status_code, "type:", resp.headers.get("content-type"),
      "size:", len(resp.content))
if resp.ok and resp.content.startswith(b"%PDF"):
    OUT.write_bytes(resp.content)
    print("saved:", OUT)
else:
    print("NOT a PDF; first bytes:", resp.content[:80])
