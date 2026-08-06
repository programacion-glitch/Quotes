"""
Workflow Orchestrator

Coordinates the complete email auto-response workflow.
"""

import sys
import json
import hashlib
import time
from pathlib import Path
from typing import Dict, List, Optional
import tempfile

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.email_receiver import extract_quote_body  # solo el helper de texto
from modules.email_sender import EmailSender  # aún lo usa _dispatch_to_mgas (SMTP, fuera de alcance)
from modules.gmail_client import GmailClient
from modules.pdf_extractor import BlueQuotePDFExtractor
from modules.comm_tdn_mapper import COMMTDNMapper
from modules.mga_reader import MGAReader
from modules.email_template_builder import build_email_response
from modules.config_manager import get_config
from modules.mga_email_reader import MGAEmailReader
from modules.attachment_validator import AttachmentValidator
from modules.drive_manager import DriveManager
from modules.document_ai_extractor import DocumentAIExtractor
from modules.rule_engine import RuleEngine
from modules.analysis_email_builder import build_analysis_email
from modules.quote_queue.store import QuoteQueueStore
from modules.quote_queue.messages import RPA_SECTION_MARKER


# Cola durable compartida entre el orquestador (productor) y el runner (workers).
QUOTE_DB_PATH = Path(__file__).resolve().parent / "data" / "quote_queue.db"
SUBMISSIONS_DIR = Path(__file__).resolve().parent / "data" / "submissions"


def _rpa_mgas_enabled(config) -> set:
    """MGAs que cotizan por RPA. Progressive siempre; GEICO detrás de flag."""
    mgas = {"PROGRESSIVE"}
    if str(config.get("rule_engine.geico_queue_enabled", False)).lower() in ("true", "1", "yes"):
        mgas.add("GEICO")
    return mgas


class QuoteWorkflowOrchestrator:
    """Orchestrates the complete quote processing workflow."""

    def __init__(self):
        """Initialize orchestrator with configuration."""
        self.config = get_config()

        # Email settings
        self.email_address = self.config.get("email.username")
        self.email_password = self.config.get("email.password")

        # Excel path
        self.excel_path = self.config.excel_checklist_path

        # Subject filter
        self.subject_filter = self.config.get("email.monitoring.subject_filter", "Submission New Venture")

        # Testing override
        self.test_email_override = self.config.get("email.test_email_override")

        # Dry run mode
        import os
        self.dry_run = os.getenv("DRY_RUN", "False").lower() in ("true", "1", "yes")

        # Pull latest rules/checklist from Drive (no-op if REGLAS_DRIVE_FILE_ID not set
        # or REGLAS_SYNC_ENABLED=false). Falls back to existing local xlsx if Drive
        # is unreachable. All readers below see the freshest version of the sheet.
        try:
            from modules.drive_sheet_sync import sync_from_env
            self.excel_path = sync_from_env(self.excel_path)
        except Exception as e:
            print(f"  Drive sync skipped ({e}); using existing local xlsx.")

        # Initialize components
        self.mapper = COMMTDNMapper(str(self.excel_path))
        self.mga_reader = MGAReader(str(self.excel_path))
        self.mga_email_reader = MGAEmailReader(str(self.excel_path))
        self.attachment_validator = AttachmentValidator()
        self.drive_manager = DriveManager()
        self.document_extractor = DocumentAIExtractor()
        self.rule_engine = RuleEngine(str(self.excel_path))
        self.rule_engine_enabled = self.config.get("rule_engine.enabled", True)
        self.halt_on_low_confidence = self.config.get("rule_engine.halt_on_low_confidence", True)

        # Approval settings
        self.approval_mode = self.config.get("rule_engine.approval_mode", "manual")
        self.summary_email = self.config.get("rule_engine.summary_email") or self.email_address
        self.confirmation_keyword = self.config.get("rule_engine.confirmation_keyword", "APROBAR")

        # Transporte Gmail API (reemplaza IMAP/SMTP para el flujo de análisis).
        self.gmail = GmailClient()
        self.analysis_to = (self.config.get("email.analysis_to")
                            or self.summary_email)

        # Pending approvals: stores data needed to dispatch after confirmation
        # Key: original subject, Value: dict with all data needed
        self._pending_approvals = {}

        # Cola de cotización RPA (durable). Productor: este orquestador.
        self.quote_store = QuoteQueueStore(QUOTE_DB_PATH)
        self.rpa_mgas = _rpa_mgas_enabled(self.config)

    def process_email(self, email_data: Dict):
        """
        Process a single email. Handles both:
        - New submission emails (with attachments)
        - Confirmation replies (with APROBAR keyword)
        """
        subject = email_data.get('subject', '')
        body = email_data.get('body', '')

        # Check if this is a confirmation reply
        if self.confirmation_keyword.upper() in body.upper() and "[ANALISIS]" in subject:
            self._handle_confirmation(email_data)
            return

        # Skip analysis emails (sent by the bot itself) to avoid loops
        if "ANALISIS" in subject.upper():
            print(f"  Skipping analysis email: {subject[:60]}")
            return

        # Otherwise process as new submission
        self._process_submission(email_data)

    def _process_submission(self, email_data: Dict):
        """Process a new submission email."""
        print(f"\n{'='*60}")
        print(f"PROCESSING SUBMISSION")
        print(f"{'='*60}")

        subject = email_data.get('subject', '')
        sender = email_data.get('sender_email', '')
        sender_name = email_data.get('sender_name', 'Cliente')

        print(f"From: {sender_name} <{sender}>")
        print(f"Subject: {subject}")

        # Step 1: Get attachments
        attachments = email_data.get('attachments', [])
        if not attachments:
            print("No attachments found - skipping")
            return

        # Step 2: Extract data from all documents
        print(f"\nStep 1: Extracting data from {len(attachments)} attachment(s)...")
        try:
            profile = self.document_extractor.extract_all(attachments)
        except Exception as e:
            print(f"  Error: {e}")
            return

        # Override new-venture flag from subject (authoritative signal from sender)
        # — but a REAL current_carrier in the Blue Quote is HARD EVIDENCE that
        # the client is already insured, so never treat as New Venture in that
        # case. OJO: la Blue Quote usa el mismo campo para decir "no tiene
        # aseguradora" ('NEW BUSINESS', 'NEW VENTURE') — eso es evidencia de lo
        # CONTRARIO (visto live con T&S Logistics 2026-08-06).
        current_carrier = (profile.applicant.current_carrier or "").strip()
        carrier_kind = self._carrier_kind(current_carrier)
        if carrier_kind == "real":
            profile.applicant.is_new_venture = False
            if "new venture" in subject.lower():
                print(f"  Subject says 'New Venture' but Blue Quote has current_carrier='{current_carrier}' — treating as established")
        elif carrier_kind == "nv" or "new venture" in subject.lower():
            if carrier_kind == "nv" and "new venture" not in subject.lower():
                print(f"  Blue Quote current_carrier='{current_carrier}' — treating as NEW VENTURE")
            profile.applicant.is_new_venture = True
            # Drop business_years from confidence flags — not applicable to new ventures
            if profile.extraction_confidence:
                profile.extraction_confidence.flags = [
                    f for f in profile.extraction_confidence.flags if f.field != "business_years"
                ]
                # Recompute overall
                still_critical = any(
                    f.field in ["cdl_years", "commodity"]
                    for f in profile.extraction_confidence.flags
                )
                profile.extraction_confidence.overall = "low" if still_critical else "high"
        else:
            # Plain "Submission" = existing client
            profile.applicant.is_new_venture = False

        # Step 3: Check confidence
        confidence = profile.extraction_confidence.overall if profile.extraction_confidence else "unknown"
        print(f"  Confidence: {confidence}")

        if confidence == "low" and self.halt_on_low_confidence:
            flags = profile.extraction_confidence.flags if profile.extraction_confidence else []
            flag_summary = ", ".join(f.field for f in flags) if flags else "unknown"
            print(f"  Low confidence on: {flag_summary} - halting for manual review")
            return

        # Step 4: Get commodity and map
        commodity = profile.commodity or ''
        business_name = profile.applicant.business_name or 'su empresa'
        print(f"  Commodity: {commodity or 'None'}")
        print(f"  Business: {business_name}")

        if not commodity:
            commodity = "N/A"
            tipo_negocio = None
        else:
            print(f"\nStep 2: Mapping commodity...")
            tipo_negocio = self.mapper.map_commodity_to_type(commodity)

        if not tipo_negocio:
            print(f"  No match for commodity: {commodity}")
            self._send_not_found_email(email_data, commodity, sender_name, business_name, subject)
            return

        print(f"  Matched: {tipo_negocio}")

        # Step 5: Get candidate MGAs
        print(f"\nStep 3: Finding MGAs...")
        mga_list = self.mga_reader.get_mga_by_business_type(tipo_negocio)
        print(f"  Found {len(mga_list)} MGA(s)")

        # Step 6: Evaluate rules
        evaluations = []
        if self.rule_engine_enabled and mga_list:
            print(f"\nStep 4: Evaluating rules...")
            try:
                evaluations = self.rule_engine.evaluate(profile, tipo_negocio)
                eligible = [ev for ev in evaluations if ev.eligible]
                ineligible = [ev for ev in evaluations if not ev.eligible]
                print(f"  Eligible: {len(eligible)}, Ineligible: {len(ineligible)}")
            except Exception as e:
                print(f"  Rule engine error: {e}")

        # Step 5: build the analysis email. If an RPA MGA (Progressive, and
        # GEICO if enabled) is eligible, QUEUE the quote and let the worker send
        # this email later — with the price-page PDF attached and the RPA
        # section filled in. Otherwise send it now, as before.
        print(f"\nStep 5: Analysis summary...")
        eligible_rpa = self._eligible_rpa_mgas(evaluations, mga_list)
        analysis = build_analysis_email(
            profile=profile,
            commodity=commodity,
            tipo_negocio=tipo_negocio,
            evaluations=evaluations,
            mga_list=mga_list,
            original_subject=subject,
            confirmation_keyword=self.confirmation_keyword,
            rpa_quotes_section=(RPA_SECTION_MARKER if eligible_rpa else ""),
        )
        analysis_to = self.analysis_to

        if eligible_rpa and not self.dry_run:
            submission_id = self._submission_id(email_data, profile)
            attachment_paths = self._persist_attachments(submission_id, attachments)
            self.quote_store.save_submission_context(submission_id, json.dumps({
                "recipient": analysis_to,
                "subject": analysis["subject"],
                "body_html": analysis["body"],
                "attachment_paths": attachment_paths,
            }))
            eff_date = self._effective_date_from_subject(subject)
            now = time.time()
            queued = []
            for mga in sorted(eligible_rpa):
                if self.quote_store.recently_quoted(
                        mga, profile.applicant.usdot or "", now - 86400) >= 3:
                    print(f"  [queue] SKIP {mga}: USDOT cotizado >=3x en 24h")
                    continue
                self.quote_store.enqueue(
                    submission_id, mga, json.dumps(profile.to_dict()),
                    eff_date, profile.applicant.usdot or "")
                queued.append(mga)
            if not queued:
                # Todos rate-limited: mandar ahora (sin sección RPA) + etiquetar.
                body = analysis["body"].replace(RPA_SECTION_MARKER, "")
                self._send_analysis_now(email_data, analysis["subject"], body,
                                        attachments)
                print("  [queue] Nada encolado (rate-limit); análisis enviado ya")
            else:
                print(f"  [queue] Encolado {submission_id}: {queued} "
                      f"(el correo sale al terminar la cotización)")
        else:
            if self.dry_run:
                print(f"  DRY RUN - Would send analysis to: {analysis_to}")
            else:
                self._send_analysis_now(email_data, analysis["subject"],
                                        analysis["body"], attachments)

        # Step 8: If auto mode, dispatch immediately. If manual, store and wait.
        if self.approval_mode == "auto":
            print(f"\nStep 6: Auto-mode - dispatching to eligible MGAs...")
            self._dispatch_to_mgas(email_data, profile, evaluations, mga_list,
                                   tipo_negocio, commodity, business_name, subject)
        else:
            # Store pending approval
            print(f"\nStep 6: Manual mode - waiting for confirmation reply with '{self.confirmation_keyword}'")
            self._pending_approvals[subject] = {
                'email_data': email_data,
                'profile': profile,
                'evaluations': evaluations,
                'mga_list': mga_list,
                'tipo_negocio': tipo_negocio,
                'commodity': commodity,
                'business_name': business_name,
                'subject': subject,
            }
            print(f"  Stored pending approval for: {subject[:60]}...")

        print(f"{'='*60}\n")

    def _handle_confirmation(self, email_data: Dict):
        """Handle a confirmation reply to dispatch pending MGA emails."""
        subject = email_data.get('subject', '')
        print(f"\n{'='*60}")
        print(f"CONFIRMATION RECEIVED")
        print(f"{'='*60}")
        print(f"Subject: {subject}")

        # Find the matching pending approval
        # The reply subject will be like "Re: [ANALISIS] Submission // ..."
        # We need to match against the original submission subject
        matched_key = None
        for pending_subject in self._pending_approvals:
            if pending_subject in subject:
                matched_key = pending_subject
                break

        if not matched_key:
            print(f"  No pending approval found for this reply. Ignoring.")
            print(f"  Pending keys: {list(self._pending_approvals.keys())[:3]}")
            print(f"{'='*60}\n")
            return

        pending = self._pending_approvals.pop(matched_key)
        print(f"  Found pending approval for: {matched_key[:60]}...")
        print(f"  Dispatching to eligible MGAs...")

        self._dispatch_to_mgas(
            pending['email_data'], pending['profile'], pending['evaluations'],
            pending['mga_list'], pending['tipo_negocio'], pending['commodity'],
            pending['business_name'], pending['subject']
        )
        print(f"{'='*60}\n")

    def _dispatch_to_mgas(self, email_data, profile, evaluations, mga_list,
                          tipo_negocio, commodity, business_name, subject):
        """Send emails to eligible MGAs and upload to Drive."""
        # Determine eligible MGAs
        eligible_mga_names = set(mga['mga'] for mga in mga_list)
        eval_by_name = {ev.mga_name: ev for ev in evaluations}

        for mga in mga_list:
            ev = eval_by_name.get(mga['mga'])
            if ev and not ev.eligible:
                eligible_mga_names.discard(mga['mga'])

        mga_list_eligible = [m for m in mga_list if m['mga'] in eligible_mga_names]
        attachments = email_data.get('attachments', [])
        original_body = extract_quote_body(email_data.get('body', ''))
        email_sender = EmailSender(self.email_address, self.email_password)

        print(f"  Eligible MGAs: {len(mga_list_eligible)}/{len(mga_list)}")

        mgas_contacted = 0

        for mga in mga_list_eligible:
            mga_name = mga['mga']
            # Los MGA-RPA (Progressive, GEICO) los cotiza el QuoteWorker desde la
            # cola — NO se dispatchan por email acá.
            if mga_name.upper() in self.rpa_mgas:
                continue
            print(f"\n  Processing MGA: {mga_name}")

            # Validate documents
            validation = self.attachment_validator.validate_for_mga(attachments, mga_name)
            if not validation.is_valid:
                print(f"    Missing docs: {', '.join(validation.missing_docs)}")
                continue

            # Get MGA email
            mga_email_info = self.mga_email_reader.get_email_for_mga(mga_name)
            if not mga_email_info:
                print(f"    No email configured for MGA: {mga_name}")
                continue

            to_email = mga_email_info['email_to']
            cc_email = mga_email_info.get('email_cc')

            if self.test_email_override:
                print(f"    TEST MODE: {to_email} -> {self.test_email_override}")
                to_email = self.test_email_override
                cc_email = None

            if self.dry_run:
                print(f"    DRY RUN - Would send to: {to_email}")
                mgas_contacted += 1
            else:
                success = email_sender.send_to_mga(
                    to_email=to_email,
                    subject=subject,
                    body=original_body,
                    attachments=validation.matched_docs,
                    cc_email=cc_email
                )
                if success:
                    mgas_contacted += 1
                    print(f"    Email sent to {mga_name}")
                else:
                    print(f"    Failed to send to {mga_name}")

        # Upload to Drive
        if mgas_contacted > 0:
            print(f"\n  Uploading to Google Drive...")
            usdot = profile.applicant.usdot or 'UNKNOWN'
            self.drive_manager.upload_files_for_client(
                business_name=business_name,
                usdot=usdot,
                attachments=attachments
            )

        print(f"\n  SUMMARY: {mgas_contacted}/{len(mga_list)} MGAs contacted")

    def _dispatch_to_progressive(self, profile, subject):
        """Dispatch quote to Progressive via web automation."""
        import re

        # Extract effective date from subject (format: Effective date: MM/DD/YYYY or M/D/YYYY)
        eff_date = None
        match = re.search(r'[Ee]ffective\s+date[:\s]+(\d{1,2}/\d{1,2}/\d{4})', subject)
        if match:
            eff_date = match.group(1)

        print(f"    [Progressive] Starting web automation (effective date: {eff_date or 'unknown'})...")

        try:
            from modules.progressive.client import ProgressiveClient
            result = ProgressiveClient.create_quote(profile, effective_date=eff_date)

            if result.success:
                print(f"    [Progressive] Quote completed! Step reached: {result.step_reached}")
                for w in result.warnings:
                    print(f"    [Progressive] WARN: {w}")
            else:
                print(f"    [Progressive] Failed at step '{result.step_reached}': {result.error}")
                if result.screenshot_path:
                    print(f"    [Progressive] Screenshot: {result.screenshot_path}")
        except Exception as e:
            print(f"    [Progressive] Unexpected error: {e}")

    def _eligible_rpa_mgas(self, evaluations, mga_list) -> set:
        """MGA-RPA habilitados que quedaron elegibles para esta submission."""
        eval_by_name = {ev.mga_name: ev for ev in evaluations}
        out = set()
        for m in mga_list:
            name = m["mga"]
            if name.upper() not in self.rpa_mgas:
                continue
            ev = eval_by_name.get(name)
            if ev is None or ev.eligible:   # sin reglas específicas = elegible para RPA
                out.add(name.upper())
        return out

    @staticmethod
    def _submission_id(email_data: dict, profile) -> str:
        """ID estable: Message-ID (del dict de GmailClient) si existe, si no
        hash(subject+usdot)."""
        msg_id = (email_data.get("message_id") or "").strip()
        if msg_id:
            return msg_id
        usdot = (profile.applicant.usdot or "").strip()
        subject = email_data.get("subject", "")
        return "sub-" + hashlib.sha1(f"{subject}|{usdot}".encode("utf-8")).hexdigest()[:16]

    def _persist_attachments(self, submission_id: str, attachments: list) -> list:
        """Escribe los adjuntos originales a disco y devuelve sus paths."""
        safe = "".join(c if c.isalnum() else "_" for c in submission_id)[:40]
        out_dir = SUBMISSIONS_DIR / safe
        out_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for att in attachments:
            data = att.get("data")
            fname = att.get("filename") or "attachment.pdf"
            if not data:
                continue
            p = out_dir / fname
            p.write_bytes(data)
            paths.append(str(p))
        return paths

    def _effective_date_from_subject(self, subject: str):
        import re
        m = re.search(r'[Ee]ffective\s+date[:\s]+(\d{1,2}/\d{1,2}/\d{4})', subject)
        return self._clamp_effective_date(m.group(1)) if m else None

    @staticmethod
    def _carrier_kind(current_carrier: str) -> str:
        """Clasifica el campo current_carrier de la Blue Quote:
        'real' = nombre de aseguradora (evidencia de establecido),
        'nv'   = sentinel de negocio nuevo (evidencia de new venture),
        'empty'= sin dato (decide el subject)."""
        c = (current_carrier or "").strip().upper()
        if not c or c in {"N/A", "NA", "NONE", "-", "NO"}:
            return "empty"
        if c in {"NEW BUSINESS", "NEW VENTURE", "NEW", "NUEVO"}:
            return "nv"
        return "real"

    @staticmethod
    def _clamp_effective_date(raw: str, today=None):
        """R-088: una fecha efectiva vencida no es cotizable — los portales
        exigen >= hoy (Progressive: 'cannot be less than <hoy>', visto live
        con T&S Logistics 2026-08-06) → se cotiza con HOY y queda en el log.
        Una fecha futura o im-parseable pasa intacta."""
        from datetime import datetime, date
        try:
            parsed = datetime.strptime(raw, "%m/%d/%Y").date()
        except ValueError:
            return raw
        today = today or date.today()
        if parsed >= today:
            return raw
        clamped = today.strftime("%m/%d/%Y")
        print(f"  Effective date {raw} ya venció → se cotiza con hoy "
              f"{clamped} (R-088)")
        return clamped

    def _send_analysis_now(self, email_data: dict, subject: str, body: str,
                           attachments: list) -> None:
        """Envía el análisis como correo NUEVO a analysis_to (Diana durante
        estabilización). Transparente: no toca el correo original."""
        ok = self.gmail.send_threaded(
            to=self.analysis_to,
            subject=subject,
            body=body,
            attachments=attachments,
            is_html=True,
        )
        print(f"  Analysis sent to {self.analysis_to} (ok={ok})")

    def _send_not_found_email(self, email_data, commodity, sender_name, business_name, subject):
        """Send 'not found' email when commodity can't be matched."""
        response = build_email_response(
            mga_data=[],
            commodity=commodity,
            tipo_negocio="UNKNOWN",
            nombre_cliente=sender_name,
            nombre_negocio=business_name,
            original_subject=subject
        )
        if self.dry_run:
            print(f"  DRY RUN - Would send not-found email")
        else:
            ok = self.gmail.send_threaded(
                to=self.analysis_to,
                subject=response['subject'],
                body=response['body'],
                is_html=False,
            )
        print(f"{'='*60}\n")

