"""
Runner del bot autónomo: productor (monitor del inbox) + consumidores (un
worker-thread por MGA), en un solo proceso, sobre la cola durable.

Entrypoint:  python -m modules.quote_queue.runner
"""

import threading
import time

from modules.config_manager import get_config
from modules.gmail_client import GmailClient
from modules.quote_queue.worker import QuoteWorker


def poll_once(gmail, orchestrator, subject_filter: str) -> int:
    """Un ciclo del monitor: procesa cada no-leído y lo marca leído (siempre,
    aun si el procesamiento falla, para no reprocesarlo). Devuelve cuántos vio."""
    emails = gmail.fetch_unread(subject_filter)
    for email_data in emails:
        try:
            orchestrator.process_email(email_data)
        except Exception as e:  # un correo malo no frena el monitor
            print(f"  [monitor] error procesando "
                  f"{email_data.get('subject', '')[:50]}: {e}")
        finally:
            try:
                gmail.mark_read(email_data["id"])
            except Exception as e:
                print(f"  [monitor] no se pudo marcar leído: {e}")
    return len(emails)


def _create_quote_for(mga: str):
    """Devuelve la función create_quote(profile, eff_date) del cliente del MGA."""
    if mga == "PROGRESSIVE":
        from modules.progressive.client import ProgressiveClient
        return ProgressiveClient.create_quote
    if mga == "GEICO":
        from modules.geico.client import GEICOClient
        return GEICOClient.create_quote
    raise ValueError(f"MGA desconocido: {mga}")


def _worker_loop(worker, stop: threading.Event, idle_sleep: float = 5.0):
    while not stop.is_set():
        try:
            took = worker.run_once()
        except Exception as e:
            print(f"  [worker:{worker.mga}] loop error: {e}")
            took = False
        if not took:
            stop.wait(idle_sleep)


def run_forever(check_interval: int = 60) -> None:
    config = get_config()
    gmail = GmailClient()

    # Importar acá para evitar ciclos de import al cargar el módulo.
    from workflow_orchestrator import QuoteWorkflowOrchestrator
    orchestrator = QuoteWorkflowOrchestrator()
    store = orchestrator.quote_store
    subject_filter = config.get("email.monitoring.subject_filter", "Submission")
    label = config.get("email.label_processed", "Cotizado-Bot")

    # Recuperación de crash: jobs colgados vuelven a pending.
    reclaimed = store.reclaim_stale()
    print(f"[runner] reclaim_stale -> {reclaimed} jobs")

    # Un worker-thread por MGA habilitado.
    stop = threading.Event()
    threads = []
    for mga in sorted(orchestrator.rpa_mgas):
        worker = QuoteWorker(mga, store, _create_quote_for(mga), gmail,
                             label_processed=label)
        t = threading.Thread(target=_worker_loop, args=(worker, stop),
                             name=f"worker-{mga}", daemon=True)
        t.start()
        threads.append(t)
    print(f"[runner] workers: {sorted(orchestrator.rpa_mgas)}")

    print(f"[runner] monitoreando '{subject_filter}' cada {check_interval}s")
    try:
        while True:
            n = poll_once(gmail, orchestrator, subject_filter)
            if n:
                print(f"[monitor] procesados {n} correo(s)")
            time.sleep(check_interval)
    except KeyboardInterrupt:
        print("\n[runner] apagando...")
        stop.set()


if __name__ == "__main__":
    run_forever()
