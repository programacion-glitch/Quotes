"""Guard de _rpa_mgas_enabled: GEICO es env-driven (string/bool tolerante)."""
from workflow_orchestrator import _rpa_mgas_enabled


class _Cfg:
    def __init__(self, val):
        self._val = val

    def get(self, key, default=None):
        if key == "rule_engine.geico_queue_enabled":
            return self._val
        return default


def test_geico_on_when_string_true():
    assert _rpa_mgas_enabled(_Cfg("true")) == {"PROGRESSIVE", "GEICO"}


def test_geico_on_when_bool_true():
    assert _rpa_mgas_enabled(_Cfg(True)) == {"PROGRESSIVE", "GEICO"}


def test_geico_off_when_string_false():
    assert _rpa_mgas_enabled(_Cfg("false")) == {"PROGRESSIVE"}


def test_geico_off_when_unresolved_placeholder():
    # Si la var de entorno no está seteada, config deja el literal "${...}":
    # debe quedar GEICO OFF (señal de que hay que setear GEICO_QUEUE_ENABLED).
    assert _rpa_mgas_enabled(_Cfg("${GEICO_QUEUE_ENABLED}")) == {"PROGRESSIVE"}
