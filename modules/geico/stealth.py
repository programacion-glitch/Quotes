"""Anti-bot hardening for GEICO (Imperva Incapsula WAF).

GEICO fronts sales.geico.com with Imperva Incapsula (cookies incap_ses_*,
visid_incap_*, nlbi_*). Incapsula fingerprints the browser and blocks
automation — the symptom is the 'There was a problem while processing the
information you submitted' page on a step submit, NOT a real validation
error. The MCP-driven browser sailed through the SAME flow because it
presented a real Chrome fingerprint; our context did not.

Two tells we were emitting:
  1. A TRUNCATED User-Agent ending at 'AppleWebKit/537.36' (no 'Chrome/...'
     'Safari/...') — a classic headless/bot signature.
  2. navigator.webdriver === true, plus missing window.chrome and a
     headless-shaped plugins/languages surface.

This module centralizes the countermeasures so the client and every probe
use an identical, realistic fingerprint. Validated against the UA the live
MCP Chrome reported on 2026-06-11.
"""

from __future__ import annotations

# Full, realistic desktop Chrome UA (matches the live MCP browser exactly).
# Bump the Chrome major to track the installed Playwright Chromium.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
)

# Launch flags that drop the most obvious automation tells. The first is the
# important one: it removes the `navigator.webdriver` flag at the engine
# level and the AutomationControlled blink feature Incapsula probes for.
LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
    "--no-sandbox",
    "--disable-dev-shm-usage",
]

# Init script run before any page JS: scrub the residual headless tells that
# the launch flag alone doesn't cover (webdriver getter, empty plugins,
# missing window.chrome, headless languages).
_INIT_SCRIPT = """
(() => {
    // 1. navigator.webdriver -> undefined
    try {
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    } catch (e) {}
    // 2. window.chrome shim (real Chrome always has it)
    if (!window.chrome) {
        window.chrome = {runtime: {}};
    }
    // 3. plugins / mimeTypes look non-empty
    try {
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5],
        });
    } catch (e) {}
    // 4. languages
    try {
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en'],
        });
    } catch (e) {}
    // 5. permissions query (headless returns 'denied' for notifications)
    try {
        const orig = window.navigator.permissions &&
            window.navigator.permissions.query;
        if (orig) {
            window.navigator.permissions.query = (p) =>
                p && p.name === 'notifications'
                    ? Promise.resolve({state: Notification.permission})
                    : orig(p);
        }
    } catch (e) {}
})();
"""

# Headers a real Chrome sends that Playwright omits by default; some WAFs
# flag their absence.
EXTRA_HEADERS = {
    "Accept-Language": "en-US,en;q=0.9",
    "sec-ch-ua": '"Chromium";v="149", "Google Chrome";v="149", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}


def launch_kwargs(*, headless: bool) -> dict:
    """kwargs for chromium.launch() with the anti-automation flags."""
    return {"headless": headless, "args": list(LAUNCH_ARGS)}


def context_kwargs(*, storage_state=None) -> dict:
    """kwargs for browser.new_context() with the realistic fingerprint."""
    kwargs = {
        "viewport": {"width": 1920, "height": 1080},
        "user_agent": USER_AGENT,
        "locale": "en-US",
        "timezone_id": "America/Chicago",
        "extra_http_headers": dict(EXTRA_HEADERS),
    }
    if storage_state is not None:
        kwargs["storage_state"] = storage_state
    return kwargs


async def apply_stealth(context) -> None:
    """Install the init script on a context (runs before page JS on every
    navigation). Call once right after creating the context."""
    await context.add_init_script(_INIT_SCRIPT)
