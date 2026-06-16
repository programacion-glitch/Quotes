"""
Runner del pipeline RPA: productor (monitor de inbox) + consumidores (un
QuoteWorker por MGA, en hilos). La cola SQLite es durable, así que un reinicio
retoma donde quedó; al arrancar se llama reclaim_stale() para recuperar jobs
colgados por un crash a mitad de cotización.

Uso:
    <python> runner.py
"""

import threading

from workflow_orchestrator import QuoteWorkflowOrchestrator, QUOTE_DB_PATH
from modules.quote_queue.store import QuoteQueueStore
from modules.quote_queue.worker import QuoteWorker
from modules.email_sender import EmailSender
from modules.progressive.client import ProgressiveClient


def _create_quote_fns(rpa_mgas: set) -> dict:
    """create_quote por MGA. GEICO sólo si el flag lo habilitó."""
    fns = {"PROGRESSIVE": ProgressiveClient.create_quote}
    if "GEICO" in rpa_mgas:
        from modules.geico.client import GEICOClient
        fns["GEICO"] = GEICOClient.create_quote
    return fns


def _worker_loop(worker: QuoteWorker, stop: threading.Event, idle_sleep: float = 5.0):
    while not stop.is_set():
        try:
            took = worker.run_once()
        except Exception as e:
            print(f"    [worker:{worker.mga}] loop error: {e}")
            took = False
        if not took:
            stop.wait(idle_sleep)  # cola vacía → dormir un poco


def main():
    orch = QuoteWorkflowOrchestrator()
    store = QuoteQueueStore(QUOTE_DB_PATH)

    reclaimed = store.reclaim_stale()
    if reclaimed:
        print(f"  [runner] reclaim_stale: {reclaimed} job(s) colgado(s) → pending")

    sender = EmailSender(orch.email_address, orch.email_password)
    create_fns = _create_quote_fns(orch.rpa_mgas)

    stop = threading.Event()
    threads = []
    for mga in sorted(orch.rpa_mgas):
        if mga not in create_fns:
            print(f"  [runner] WARNING: sin create_quote para {mga}, se omite")
            continue
        worker = QuoteWorker(mga, store, create_quote=create_fns[mga], email_sender=sender)
        t = threading.Thread(target=_worker_loop, args=(worker, stop), name=f"worker-{mga}", daemon=True)
        t.start()
        threads.append(t)
        print(f"  [runner] worker {mga} arrancado")

    # El monitor de inbox corre en el hilo principal (bloqueante).
    try:
        orch.start_monitoring(check_interval=60)
    except KeyboardInterrupt:
        print("\n  [runner] deteniendo workers...")
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=5)
        store.close()


if __name__ == "__main__":
    main()
