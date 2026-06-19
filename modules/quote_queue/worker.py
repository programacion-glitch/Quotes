"""
QuoteWorker — consumidor de la cola, uno por MGA.

Reclama jobs en serie (sesión única por MGA), corre create_quote, clasifica el
resultado a un estado terminal + reason code humanizable, y cuando TODOS los
jobs de una submission terminaron, manda el correo de análisis (una sola vez)
con la sección RPA inyectada y los PDFs adjuntos.
"""

import json
import time
from typing import Callable, List

from modules.quote_profile import QuoteProfile
from modules.quote_queue.models import JobStatus
from modules.quote_queue.messages import (
    RpaQuoteOutcome, RPA_SECTION_MARKER, render_rpa_section,
)


# Tras este nº de intentos, un job 'deferred' deja de bloquear el correo: se
# marca terminal (pending_retry → halted) para no esperar para siempre.
MAX_DEFER_ATTEMPTS = 3
# Backoff por defecto al diferir (producto no disponible / cooldown de OTP).
DEFER_SECONDS = 1800


def classify_result(result) -> tuple:
    """Mapa QuoteResult → (status, reason, premium, quote_number, pdf_path).

    `status` ∈ {quoted, halted, deferred, failed}. `reason` es un código
    humanizable (ver messages.humanize). Tolera QuoteResults sin los flags de
    GEICO vía getattr; para Progressive cae a matchear el texto del error.
    """
    price = getattr(result, "price", None)
    premium = getattr(price, "annual_premium", None) if price else None
    quote_number = getattr(price, "quote_number", None) if price else None
    pdf_path = getattr(result, "pdf_path", None)

    if getattr(result, "success", False):
        reason = "ok" if pdf_path else "ok_no_pdf"
        return ("quoted", reason, premium, quote_number, pdf_path)

    if getattr(result, "needs_manual_review", False):
        return ("halted", "needs_ssn", premium, quote_number, pdf_path)
    if getattr(result, "halted", False):
        return ("halted", "not_eligible", premium, quote_number, pdf_path)
    if getattr(result, "session_expired", False):
        return ("deferred", "pending_retry", premium, quote_number, pdf_path)

    # Progressive (sin flags): inferir por el texto del error.
    err = (getattr(result, "error", None) or "").lower()
    if "ssn" in err or "social security" in err:
        return ("halted", "needs_ssn", premium, quote_number, pdf_path)
    if "elegib" in err or "fmcsa" in err or "unable to complete" in err:
        return ("halted", "not_eligible", premium, quote_number, pdf_path)

    return ("failed", "error", premium, quote_number, pdf_path)


class QuoteWorker:
    def __init__(self, mga: str, store, create_quote: Callable, gmail,
                 label_processed: str = "Cotizado-Bot"):
        self.mga = mga
        self.store = store
        self.create_quote = create_quote   # (profile, effective_date) -> QuoteResult
        self.gmail = gmail                  # GmailClient (send_threaded/add_label)
        self.label_processed = label_processed

    def run_once(self) -> bool:
        """Procesa un job. Devuelve True si tomó uno, False si la cola estaba vacía."""
        job = self.store.claim_next(self.mga)
        if job is None:
            return False
        self.store.mark_running(job.id)

        try:
            profile = QuoteProfile.from_dict(json.loads(job.profile_json))
            result = self.create_quote(profile, job.effective_date)
        except Exception as e:  # falla dura del cliente RPA
            self.store.mark_terminal(job.id, JobStatus.FAILED, error="error",
                                     screenshot_path=None)
            print(f"    [worker:{self.mga}] create_quote crashed: {e}")
            self.maybe_send_submission_email(job.submission_id)
            return True

        status, reason, premium, quote_number, pdf_path = classify_result(result)
        screenshot = getattr(result, "screenshot_path", None)

        if status == "deferred" and job.attempts < MAX_DEFER_ATTEMPTS:
            self.store.mark_deferred(job.id, retry_after=time.time() + DEFER_SECONDS)
            print(f"    [worker:{self.mga}] job {job.id} deferred "
                  f"(attempt {job.attempts}/{MAX_DEFER_ATTEMPTS})")
            return True

        # deferred agotado → no bloquear el correo: tratar como halted pendiente.
        if status == "deferred":
            status, reason = "halted", "pending_retry"

        self.store.mark_terminal(
            job.id, JobStatus(status), premium=premium, quote_number=quote_number,
            pdf_path=pdf_path, screenshot_path=screenshot, error=reason,
        )
        self.maybe_send_submission_email(job.submission_id)
        return True

    def maybe_send_submission_email(self, submission_id: str) -> bool:
        """Si todos los jobs terminaron, manda el correo de análisis UNA vez."""
        if not self.store.siblings_all_terminal(submission_id):
            return False
        if not self.store.try_claim_submission_email(submission_id):
            return False  # otro worker ya lo está mandando / lo mandó

        raw_ctx = self.store.get_submission_context(submission_id)
        if not raw_ctx:
            print(f"    [worker:{self.mga}] no context for {submission_id}; skip email")
            return False
        ctx = json.loads(raw_ctx)

        jobs = self.store.get_jobs(submission_id)
        outcomes: List[RpaQuoteOutcome] = [
            RpaQuoteOutcome(
                mga=j.mga, status=j.status, reason=(j.error or "error"),
                premium=j.premium, pdf_path=j.pdf_path,
            )
            for j in jobs
        ]
        body = ctx["body_html"].replace(RPA_SECTION_MARKER, render_rpa_section(outcomes))

        # Los PDFs de CADA cotización (j.pdf_path) van adjuntos, junto al
        # BlueQuote original.
        attachments = list(ctx.get("attachment_paths", []))
        attachments += [j.pdf_path for j in jobs if j.pdf_path]

        ok = self.gmail.send_threaded(
            to=ctx["recipient"],
            cc=ctx.get("cc"),
            subject=ctx["subject"],
            body=body,
            attachments=attachments,
            is_html=True,
            thread_id=ctx.get("thread_id"),
            in_reply_to=ctx.get("in_reply_to"),
        )
        if ok and ctx.get("message_id"):
            try:
                self.gmail.add_label(ctx["message_id"], self.label_processed)
            except Exception as e:  # etiquetar nunca debe tumbar el envío
                print(f"    [worker:{self.mga}] label warn: {e}")
        print(f"    [worker:{self.mga}] analysis email for {submission_id} "
              f"sent={ok} (outcomes={len(outcomes)})")
        return ok
