"""
Runner del bot autónomo: productor (monitor del inbox) + consumidores (un
worker-thread por MGA), en un solo proceso, sobre la cola durable.

Entrypoint:  python -m modules.quote_queue.runner
"""

import sys
import threading
import time

# La consola de Windows (cp1252) no puede encodear los emojis/acentos que el bot
# imprime (⚠️, ✓, ñ, etc.) → UnicodeEncodeError que tumba el proceso. Forzar
# UTF-8 como hacen los scripts. En Docker ya es UTF-8; esto hace al runner
# robusto también en el host Windows.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from modules.config_manager import get_config
from modules.gmail_client import GmailClient
from modules.quote_queue.worker import QuoteWorker
from modules.quote_queue.sender_filter import is_processable_submission


def poll_once(gmail, orchestrator, subject_filter: str, store,
              after_epoch=None, rt_senders=None, new_venture_senders=None,
              skip_cache=None) -> int:
    """Un ciclo del monitor: procesa cada submission ORIGINAL de ventas.
    Devuelve cuántas PROCESÓ (no cuántas fetcheó).

    TRANSPARENCIA TOTAL (Usuario 2026-07-29): el bot NO etiqueta, NO marca
    leído, NO modifica el correo de ventas de ninguna forma. La dedup vive
    en la cola SQLite (`store.try_claim_email` por Gmail message-id), NO en
    el buzón. Se reclama ANTES de procesar (mismas semánticas que la
    etiqueta vieja en finally: un crash a mitad de proceso no reprocesa).

    Guard de remitentes: idéntico a antes; lo que no pasa NO se procesa NI
    se reclama (si mañana entra al allowlist, sigue procesable). Sí se
    recuerda en `skip_cache` (memoria del proceso) para no re-descargarlo
    cada ciclo — al reiniciar el bot se re-evalúa contra el allowlist vigente.

    after_epoch: corte por fecha — solo correos recibidos después de ese epoch.
    skip_cache: set en memoria compartido entre ciclos; junto con
    store.is_seen evita el messages.get (cuerpo + adjuntos) de correos ya
    vistos/rechazados. Crítico con el scanner a 5s.
    """
    guard_active = not (rt_senders is None and new_venture_senders is None)
    rt = rt_senders or set()
    nv = new_venture_senders or set()
    from_allowlist = sorted(rt | nv) if guard_active else None
    cache = skip_cache if skip_cache is not None else set()

    def _skip(msg_id: str) -> bool:
        return msg_id in cache or store.is_seen(msg_id)

    emails = gmail.fetch_unread(subject_filter, after_epoch=after_epoch,
                                from_allowlist=from_allowlist,
                                skip_message_id=_skip)
    processed = 0
    for email_data in emails:
        if guard_active and not is_processable_submission(
                email_data.get("sender_email", ""),
                email_data.get("subject", ""), rt, nv):
            cache.add(email_data["id"])  # no re-descargar mientras viva el proceso
            continue  # no es submission original de ventas
        if not store.try_claim_email(email_data["id"]):
            continue  # ya visto en un ciclo/arranque anterior
        processed += 1
        try:
            orchestrator.process_email(email_data)
        except Exception as e:  # un correo malo no frena el monitor
            print(f"  [monitor] error procesando "
                  f"{email_data.get('subject', '')[:50]}: {e}")
    return processed


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


# Corte por fecha (historia completa):
# - Hasta 2026-07-06 el epoch de la 1ra corrida se persistía en un archivo;
#   sin dedup durable, una caída larga reprocesaba días de backlog no-leído
#   → el usuario pidió cortar SIEMPRE en el arranque.
# - 2026-07-29 llegó seen_emails (dedup atómica por message-id): reprocesar
#   se volvió imposible.
# - 2026-08-03 el contenedor estuvo caído 3 días y el corte-al-arranque dejó
#   ese backlog en tierra de nadie → el usuario aprobó volver a persistir el
#   corte (tabla meta, key monitor_cutoff_epoch): misma semántica (solo NO
#   leídos posteriores al corte), pero los reinicios retoman donde quedaron.
_CUTOFF_KEY = "monitor_cutoff_epoch"


def _load_sender_sets(config):
    """Devuelve (rt_set, new_venture_set) en minúscula desde la config."""
    rt = {str(a).strip().lower() for a in
          (config.get("email.monitoring.senders.rt", []) or [])}
    nv = {str(a).strip().lower() for a in
          (config.get("email.monitoring.senders.new_venture", []) or [])}
    return rt, nv


def run_forever(check_interval: int = None) -> None:
    if check_interval is None:
        import os
        check_interval = int(os.getenv("MONITOR_INTERVAL_SECONDS", "5"))
    config = get_config()
    gmail = GmailClient()

    # Importar acá para evitar ciclos de import al cargar el módulo.
    from workflow_orchestrator import QuoteWorkflowOrchestrator
    orchestrator = QuoteWorkflowOrchestrator()
    store = orchestrator.quote_store
    subject_filter = config.get("email.monitoring.subject_filter", "Submission")
    rt_senders, new_venture_senders = _load_sender_sets(config)
    print(f"[runner] remitentes ventas: RT={len(rt_senders)} "
          f"NEW_VENTURE={len(new_venture_senders)}")
    if not rt_senders and not new_venture_senders:
        print("[runner] ⚠️ WARNING: sin remitentes de ventas configurados "
              "(email.monitoring.senders) — el filtro rechazará TODO (fail-closed)")
    # Corte persistido: el primer arranque fija el corte en AHORA (el backlog
    # previo a la puesta en marcha no se toca); los reinicios retoman el corte
    # guardado, así lo que llegue con el bot caído se procesa al volver
    # (seen_emails garantiza cero duplicados).
    from datetime import datetime
    stored = store.get_meta(_CUTOFF_KEY)
    if stored is not None:
        cutoff = float(stored)
        origen = "persistido — retoma donde quedó"
    else:
        cutoff = time.time()
        store.set_meta(_CUTOFF_KEY, cutoff)
        origen = "primer arranque"
    print(f"[runner] corte por fecha: solo correos NO LEÍDOS posteriores a "
          f"{datetime.fromtimestamp(cutoff).isoformat()} ({origen})")

    # Recuperación de crash: jobs colgados vuelven a pending.
    reclaimed = store.reclaim_stale()
    print(f"[runner] reclaim_stale -> {reclaimed} jobs")

    # Un worker-thread por MGA habilitado.
    stop = threading.Event()
    threads = []
    for mga in sorted(orchestrator.rpa_mgas):
        worker = QuoteWorker(mga, store, _create_quote_for(mga), gmail)
        t = threading.Thread(target=_worker_loop, args=(worker, stop),
                             name=f"worker-{mga}", daemon=True)
        t.start()
        threads.append(t)
    print(f"[runner] workers: {sorted(orchestrator.rpa_mgas)}")

    print(f"[runner] monitoreando '{subject_filter}' cada {check_interval}s")
    skip_cache = set()  # rechazados por el guard: no re-descargar cada ciclo
    try:
        while True:
            try:
                n = poll_once(gmail, orchestrator, subject_filter, store,
                              after_epoch=cutoff,
                              rt_senders=rt_senders,
                              new_venture_senders=new_venture_senders,
                              skip_cache=skip_cache)
                if n:
                    print(f"[monitor] procesados {n} correo(s)")
            except Exception as e:
                # Errores transitorios de red/API (TimeoutError [WinError 10060],
                # RemoteDisconnected, HttpError 5xx...) NO deben tumbar el runner:
                # se loguea y se reintenta el próximo ciclo. Los workers siguen
                # vivos. KeyboardInterrupt NO es Exception → escapa a la salida.
                print(f"[monitor] ciclo falló ({type(e).__name__}: {e}); "
                      f"reintento en {check_interval}s")
            time.sleep(check_interval)
    except KeyboardInterrupt:
        print("\n[runner] apagando...")
        stop.set()


if __name__ == "__main__":
    run_forever()
