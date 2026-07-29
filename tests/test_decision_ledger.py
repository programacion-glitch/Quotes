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
