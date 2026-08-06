"""Diagnóstico 2026-08-06: sin VPN, Imperva bloquea gateway.geico.com por IP
(Error 15) y el bot moría con "Login landing did not resolve" tras dos
intentos de ~2 min. El preflight lo detecta antes y deja un mensaje
accionable; y el landing acepta gateway2 (GEICO balancea entre ambos)."""
from unittest.mock import MagicMock, patch

from modules.geico import client as geico_client
from modules.geico.pages.login_page import (
    _host_is_gateway,
    _is_authenticated_gateway,
)


class TestGatewayHosts:
    def test_gateway2_es_gateway(self):
        """GEICO balancea a gateway2; antes quedaba 'unknown' y quemaba el
        primer intento de login entero."""
        assert _host_is_gateway("https://gateway2.geico.com/") is True
        assert _is_authenticated_gateway(
            "https://gateway2.geico.com/Dashboard") is True

    def test_gateway_normal_sigue_siendo_gateway(self):
        assert _host_is_gateway("https://gateway.geico.com/Dashboard") is True
        assert _host_is_gateway("https://sub.gateway.geico.com/x") is True

    def test_no_confunde_el_relaystate_del_b2c(self):
        """El substring naïve matcheaba el query param y daba login por hecho."""
        url = ("https://geicoextendprod.b2clogin.com/authorize?relayState="
               "https%3A%2F%2Fgateway.geico.com%2FDashboard")
        assert _host_is_gateway(url) is False

    def test_rechaza_hosts_ajenos(self):
        assert _host_is_gateway("https://gateway.geico.com.evil.com/") is False
        assert _host_is_gateway("https://ecams.geico.com/") is False


def _resp(status, text):
    r = MagicMock()
    r.status_code = status
    r.text = text
    return r


class TestPreflightBloqueoWAF:
    def test_detecta_el_bloqueo_de_incapsula(self):
        with patch("requests.get",
                   return_value=_resp(403, '<script src="/_Incapsula_Resource?')):
            assert geico_client._gateway_blocked_by_waf() is True

    def test_gateway_sano_no_es_bloqueo(self):
        with patch("requests.get", return_value=_resp(200, "<html>login</html>")):
            assert geico_client._gateway_blocked_by_waf() is False

    def test_403_ajeno_no_se_confunde_con_incapsula(self):
        with patch("requests.get", return_value=_resp(403, "Forbidden")):
            assert geico_client._gateway_blocked_by_waf() is False

    def test_error_de_red_no_inventa_diagnostico(self):
        """Sin red/DNS/timeout: False — que falle el flujo normal y reporte
        lo que realmente pase, en vez de culpar a la VPN."""
        with patch("requests.get", side_effect=OSError("dns")):
            assert geico_client._gateway_blocked_by_waf() is False
