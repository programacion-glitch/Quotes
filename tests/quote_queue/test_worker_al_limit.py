"""El worker cotiza el límite de AL que le tocó al job (R-097).

El perfil viaja serializado en el job, y todos los jobs de una submission
llevan el MISMO perfil: lo único que los distingue es `al_limit`. El worker es
el que lo aplica, en un solo punto — de ahí lo leen Progressive
(`CoveragesRatesPage`) y GEICO (`_bi_limits_to_geico`) sin cambios.
"""
import json
from unittest.mock import MagicMock

from modules.quote_queue.store import QuoteQueueStore
from modules.quote_queue.worker import QuoteWorker
from modules.quote_profile import QuoteProfile


def _perfil_json(limite="$1M CSL"):
    p = QuoteProfile()
    p.applicant.business_name = "T&S LOGISTICS"
    p.applicant.usdot = "9731476"
    p.coverages_detail.bodily_injury_limit = limite
    return json.dumps(p.to_dict())


def _worker_que_captura(store):
    """Worker cuyo create_quote solo anota con qué perfil lo llamaron."""
    visto = {}

    def create_quote(profile, effective_date):
        visto["limite"] = profile.coverages_detail.bodily_injury_limit
        return None  # sin resultado → el worker lo marca failed; no importa acá

    w = QuoteWorker("PROGRESSIVE", store, create_quote=create_quote,
                    gmail=MagicMock())
    w._upload_enabled = False
    return w, visto


def test_el_job_de_750k_cotiza_750k_aunque_el_perfil_diga_1m(tmp_path):
    store = QuoteQueueStore(tmp_path / "q.db")
    try:
        store.enqueue("sub-1", "PROGRESSIVE", _perfil_json("$1M CSL"), None,
                      "9731476", al_limit="$750K CSL")
        worker, visto = _worker_que_captura(store)

        worker.run_once()

        assert visto["limite"] == "$750K CSL"
    finally:
        store.close()


def test_sin_al_limit_se_respeta_el_limite_del_perfil(tmp_path):
    """Retrocompatible: los jobs de una sola cotización no cambian."""
    store = QuoteQueueStore(tmp_path / "q.db")
    try:
        store.enqueue("sub-1", "PROGRESSIVE", _perfil_json("$1M CSL"), None,
                      "9731476")
        worker, visto = _worker_que_captura(store)

        worker.run_once()

        assert visto["limite"] == "$1M CSL"
    finally:
        store.close()


def test_el_pdf_va_a_drive_con_el_limite_en_el_nombre(tmp_path):
    """Dos indicaciones del mismo carrier el mismo día chocaban por nombre y
    Drive descartaba la segunda ('ya existe'). El límite las desambigua."""
    pdf = tmp_path / "quote.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    store = QuoteQueueStore(tmp_path / "q.db")
    try:
        store.enqueue("sub-1", "PROGRESSIVE", _perfil_json(), None, "9731476",
                      al_limit="$750K CSL")

        resultado = MagicMock()
        resultado.success = True
        resultado.premium = "$44,621"
        resultado.quote_number = "CA117054124"
        resultado.pdf_path = str(pdf)
        resultado.screenshot_path = None
        resultado.needs_ssn = False
        resultado.not_eligible = False

        drive = MagicMock()
        worker = QuoteWorker("PROGRESSIVE", store,
                             create_quote=lambda *a: resultado,
                             gmail=MagicMock(), drive_manager=drive)
        worker._upload_enabled = True

        worker.run_once()

        assert drive.upload_quote_indication.called
        _, kwargs = drive.upload_quote_indication.call_args
        assert kwargs["al_limit"] == "$750K CSL"
    finally:
        store.close()


def test_el_correo_final_distingue_las_dos_cotizaciones(tmp_path):
    """Las dos filas son de PROGRESSIVE: sin el límite en cada una, Diana no
    sabe cuál indicación corresponde a cuál precio."""
    from modules.quote_queue.models import JobStatus

    store = QuoteQueueStore(tmp_path / "q.db")
    try:
        sub = "sub-ts"
        store.save_submission_context(sub, json.dumps({
            "recipient": "dianarubio@h2oins.com",
            "subject": "[ANALISIS] T&S LOGISTICS",
            "body_html": "<!--RPA_QUOTES_SECTION-->",
            "attachment_paths": [],
        }))
        uno = store.enqueue(sub, "PROGRESSIVE", _perfil_json(), None, "9731476",
                            al_limit="$1M CSL")
        dos = store.enqueue(sub, "PROGRESSIVE", _perfil_json(), None, "9731476",
                            al_limit="$750K CSL")
        store.mark_terminal(uno, JobStatus.QUOTED, premium="$53,064",
                            quote_number="CA1", error="ok")
        store.mark_terminal(dos, JobStatus.QUOTED, premium="$44,621",
                            quote_number="CA2", error="ok")

        gmail = MagicMock()
        gmail.send_threaded.return_value = True
        worker = QuoteWorker("PROGRESSIVE", store, create_quote=lambda *a: None,
                             gmail=gmail)

        assert worker.maybe_send_submission_email(sub) is True

        _, kwargs = gmail.send_threaded.call_args
        body = kwargs["body"]
        assert "$1M CSL" in body and "$750K CSL" in body
        assert "$53,064" in body and "$44,621" in body
    finally:
        store.close()
