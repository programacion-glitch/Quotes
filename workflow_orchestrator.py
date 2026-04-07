"""
Workflow Orchestrator

Coordinates the complete email auto-response workflow.
"""

import sys
import json
from pathlib import Path
from typing import Dict, List, Optional
import tempfile

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.email_receiver import EmailReceiver, extract_quote_body
from modules.email_sender import EmailSender
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

        # Pending approvals: stores data needed to dispatch after confirmation
        # Key: original subject, Value: dict with all data needed
        self._pending_approvals = {}

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
        if "new venture" in subject.lower():
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

        # Step 7: Send analysis email
        print(f"\nStep 5: Sending analysis summary...")
        analysis = build_analysis_email(
            profile=profile,
            commodity=commodity,
            tipo_negocio=tipo_negocio,
            evaluations=evaluations,
            mga_list=mga_list,
            original_subject=subject,
            confirmation_keyword=self.confirmation_keyword,
        )

        summary_to = self.test_email_override or self.summary_email
        email_sender = EmailSender(self.email_address, self.email_password)

        if self.dry_run:
            print(f"  DRY RUN - Would send analysis to: {summary_to}")
            print(f"  Subject: {analysis['subject']}")
        else:
            success = email_sender.send_email(
                to_email=summary_to,
                subject=analysis['subject'],
                body=analysis['body'],
                is_html=analysis.get('is_html', False),
                attachments=attachments,
            )
            if success:
                print(f"  Analysis sent to {summary_to}")
            else:
                print(f"  Failed to send analysis email")

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
        email_sender = EmailSender(self.email_address, self.email_password)
        recipient = self.test_email_override or email_data.get('sender_email')

        if self.dry_run:
            print(f"  DRY RUN - Would send not-found email to: {recipient}")
        else:
            email_sender.send_email(
                to_email=recipient,
                subject=response['subject'],
                body=response['body']
            )
        print(f"{'='*60}\n")

    def start_monitoring(self, check_interval: int = 60):
        """Start monitoring inbox continuously."""
        print(f"\n{'='*60}")
        print(f"H2O QUOTE RPA - AUTO-RESPONSE BOT")
        print(f"{'='*60}")
        print(f"Email: {self.email_address}")
        print(f"Filter: '{self.subject_filter}'")
        print(f"Approval mode: {self.approval_mode}")
        print(f"DRY RUN: {self.dry_run}")
        print(f"Check interval: {check_interval}s")
        print(f"{'='*60}\n")

        receiver = EmailReceiver(
            self.email_address,
            self.email_password
        )

        receiver.monitor_inbox(
            subject_filter=self.subject_filter,
            callback_function=self.process_email,
            check_interval=check_interval
        )


def main():
    """Main entry point."""
    orchestrator = QuoteWorkflowOrchestrator()
    orchestrator.start_monitoring(check_interval=60)


if __name__ == "__main__":
    main()
