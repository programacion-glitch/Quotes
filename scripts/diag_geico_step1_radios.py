"""
Surgical diagnostic for the Step 1 'Is this the customer's business?' radio.

The 2026-06-11 HUMBERTO run failed with RadioStuckError: clicks landed
without exception but the radio never read as checked (screenshot confirms
both cards unchecked). This script reuses the saved session, drives to
Step 1, and in ONE session:

  1. Dumps the real DOM of every gds-radio-button-group (light DOM +
     each gds-radio-button's attributes + shadowRoot innerHTML).
  2. Tries click strategies in order on the customer's-business 'Yes'
     radio, reading the full checked-state (aria-checked, attrs, shadow
     input.checked) after each, and reports WHICH one commits.

Output: logs/diag_step1_radios.json + console summary. No Next click —
the quote is abandoned afterwards.
"""

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for s in (sys.stdout, sys.stderr):
    try:
        s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception as e:
    print("WARN dotenv", e)

from playwright.async_api import async_playwright

from modules.geico.client import GEICOConfig, _SESSION_STATE
from modules.geico.pages.dashboard_page import DashboardPage
from modules.geico.pages.login_page import LoginPage
from modules.gmail_api_otp_reader import GmailAPIOTPReader

USDOT = "2033673"
ZIP = "77705"

JS_DUMP_GROUPS = """
() => {
    const vis = el => el.offsetParent !== null;
    return Array.from(document.querySelectorAll('gds-radio-button-group'))
        .filter(vis)
        .map(g => ({
            question: (g.innerText || '').trim().split('\\n')[0].slice(0, 90),
            attrs: Object.fromEntries(
                Array.from(g.attributes).map(a => [a.name, a.value])
            ),
            buttons: Array.from(g.querySelectorAll('gds-radio-button')).map(b => ({
                attrs: Object.fromEntries(
                    Array.from(b.attributes).map(a => [a.name, a.value])
                ),
                text: (b.innerText || '').trim().slice(0, 40),
                ariaChecked: b.getAttribute('aria-checked'),
                shadowHTML: b.shadowRoot
                    ? b.shadowRoot.innerHTML.slice(0, 600)
                    : null,
                shadowInputChecked: (() => {
                    const i = b.shadowRoot
                        && b.shadowRoot.querySelector('input[type=radio]');
                    return i ? i.checked : null;
                })(),
            })),
        }));
}
"""

JS_READ_STATE = """
(args) => {
    const groups = Array.from(
        document.querySelectorAll('gds-radio-button-group')
    ).filter(g => (g.innerText || '').toLowerCase()
        .includes(args.q.toLowerCase()));
    if (!groups.length) return {error: 'group-not-found'};
    const g = groups[0];
    return Array.from(g.querySelectorAll('gds-radio-button')).map(b => {
        const i = b.shadowRoot
            && b.shadowRoot.querySelector('input[type=radio]');
        return {
            text: (b.innerText || '').trim().slice(0, 20),
            value: b.getAttribute('value'),
            checked_attr: b.hasAttribute('checked'),
            aria: b.getAttribute('aria-checked'),
            shadow_checked: i ? i.checked : null,
        };
    });
}
"""

Q = "customer's business"


async def read_state(page):
    return await page.evaluate(JS_READ_STATE, {"q": "customer’s business"})


async def main() -> int:
    config = GEICOConfig.from_env()
    if not _SESSION_STATE.exists():
        print("[diag] no saved session — run probe_geico_login.py first")
        return 1

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=config.headless)
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            storage_state=str(_SESSION_STATE),
        )
        ctx.set_default_timeout(30_000)
        page = await ctx.new_page()

        # Same path as the real flow: reuse the session if alive, full
        # credentials+OTP re-login if it idled out (GEICO TTL ~minutes).
        reader = GmailAPIOTPReader(config.otp_email, subject="GEICO")
        ok = await LoginPage(page, reader, config.login_url).login(
            config.username, config.password
        )
        if not ok:
            print("[diag] login failed — see logs/geico_login_*.png")
            await browser.close()
            return 1
        try:
            await ctx.storage_state(path=str(_SESSION_STATE))
        except Exception as e:
            print(f"[diag] WARN: could not save session state: {e}")

        print("[diag] driving dashboard eligibility -> wizard...")
        wizard = await DashboardPage(page).start_new_quote(
            usdot=USDOT, zip_code=ZIP, context=ctx
        )
        await wizard.wait_for_load_state("networkidle", timeout=30_000)
        await wizard.wait_for_timeout(2_000)

        # ---- 1. Full dump of every visible radio group ----
        dump = await wizard.evaluate(JS_DUMP_GROUPS)
        out = ROOT / "logs" / "diag_step1_radios.json"
        out.write_text(json.dumps(dump, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        print(f"[diag] {len(dump)} visible groups dumped -> {out}")
        for g in dump:
            print(f"  Q: {g['question']!r}")
            for b in g["buttons"]:
                print(f"     btn text={b['text']!r} attrs={b['attrs']} "
                      f"aria={b['ariaChecked']} shadow={b['shadowInputChecked']}")

        # ---- 2. Click strategies on the customer's-business Yes ----
        target_group = wizard.locator("gds-radio-button-group").filter(
            has_text="s business?"
        )
        n = await target_group.count()
        print(f"[diag] locator matched {n} group(s) for 'customer's business'")
        if n == 0:
            await browser.close()
            return 1
        grp = target_group.first

        strategies = [
            ("value=Yes", grp.locator('gds-radio-button[value="Yes"]')),
            ("text Yes (gds-radio-button)", grp.locator(
                "gds-radio-button").filter(has_text="Yes")),
            ("role=radio name Yes", grp.get_by_role(
                "radio", name="Yes", exact=True)),
            ("label.click via JS shadow", None),  # special-cased below
        ]
        for name, loc in strategies:
            print(f"\n[diag] strategy: {name}")
            try:
                if loc is None:
                    clicked = await wizard.evaluate(
                        """() => {
                            const gs = Array.from(document.querySelectorAll(
                                'gds-radio-button-group'
                            )).filter(g => (g.innerText||'')
                                .includes('business?'));
                            if (!gs.length) return 'no-group';
                            const b = Array.from(
                                gs[0].querySelectorAll('gds-radio-button')
                            ).find(x => (x.innerText||'').trim() === 'Yes');
                            if (!b) return 'no-button';
                            const sh = b.shadowRoot;
                            const input = sh && sh.querySelector(
                                'input[type=radio]');
                            const label = sh && sh.querySelector('label');
                            (label || input || b).click();
                            return 'clicked ' + (label ? 'label'
                                : input ? 'input' : 'host');
                        }"""
                    )
                    print(f"  -> {clicked}")
                else:
                    cnt = await loc.count()
                    print(f"  locator count={cnt}")
                    if cnt == 0:
                        continue
                    await loc.first.scroll_into_view_if_needed(timeout=3_000)
                    await loc.first.click(timeout=8_000)
                await wizard.wait_for_timeout(800)
            except Exception as e:
                print(f"  click failed: {e}")
                continue
            state = await read_state(wizard)
            print(f"  state after click: {state}")
            if isinstance(state, list) and any(
                (s.get("shadow_checked") or s.get("aria") == "true"
                 or s.get("checked_attr"))
                and (s.get("text") == "Yes" or s.get("value") == "Yes")
                for s in state
            ):
                print(f"[diag] *** WINNER: {name} ***")
                break

        await wizard.screenshot(
            path=str(ROOT / "logs" / "diag_step1_after_clicks.png"),
            full_page=True,
        )
        print("[diag] screenshot logs/diag_step1_after_clicks.png — quote "
              "abandoned (no Next clicked)")
        await browser.close()
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
