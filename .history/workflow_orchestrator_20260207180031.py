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
        
        # Step 1: Find PDF attachment - prioritize BLUE QUOTE
        attachments = email_data.get('attachments', [])
        pdf_attachment = None
        
        # First pass: Look for "BLUE QUOTE" in filename
        for att in attachments:
            filename = att['filename'].upper()
            if filename.endswith('.PDF') and 'BLUE QUOTE' in filename:
                pdf_attachment = att
                print(f"✓ Found BLUE QUOTE PDF: {att['filename']}")
                break
        
        # Second pass: If no BLUE QUOTE found, take any PDF
        if not pdf_attachment:
            for att in attachments:
                if att['filename'].lower().endswith('.pdf'):
                    pdf_attachment = att
                    print(f"⚠️  BLUE QUOTE not found, using: {att['filename']}")
                    break
        
        # Validate PDF was found
        if not pdf_attachment:
            print("✗ No PDF attachment found - skipping email")
            return
        
        # Step 2: Save PDF temporarily and extract data
        try:
            # Save to temp file
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
                tmp_file.write(pdf_attachment['data'])
                tmp_pdf_path = tmp_file.name
            
            print(f"Step 1: Extracting data from PDF...")
            extractor = BlueQuotePDFExtractor(tmp_pdf_path)
            extracted_data = extractor.extract()
            
            # Get commodity and business name with fallbacks
            commodity = extracted_data.get('applicant_info', {}).get('commodities') or ''
            business_name = extracted_data.get('applicant_info', {}).get('business_name') or 'su empresa'
            
            print(f"  ✓ Commodity: {commodity or 'None'}")
            print(f"  ✓ Business: {business_name}")
            
            # Clean up temp file
            Path(tmp_pdf_path).unlink()
            
        except Exception as e:
            print(f"✗ Error extracting PDF: {e}")
            return
        
        # Handle empty/None commodity
        if not commodity:
            print("⚠️  No commodity found in PDF - sending not found email")
            commodity = "N/A"
            tipo_negocio = None
        else:
            # Step 3: Map commodity to business type
            print(f"\nStep 2: Mapping commodity to business type...")
            tipo_negocio = self.mapper.map_commodity_to_type(commodity)

        
        if not tipo_negocio:
            print(f"  ⚠️  No match found for commodity: {commodity}")
            # Still send "not found" email
            response = build_email_response(
                mga_data=[],
                commodity=commodity,
                tipo_negocio="UNKNOWN",
                nombre_cliente=sender_name,
                nombre_negocio=business_name,
                original_subject=subject
            )
        else:
            print(f"  ✓ Matched: {tipo_negocio}")
            
            # Step 4: Get MGAs
            print(f"\nStep 3: Finding MGAs...")
            mga_list = self.mga_reader.get_mga_by_business_type(tipo_negocio)
            
            print(f"  ✓ Found {len(mga_list)} MGA(s)")
            for mga in mga_list:
                print(f"    - {mga['mga']}")
            
            # Step 5: Validate documents and send to MGAs
            print(f"\nStep 4: Validating documents and sending to MGAs...")
            email_sender = EmailSender(self.email_address, self.email_password)
            
            # Extract the quote body from original email
            original_body = extract_quote_body(email_data.get('body', ''))
            
            mgas_contacted = 0
            mgas_failed = []
            
            for mga in mga_list:
                mga_name = mga['mga']
                print(f"\n  Processing MGA: {mga_name}")
                
                # Validate documents for this MGA
                validation = self.attachment_validator.validate_for_mga(attachments, mga_name)
                
                if not validation.is_valid:
                    print(f"    ✗ Missing documents: {', '.join(validation.missing_docs)}")
                    mgas_failed.append({'mga': mga_name, 'missing': validation.missing_docs})
                    continue
                
                print(f"    ✓ All documents valid")
                
                # Get MGA email address
                mga_email_info = self.mga_email_reader.get_email_for_mga(mga_name)
                
                if not mga_email_info:
                    print(f"    ✗ No email configured for MGA: {mga_name}")
                    mgas_failed.append({'mga': mga_name, 'missing': ['EMAIL NOT CONFIGURED']})
                    continue
                
                to_email = mga_email_info['email_to']
                cc_email = mga_email_info.get('email_cc')
                
                # Override for testing
                if self.test_email_override:
                    print(f"    🧪 TEST MODE: Would send to {self.test_email_override} instead of {to_email}")
                    to_email = self.test_email_override
                    cc_email = None
                
                # DRY RUN: Simulate sending
                if self.dry_run:
                    print(f"    📋 DRY RUN - Would send email:")
                    print(f"       TO: {to_email}")
                    if cc_email:
                        print(f"       CC: {cc_email}")
                    print(f"       Subject: {subject}")
                    print(f"       Attachments: {list(validation.matched_docs.keys())}")
                    print(f"       Body: {original_body[:100]}...")
                    mgas_contacted += 1
                    print(f"    ✓ [SIMULATED] Email to {mga_name}")
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
                        print(f"    ✓ Email sent to {mga_name}")
                    else:
                        mgas_failed.append({'mga': mga_name, 'missing': ['SEND FAILED']})
            
            # Summary
            print(f"\n{'='*60}")
            print(f"SUMMARY: {mgas_contacted}/{len(mga_list)} MGAs contacted")
            
            # If no MGAs were contacted, send fallback email
            if mgas_contacted == 0:
                print(f"\n⚠️ No MGAs received email - sending summary to fallback...")
                response = build_email_response(
                    mga_data=mga_list,
                    commodity=commodity,
                    tipo_negocio=tipo_negocio,
                    nombre_cliente=sender_name,
                    nombre_negocio=business_name,
                    original_subject=subject
                )
                
                recipient_email = self.test_email_override or email_data.get('sender_email')
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
            print(f"🧪 TEST MODE: Sending to {self.test_email_override} instead of {recipient_email}")
            recipient_email = self.test_email_override
        
        success = email_sender.send_email(
            to_email=recipient_email,
            subject=response['subject'],
            body=response['body']
        )
        
        if success:
            print(f"✓✓✓ WORKFLOW COMPLETE - Summary email sent!")
        else:
            print(f"✗ Failed to send email")
        
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
