"""Anti-bot fingerprint config (GEICO / Imperva Incapsula).

The truncated UA was the bot tell that got our context blocked while the
MCP browser (full Chrome UA) sailed through — pin the realistic shape so it
never regresses.
"""

from __future__ import annotations

from modules.geico import stealth


def test_user_agent_is_full_chrome_not_truncated():
    ua = stealth.USER_AGENT
    assert "Chrome/" in ua          # the missing piece that flagged us
    assert "Safari/537.36" in ua
    assert not ua.rstrip().endswith("AppleWebKit/537.36")


def test_launch_args_disable_automation_controlled():
    assert "--disable-blink-features=AutomationControlled" in stealth.LAUNCH_ARGS


def test_launch_kwargs_carries_headless_and_args():
    kw = stealth.launch_kwargs(headless=False)
    assert kw["headless"] is False
    assert "--disable-blink-features=AutomationControlled" in kw["args"]


def test_context_kwargs_uses_full_ua_and_locale():
    kw = stealth.context_kwargs()
    assert kw["user_agent"] == stealth.USER_AGENT
    assert kw["locale"] == "en-US"
    assert kw["viewport"] == {"width": 1920, "height": 1080}
    assert "storage_state" not in kw  # omitted when None


def test_context_kwargs_includes_storage_state_when_given():
    kw = stealth.context_kwargs(storage_state="data/geico_session.json")
    assert kw["storage_state"] == "data/geico_session.json"


def test_init_script_scrubs_webdriver():
    assert "navigator.webdriver" in stealth._INIT_SCRIPT
    assert "window.chrome" in stealth._INIT_SCRIPT
