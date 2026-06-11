"""
Bisect the Step 1 radio failure: replicate the CLIENT's exact context
(persistent session + custom UA + popup tab via expect_page) and run an
instrumented click sequence on the customer's-business 'Yes' radio.

Background: the same locator click commits instantly in the MCP browser
(default UA, direct navigation) but never commits inside the real flow
(3 runs, 2026-06-11). This script holds every client variable constant and
logs what actually happens on click:

  * capture-phase window click logger (composedPath target)
  * page console errors
  * full checked-state read after each strategy

Strategies, in order, stopping at the first that commits:
  0. USER HYPOTHESIS (live observation, 2026-06-11): the right-hand
     Dashboard drawer auto-opens when the FMCSA lookup populates it and
     interferes with the selection (click-outside-to-close consuming the
     click / invisible scrim). Detect the drawer, dump its DOM, CLOSE it
     via its collapse chevron, then plain locator click.
  A. exact flow locator click  (gds-radio-button[value=Yes])
  B. JS shadow label click     (flow strategy 6)
  C. MouseEvent sequence on the shadow input
  D. trusted page.mouse.click at the card's center coordinates

Output: console + logs/diag_bisect_step1.png. Quote abandoned (no Next).
"""

import asyncio
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
from modules.geico.pages.base_page import _flex_text_regex
from modules.geico.pages.dashboard_page import DashboardPage
from modules.geico.pages.login_page import LoginPage
from modules.gmail_api_otp_reader import GmailAPIOTPReader

USDOT = "2033673"
ZIP = "77705"
Q = "Is this the customer's business"

JS_INSTALL_LOGGER = """
() => {
    window.__clicks = [];
    const desc = (el) => el ? (el.tagName + (el.id ? '#' + el.id : '')
        + (el.className && el.className.toString
           ? '.' + el.className.toString().split(' ').slice(0, 2).join('.')
           : '')) : 'null';
    window.addEventListener('click', (e) => {
        const path = e.composedPath ? e.composedPath() : [];
        window.__clicks.push({
            target: desc(e.target),
            composed0: desc(path[0]),
            composed1: desc(path[1]),
            trusted: e.isTrusted,
            x: e.clientX, y: e.clientY,
        });
    }, true);
    return 'logger installed';
}
"""

JS_READ_STATE = """
() => {
    const re = /Is\\s+this\\s+the\\s+customer['’]s\\s+business/i;
    const g = Array.from(document.querySelectorAll('gds-radio-button-group'))
        .find(x => re.test(x.textContent || ''));
    if (!g) return 'group-not-found';
    return Array.from(g.querySelectorAll('gds-radio-button')).map(b => ({
        value: b.getAttribute('value'),
        checked_attr: b.hasAttribute('checked'),
        shadow: (() => {
            const i = b.shadowRoot
                && b.shadowRoot.querySelector('input[type=radio]');
            return i ? i.checked : null;
        })(),
    }));
}
"""

JS_SHADOW_LABEL_CLICK = """
() => {
    const re = /Is\\s+this\\s+the\\s+customer['’]s\\s+business/i;
    const g = Array.from(document.querySelectorAll('gds-radio-button-group'))
        .find(x => re.test(x.textContent || ''));
    if (!g) return 'no-group';
    const b = Array.from(g.querySelectorAll('gds-radio-button'))
        .find(x => (x.getAttribute('value') || '') === 'Yes');
    if (!b) return 'no-button';
    const sh = b.shadowRoot;
    const label = sh && sh.querySelector('label');
    const input = sh && sh.querySelector('input[type=radio]');
    (label || input || b).click();
    return 'clicked ' + (label ? 'label' : input ? 'input' : 'host');
}
"""

JS_MOUSE_EVENTS_ON_INPUT = """
() => {
    const re = /Is\\s+this\\s+the\\s+customer['’]s\\s+business/i;
    const g = Array.from(document.querySelectorAll('gds-radio-button-group'))
        .find(x => re.test(x.textContent || ''));
    const b = g && Array.from(g.querySelectorAll('gds-radio-button'))
        .find(x => (x.getAttribute('value') || '') === 'Yes');
    const input = b && b.shadowRoot
        && b.shadowRoot.querySelector('input[type=radio]');
    if (!input) return 'no-input';
    for (const t of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
        input.dispatchEvent(new MouseEvent(t, {bubbles: true, composed: true}));
    }
    return 'dispatched';
}
"""


JS_DUMP_DRAWER = """
() => {
    // The drawer: a right-side container holding the quote 'Dashboard'
    // summary (Contact Number / Rated State / Zip Code).
    const all = Array.from(document.querySelectorAll('aside, [class*="drawer" i], [class*="sidebar" i], [class*="panel" i], [class*="sidenav" i], gds-drawer, gds-side-panel'));
    const byText = Array.from(document.querySelectorAll('div, aside, section'))
        .filter(el => {
            const t = el.textContent || '';
            return t.includes('Rated State') && t.includes('Dashboard')
                && el.querySelectorAll('*').length < 400;
        });
    const candidates = [...new Set([...all, ...byText])];
    return candidates.slice(0, 6).map(el => {
        const r = el.getBoundingClientRect();
        return {
            tag: el.tagName,
            cls: (el.className || '').toString().slice(0, 80),
            rect: {x: r.x, y: r.y, w: r.width, h: r.height},
            visible: el.offsetParent !== null,
            // controls that могли collapse it
            buttons: Array.from(el.querySelectorAll('button, gds-button, [role=button], [class*="toggle" i], [class*="collapse" i], [class*="chevron" i], [class*="expander" i]'))
                .slice(0, 8).map(b => ({
                    tag: b.tagName,
                    cls: (b.className || '').toString().slice(0, 60),
                    aria: b.getAttribute('aria-label'),
                    text: (b.textContent || '').trim().slice(0, 20),
                    rect: (() => { const q = b.getBoundingClientRect();
                                   return {x: q.x, y: q.y, w: q.width, h: q.height}; })(),
                })),
        };
    });
}
"""

# Anything stacked OVER the Yes card's center (the scrim/drawer hypothesis):
JS_HIT_TEST_YES = """
() => {
    const re = /Is\\s+this\\s+the\\s+customer['’]s\\s+business/i;
    const g = Array.from(document.querySelectorAll('gds-radio-button-group'))
        .find(x => re.test(x.textContent || ''));
    const b = g && Array.from(g.querySelectorAll('gds-radio-button'))
        .find(x => (x.getAttribute('value') || '') === 'Yes');
    if (!b) return 'no-button';
    const r = b.getBoundingClientRect();
    const cx = r.x + r.width / 2, cy = r.y + r.height / 2;
    const stack = document.elementsFromPoint(cx, cy).slice(0, 6).map(el =>
        el.tagName + ((el.className || '').toString()
            ? '.' + (el.className || '').toString().split(' ')[0] : ''));
    return {center: {x: cx, y: cy}, stack};
}
"""


def committed(state) -> bool:
    return isinstance(state, list) and any(
        s.get("value") == "Yes" and (s.get("checked_attr") or s.get("shadow"))
        for s in state
    )


async def main() -> int:
    config = GEICOConfig.from_env()
    console_errors = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=config.headless)
        storage = str(_SESSION_STATE) if _SESSION_STATE.exists() else None
        # EXACT client replica, including the truncated UA.
        ctx = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36"
            ),
            storage_state=storage,
        )
        ctx.set_default_timeout(30_000)
        page = await ctx.new_page()

        reader = GmailAPIOTPReader(config.otp_email, subject="GEICO")
        ok = await LoginPage(page, reader, config.login_url).login(
            config.username, config.password
        )
        if not ok:
            print("[bisect] login failed")
            await browser.close()
            return 1
        try:
            await ctx.storage_state(path=str(_SESSION_STATE))
        except Exception:
            pass

        print("[bisect] dashboard -> wizard popup (expect_page, like client)")
        wizard = await DashboardPage(page).start_new_quote(
            usdot=USDOT, zip_code=ZIP, context=ctx
        )
        wizard.on(
            "console",
            lambda m: console_errors.append(m.text) if m.type == "error" else None,
        )

        # Replica of the flow preamble.
        await wizard.wait_for_load_state("networkidle", timeout=30_000)
        print(f"[bisect] installing click logger...")
        print(await wizard.evaluate(JS_INSTALL_LOGGER))

        q_re = _flex_text_regex(Q)
        gds_group = wizard.locator("gds-radio-button-group").filter(has_text=q_re)
        await gds_group.first.wait_for(state="visible", timeout=15_000)

        async def report(tag):
            state = await wizard.evaluate(JS_READ_STATE)
            clicks = await wizard.evaluate("() => window.__clicks || 'logger-gone'")
            print(f"[bisect] {tag}: state={state}")
            print(f"[bisect] {tag}: clicks={clicks}")
            return state

        await report("pre")

        # --- Strategy 0: USER HYPOTHESIS — the Dashboard drawer ---
        print("\n[bisect] 0: Dashboard drawer state + hit-test over the Yes card")
        drawer_dump = await wizard.evaluate(JS_DUMP_DRAWER)
        for d in drawer_dump:
            print(f"  drawer candidate: {d['tag']} cls={d['cls']!r} "
                  f"rect={d['rect']} visible={d['visible']}")
            for b in d["buttons"]:
                print(f"    control: {b['tag']} cls={b['cls']!r} "
                      f"aria={b['aria']!r} text={b['text']!r} rect={b['rect']}")
        print(f"  hit-test: {await wizard.evaluate(JS_HIT_TEST_YES)}")

        # Close the drawer: click its chevron/collapse control (left edge of
        # the drawer). Try aria/cls based candidates from the dump.
        closed = await wizard.evaluate(
            """() => {
                const cands = Array.from(document.querySelectorAll(
                    'button, [role=button], [class*="toggle" i], '
                    + '[class*="collapse" i], [class*="chevron" i], '
                    + '[class*="expander" i]'
                )).filter(el => {
                    const r = el.getBoundingClientRect();
                    // controls living at the drawer's left edge (x > 60% vw)
                    return el.offsetParent !== null
                        && r.x > window.innerWidth * 0.6 && r.width < 80;
                });
                if (!cands.length) return 'no-collapse-control';
                cands[0].click();
                return 'clicked ' + cands[0].tagName + '.'
                    + (cands[0].className || '').toString().split(' ')[0];
            }"""
        )
        print(f"  drawer close attempt: {closed}")
        await wizard.wait_for_timeout(1_000)
        print(f"  hit-test after close: {await wizard.evaluate(JS_HIT_TEST_YES)}")

        # --- Strategy A: exact flow locator click (drawer now closed) ---
        print("\n[bisect] A: locator gds-radio-button[value=Yes] click")
        target = gds_group.locator('gds-radio-button[value="Yes"]').first
        await target.scroll_into_view_if_needed(timeout=3_000)
        await target.click(timeout=8_000)
        await wizard.wait_for_timeout(1_200)
        if committed(await report("A")):
            print("[bisect] *** A COMMITS (tras cerrar drawer) ***")
        else:
            # --- Strategy B: JS shadow label click ---
            print("\n[bisect] B: JS shadow label click")
            print(await wizard.evaluate(JS_SHADOW_LABEL_CLICK))
            await wizard.wait_for_timeout(1_200)
            if committed(await report("B")):
                print("[bisect] *** B COMMITS ***")
            else:
                # --- Strategy C: MouseEvent sequence on shadow input ---
                print("\n[bisect] C: MouseEvent sequence on shadow input")
                print(await wizard.evaluate(JS_MOUSE_EVENTS_ON_INPUT))
                await wizard.wait_for_timeout(1_200)
                if committed(await report("C")):
                    print("[bisect] *** C COMMITS ***")
                else:
                    # --- Strategy D: trusted mouse click at card coords ---
                    print("\n[bisect] D: page.mouse.click at card center")
                    box = await target.bounding_box()
                    print(f"  bounding_box={box}")
                    if box:
                        await wizard.mouse.click(
                            box["x"] + box["width"] / 2,
                            box["y"] + box["height"] / 2,
                        )
                        await wizard.wait_for_timeout(1_200)
                        if committed(await report("D")):
                            print("[bisect] *** D COMMITS ***")
                        else:
                            print("[bisect] NOTHING commits — see logs")

        if console_errors:
            print(f"\n[bisect] wizard console errors ({len(console_errors)}):")
            for e in console_errors[:10]:
                print(f"  - {e[:160]}")

        await wizard.screenshot(
            path=str(ROOT / "logs" / "diag_bisect_step1.png"), full_page=True
        )
        print("[bisect] screenshot logs/diag_bisect_step1.png — abandoning quote")
        await browser.close()
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
