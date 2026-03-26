"""
Workflow Orchestrator

Coordinates the complete email auto-response workflow.
"""

import sys
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
        
        # Testing override: send all emails to this address instead of original sender
        self.test_email_override = self.config.get("email.test_email_override")
        
        # Dry run mode: simulate without sending actual emails
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
    
    def process_email(self, email_data: Dict):
        """
        Process a single email with quote PDF.

        Args:
            email_data: Email dict from EmailReceiver
        """
        print(f"\n{'='*60}")
        print(f"PROCESSING EMAIL")
        print(f"{'='*60}")

        subject = email_data.get('subject', '')
        sender = email_data.get('sender_email', '')
        sender_name = email_data.get('sender_name', 'Cliente')

        print(f"From: {sender_name} <{sender}>")
        print(f"Subject: {subject}")

        # Step 1: Get all attachments
        attachments = email_data.get('attachments', [])

        if not attachments:
            print("No attachments found - skipping email")
            return

        # Step 2: Extract structured data from all attachments via DocumentAIExtractor
        print(f"\nStep 1: Extracting data from all attachments ({len(attachments)} file(s))...")
        try:
            profile = self.document_extractor.extract_all(attachments)
        except Exception as e:
            print(f"  Error during document extraction: {e}")
            return

        # Step 3: Check extraction confidence — halt if low confidence and configured to do so
        confidence = profile.extraction_confidence.overall if profile.extraction_confidence else "unknown"
        print(f"  Extraction confidence: {confidence}")

        if confidence == "low" and self.halt_on_low_confidence:
            flags = profile.extraction_confidence.flags if profile.extraction_confidence else []
            flag_summary = ", ".join(f.field for f in flags) if flags else "unknown fields"
            print(f"  Low confidence on: {flag_summary} — halting processing for manual review")
            return

        # Step 4: Get commodity and business name from profile
        commodity = profile.commodity or ''
        business_name = profile.applicant.business_name or 'su empresa'

        print(f"  Commodity: {commodity or 'None'}")
        print(f"  Business: {business_name}")

        # Step 5: Map commodity to business type
        if not commodity:
            print("  No commodity found in documents - sending not found email")
            commodity = "N/A"
            tipo_negocio = None
        else:
            print(f"\nStep 2: Mapping commodity to business type...")
            tipo_negocio = self.mapper.map_commodity_to_type(commodity)

        if not tipo_negocio:
            print(f"  No match found for commodity: {commodity}")
            # Send "not found" email
            response = build_email_response(
                mga_data=[],
                commodity=commodity,
                tipo_negocio="UNKNOWN",
                nombre_cliente=sender_name,
                nombre_negocio=business_name,
                original_subject=subject
            )
        else:
            print(f"  Matched: {tipo_negocio}")

            # Step 6: Get candidate MGAs
            print(f"\nStep 3: Finding MGAs...")
            mga_list = self.mga_reader.get_mga_by_business_type(tipo_negocio)

            print(f"  Found {len(mga_list)} MGA(s)")
            for mga in mga_list:
                print(f"    - {mga['mga']}")

            # Step 7: Apply rule engine to filter eligible MGAs
            eligible_mga_names = set(mga['mga'] for mga in mga_list)
            ineligible_log = []  # List of (mga_name, failed_rules, warnings)

            if self.rule_engine_enabled and mga_list:
                print(f"\nStep 4: Evaluating MGAs against rules...")
                try:
                    evaluations = self.rule_engine.evaluate(profile, tipo_negocio)
                    eval_by_name = {ev.mga_name: ev for ev in evaluations}

                    for mga in mga_list:
                        mga_name = mga['mga']
                        ev = eval_by_name.get(mga_name)
                        if ev is None:
                            # No rule row found — allow by default (backwards-compatible)
                            print(f"    {mga_name}: no rules defined — allowed")
                            continue
                        if ev.eligible:
                            print(f"    {mga_name}: ELIGIBLE ({len(ev.passed_rules)} rules passed)")
                            if ev.warnings:
                                for w in ev.warnings:
                                    print(f"      Warning: {w}")
                        else:
                            print(f"    {mga_name}: INELIGIBLE")
                            for fr in ev.failed_rules:
                                print(f"      Failed rule [{fr.rule}]: {fr.reason}")
                            eligible_mga_names.discard(mga_name)
                            ineligible_log.append({
                                'mga': mga_name,
                                'failed_rules': [fr.reason for fr in ev.failed_rules],
                                'warnings': ev.warnings,
                            })
                except Exception as e:
                    print(f"  Rule engine error (skipping filter): {e}")

            # Step 8: Filter mga_list to only eligible entries
            mga_list_eligible = [mga for mga in mga_list if mga['mga'] in eligible_mga_names]

            print(f"\nStep 5: Validating documents and sending to MGAs...")
            print(f"  Eligible MGAs: {len(mga_list_eligible)}/{len(mga_list)}")

            email_sender = EmailSender(self.email_address, self.email_password)

            # Extract the quote body from original email
            original_body = extract_quote_body(email_data.get('body', ''))

            mgas_contacted = 0
            mgas_failed = []

            for mga in mga_list_eligible:
                mga_name = mga['mga']
                print(f"\n  Processing MGA: {mga_name}")

                # Validate documents for this MGA
                validation = self.attachment_validator.validate_for_mga(attachments, mga_name)

                if not validation.is_valid:
                    print(f"    Missing documents: {', '.join(validation.missing_docs)}")
                    mgas_failed.append({'mga': mga_name, 'missing': validation.missing_docs})
                    continue

                print(f"    All documents valid")

                # Get MGA email address
                mga_email_info = self.mga_email_reader.get_email_for_mga(mga_name)

                if not mga_email_info:
                    print(f"    No email configured for MGA: {mga_name}")
                    mgas_failed.append({'mga': mga_name, 'missing': ['EMAIL NOT CONFIGURED']})
                    continue

                to_email = mga_email_info['email_to']
                cc_email = mga_email_info.get('email_cc')

                # Override for testing
                if self.test_email_override:
                    print(f"    TEST MODE: Would send to {self.test_email_override} instead of {to_email}")
                    to_email = self.test_email_override
                    cc_email = None

                # DRY RUN: Simulate sending
                if self.dry_run:
                    print(f"    DRY RUN - Would send email:")
                    print(f"       TO: {to_email}")
                    if cc_email:
                        print(f"       CC: {cc_email}")
                    print(f"       Subject: {subject}")
                    print(f"       Attachments: {list(validation.matched_docs.keys())}")
                    print(f"       Body: {original_body[:100]}...")
                    mgas_contacted += 1
                    print(f"    [SIMULATED] Email to {mga_name}")
                else:
                    # Send email to MGA
                    success = email_sender.send_to_mga(
                        to_email=to_email,
                        subject=subject,  # Original subject
                        body=original_body,
                        attachments=validation.matched_docs,
                        cc_email=cc_email
                    )

                    if success:
                        mgas_contacted += 1
                        print(f"    Email sent to {mga_name}")
                    else:
                        mgas_failed.append({'mga': mga_name, 'missing': ['SEND FAILED']})

            # Step 9: Log ineligible MGAs
            if ineligible_log:
                print(f"\n  Ineligible MGAs (skipped by rule engine):")
                for entry in ineligible_log:
                    print(f"    - {entry['mga']}: {'; '.join(entry['failed_rules'])}")
                    if entry['warnings']:
                        print(f"      Warnings: {'; '.join(entry['warnings'])}")

            # Step 10: Upload to Drive if at least one MGA was contacted
            if mgas_contacted > 0:
                print(f"\nStep 6: Uploading documents to Google Drive...")
                usdot = profile.applicant.usdot or 'UNKNOWN'

                # We want to ACTUALLY upload to drive even in DRY_RUN to test it!
                drive_success = self.drive_manager.upload_files_for_client(
                    business_name=business_name,
                    usdot=usdot,
                    attachments=attachments
                )
                if drive_success:
                    print(f"    Documents successfully uploaded to Drive.")
                else:
                    print(f"    Some or all documents failed to upload to Drive.")

            # Summary
            print(f"\n{'='*60}")
            print(f"SUMMARY: {mgas_contacted}/{len(mga_list)} MGAs contacted")

            # If no MGAs were contacted, send fallback email
            if mgas_contacted == 0:
                print(f"\nNo MGAs received email - sending summary to fallback...")
                response = build_email_response(
                    mga_data=mga_list,
                    commodity=commodity,
                    tipo_negocio=tipo_negocio,
                    nombre_cliente=sender_name,
                    nombre_negocio=business_name,
                    original_subject=subject
                )

                recipient_email = self.test_email_override or email_data.get('sender_email')

                if self.dry_run:
                    print(f"    DRY RUN - Would send fallback email to: {recipient_email}")
                else:
                    email_sender.send_email(
                        to_email=recipient_email,
                        subject=response['subject'],
                        body=response['body']
                    )

            print(f"{'='*60}\n")
            return

        # Fallback: Send summary email if no tipo_negocio matched
        print(f"\nStep 5: Sending summary email...")
        email_sender = EmailSender(self.email_address, self.email_password)

        recipient_email = email_data.get('sender_email')
        if self.test_email_override:
            print(f"TEST MODE: Sending to {self.test_email_override} instead of {recipient_email}")
            recipient_email = self.test_email_override

        if self.dry_run:
            print(f"DRY RUN - Would send summary email to: {recipient_email}")
            print(f"WORKFLOW COMPLETE (DRY RUN)")
        else:
            success = email_sender.send_email(
                to_email=recipient_email,
                subject=response['subject'],
                body=response['body']
            )

            if success:
                print(f"WORKFLOW COMPLETE - Summary email sent!")
            else:
                print(f"Failed to send email")

        print(f"{'='*60}\n")
    
    def start_monitoring(self, check_interval: int = 60):
        """
        Start monitoring inbox continuously.
        
        Args:
            check_interval: Seconds between email checks
        """
        print(f"\n{'='*60}")
        print(f"H2O QUOTE RPA - AUTO-RESPONSE BOT")
        print(f"{'='*60}")
        print(f"Email: {self.email_address}")
        print(f"Filter: '{self.subject_filter}'")
        print(f"Check interval: {check_interval}s")
        print(f"{'='*60}\n")
        
        # Create receiver
        receiver = EmailReceiver(
            self.email_address,
            self.email_password
        )
        
        # Start monitoring with callback
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
