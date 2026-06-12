"""Login landing classification.

Live bug (2026-06-12 batch): reusing a valid session, GEICO served
gateway.geico.com with `sessionexpired` in the URL, so login() entered the
"force re-login" branch, re-navigated to /dashboard — which loaded the
AUTHENTICATED dashboard — but then blindly waited for the Username textbox
(absent, we're logged in) and timed out 30s twice => false "login failed",
156s burned per quote. The fix: after any navigation, RE-CLASSIFY the
landing and accept a live gateway as authenticated before demanding a form.

`_classify_landing` is the pure per-tick decision exercised here.
"""

from __future__ import annotations

from modules.geico.pages.login_page import _classify_landing


def test_live_gateway_dashboard_is_authenticated():
    assert _classify_landing(
        "https://gateway.geico.com/Dashboard", username_visible=False
    ) == "authenticated"


def test_username_form_is_login_form():
    assert _classify_landing(
        "https://h2o.b2clogin.com/h2o.onmicrosoft.com/oauth2/authorize",
        username_visible=True,
    ) == "login_form"


def test_sessionexpired_without_form_is_session_expired():
    assert _classify_landing(
        "https://gateway.geico.com/account/sessionexpireddashboard",
        username_visible=False,
    ) == "session_expired"


def test_form_wins_over_url():
    # An authenticated dashboard NEVER renders the Username box. So if it's
    # visible we're on the sign-in page, whatever the URL says.
    assert _classify_landing(
        "https://gateway.geico.com/Dashboard", username_visible=True
    ) == "login_form"


def test_bare_gateway_root_is_unknown_not_authenticated():
    # THE regression: a cookieless navigation sits at the bare root before
    # bouncing to b2c. It must NOT be read as authenticated (live 2026-06-12:
    # that won a race and skipped login -> 'Sign up or sign in' at /quote).
    assert _classify_landing(
        "https://gateway.geico.com/", username_visible=False
    ) == "unknown"
    assert _classify_landing(
        "https://gateway.geico.com", username_visible=False
    ) == "unknown"


def test_bare_root_with_dashboard_marker_is_authenticated():
    # If the logged-in dashboard chrome is on screen, the bare root IS us
    # logged in (the redirect to /Dashboard just hasn't landed yet).
    assert _classify_landing(
        "https://gateway.geico.com/", username_visible=False,
        auth_marker_visible=True,
    ) == "authenticated"


def test_quote_path_is_authenticated():
    assert _classify_landing(
        "https://gateway.geico.com/quote", username_visible=False
    ) == "authenticated"


def test_unknown_when_nothing_matches():
    assert _classify_landing(
        "https://h2o.b2clogin.com/loading", username_visible=False
    ) == "unknown"


def test_relaystate_query_does_not_falsely_authenticate():
    # The b2clogin authorize URL carries gateway.geico.com in relayState — it
    # must NOT count as authenticated (host is b2clogin, not gateway).
    url = (
        "https://h2o.b2clogin.com/authorize?"
        "relayState=https%3A%2F%2Fgateway.geico.com%2FDashboard"
    )
    assert _classify_landing(url, username_visible=True) == "login_form"
    assert _classify_landing(url, username_visible=False) == "unknown"
