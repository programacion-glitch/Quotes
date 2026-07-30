"""Decision Ledger: registro thread-local de decisiones por corrida."""
import threading

from modules import decision_ledger
from modules.progressive.choice_resolver import resolve_choice


def test_record_sin_start_run_es_noop():
    decision_ledger.record("Roadside", "Yes")
    assert decision_ledger.entries() == []


def test_start_run_resetea_y_record_acumula():
    decision_ledger.start_run("PROGRESSIVE")
    decision_ledger.record("Roadside Assistance", "Selected w/ $250 Deductible",
                           page="Coverages/RATES", source="RULE", rule_id="R-001")
    entries = decision_ledger.entries()
    assert len(entries) == 1
    e = entries[0]
    assert e["mga"] == "PROGRESSIVE"
    assert e["field"] == "Roadside Assistance"
    assert e["chosen"] == "Selected w/ $250 Deductible"
    assert e["rule_id"] == "R-001"
    decision_ledger.start_run("PROGRESSIVE")
    assert decision_ledger.entries() == []  # reset


def test_record_nunca_lanza():
    decision_ledger.start_run("PROGRESSIVE")

    class Boom:
        def __str__(self):
            raise RuntimeError("boom")

    decision_ledger.record("X", Boom())  # no debe explotar
    # la entrada mala se descarta o se stringifica, pero nunca rompe
    assert isinstance(decision_ledger.entries(), list)


def test_threads_aislados():
    """Un worker GEICO y uno Progressive en paralelo no se mezclan."""
    results = {}

    def run(mga):
        decision_ledger.start_run(mga)
        decision_ledger.record(f"campo-{mga}", "valor")
        results[mga] = decision_ledger.entries()

    t1 = threading.Thread(target=run, args=("PROGRESSIVE",))
    t2 = threading.Thread(target=run, args=("GEICO",))
    t1.start(); t2.start(); t1.join(); t2.join()
    assert [e["mga"] for e in results["PROGRESSIVE"]] == ["PROGRESSIVE"]
    assert [e["mga"] for e in results["GEICO"]] == ["GEICO"]


def test_resolve_choice_registra_matched_y_defaulted():
    decision_ledger.start_run("PROGRESSIVE")
    resolve_choice("Body Type", "Dump Truck", ["Dump Truck", "Flatbed"])
    resolve_choice("Rental", None, ["Yes", "No"], default="No")
    entries = decision_ledger.entries()
    assert len(entries) == 2
    assert entries[0]["source"] == "MATCHED"
    assert entries[1]["source"] == "DEFAULTED"
    assert entries[1]["chosen"] == "No"


def test_restore_re_siembra_entradas_previas():
    decision_ledger.start_run("PROGRESSIVE")
    decision_ledger.record("Business Type", "LLC", source="MATCHED")
    base = decision_ledger.entries()

    decision_ledger.start_run("PROGRESSIVE")  # reset a vacío
    assert decision_ledger.entries() == []
    decision_ledger.restore(base)
    assert decision_ledger.entries() == base


def test_restore_sin_start_run_es_noop():
    decision_ledger.restore([{"field": "X", "chosen": "Y"}])
    assert decision_ledger.entries() == []


def test_retry_loop_no_acumula_entradas_de_intentos_fallidos():
    """Reproduce el patrón real de _run_with_browser en
    modules/progressive/client.py y modules/geico/client.py: el
    field-mapper corre UNA vez antes del retry loop (7-11 entradas según
    la MGA); el loop reintenta el wizard completo hasta
    ``1 + max_retries`` veces. Un intento que falla a mitad del wizard
    deja entradas del wizard en el ledger; si el siguiente intento no
    resetea antes de correr, esas entradas del intento fallido sobreviven
    junto a las del intento exitoso -> filas duplicadas/contradictorias en
    la tabla "Decisiones tomadas" del correo (Finding 1).

    Bajo el comportamiento viejo (sin decision_ledger.restore() y sin el
    reset por-intento en el cliente) esta prueba falla: el ledger final
    contendría "Roadside Assistance" = "Yes" (intento 1, descartado) EN VEZ
    DE únicamente "No" (intento 2, el que ganó), y con más de 4 entradas.
    """
    # --- field mapper (corre UNA vez, antes del retry loop) ---
    decision_ledger.start_run("PROGRESSIVE")
    decision_ledger.record("Business Type", "LLC", source="MATCHED")
    decision_ledger.record("Entity type / estructura del negocio", "LLC",
                            source="RULE", rule_id="R-001")
    mapper_entries = decision_ledger.entries()
    assert len(mapper_entries) == 2

    # --- attempt 1: falla a mitad del wizard, tras registrar una decisión ---
    decision_ledger.start_run("PROGRESSIVE")
    decision_ledger.restore(mapper_entries)
    decision_ledger.record("Roadside Assistance", "Yes", page="Coverages/RATES",
                            source="RULE", rule_id="R-002")
    assert len(decision_ledger.entries()) == 3  # mapper(2) + intento1(1)

    # --- retry: attempt 2, exitoso, con una decisión DIFERENTE para el
    # mismo campo (simula que el wizard tomó otro camino esta vez) ---
    decision_ledger.start_run("PROGRESSIVE")
    decision_ledger.restore(mapper_entries)
    decision_ledger.record("Roadside Assistance", "No", page="Coverages/RATES",
                            source="RULE", rule_id="R-002")
    decision_ledger.record("MTC Limit", "$100k with a $1,000 Deductible",
                            page="Coverages/RATES", source="DEFAULT", rule_id="R-037")

    final = decision_ledger.entries()
    fields = [e["field"] for e in final]

    # Las entradas del mapper aparecen UNA sola vez.
    assert fields.count("Business Type") == 1
    assert fields.count("Entity type / estructura del negocio") == 1
    # Solo las entradas del intento GANADOR (el 2) sobreviven.
    assert fields.count("Roadside Assistance") == 1
    roadside = next(e for e in final if e["field"] == "Roadside Assistance")
    assert roadside["chosen"] == "No"
    assert "MTC Limit" in fields
    # Nada del intento 1 quedó colgando.
    assert len(final) == 4
