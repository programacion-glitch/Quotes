"""
Test script for MGA Email Forwarding - Component Tests (DRY RUN mode)

Tests each component individually without requiring a real PDF.
"""

import os
import sys
from pathlib import Path

# Ensure DRY_RUN is enabled
os.environ['DRY_RUN'] = 'True'

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()


def test_mga_email_reader():
    """Test: Read MGA email from Excel"""
    print("\n" + "="*60)
    print("TEST 1: MGA Email Reader")
    print("="*60)
    
    from modules.mga_email_reader import MGAEmailReader
    
    reader = MGAEmailReader('config/CHECK LIST (2)_ESTANDARIZADO.xlsx')
    
    test_mgas = ['INVO', 'XPT', 'FOREMOST', 'NATIONAL']
    
    for mga in test_mgas:
        email_info = reader.get_email_for_mga(mga)
        if email_info:
            print(f"✓ {mga}: TO={email_info['email_to'][:30]}... CC={email_info.get('email_cc', 'None')[:20] if email_info.get('email_cc') else 'None'}...")
        else:
            print(f"✗ {mga}: No email configured")
    
    print("\nAll MGAs with email:")
    all_mgas = reader.get_all_mgas()
    print(f"  Total: {len(all_mgas)} MGAs")


def test_attachment_validator():
    """Test: Validate attachments for different MGAs"""
    print("\n" + "="*60)
    print("TEST 2: Attachment Validator")
    print("="*60)
    
    from modules.attachment_validator import AttachmentValidator
    
    validator = AttachmentValidator()
    
    # Full set of attachments (for non-INVO MGAs)
    full_attachments = [
        {'filename': 'BLUE QUOTE TEST.pdf', 'data': b'test'},
        {'filename': 'MVR DRIVER.pdf', 'data': b'test'},
        {'filename': 'CDL LICENSE.pdf', 'data': b'test'},
        {'filename': 'IFTAS REPORT.pdf', 'data': b'test'},
        {'filename': 'LOSS RUN 5YRS.pdf', 'data': b'test'},
        {'filename': 'NEW VENTURE APP.pdf', 'data': b'test'},
    ]
    
    # Full set for INVO
    invo_attachments = [
        {'filename': 'BLUE QUOTE TEST.pdf', 'data': b'test'},
        {'filename': 'MVR DRIVER.pdf', 'data': b'test'},
        {'filename': 'CDL LICENSE.pdf', 'data': b'test'},
        {'filename': 'IFTAS REPORT.pdf', 'data': b'test'},
        {'filename': 'LOSS RUN 5YRS.pdf', 'data': b'test'},
        {'filename': 'NEW VENTURE APP INVO.pdf', 'data': b'test'},
    ]
    
    # Missing some docs
    partial_attachments = [
        {'filename': 'BLUE QUOTE TEST.pdf', 'data': b'test'},
        {'filename': 'MVR DRIVER.pdf', 'data': b'test'},
    ]
    
    print("\nTest A: XPT with full attachments")
    result = validator.validate_for_mga(full_attachments, 'XPT')
    print(f"  Valid: {result.is_valid}")
    print(f"  Missing: {result.missing_docs}")
    
    print("\nTest B: INVO with INVO-specific attachments")
    result = validator.validate_for_mga(invo_attachments, 'INVO')
    print(f"  Valid: {result.is_valid}")
    print(f"  Missing: {result.missing_docs}")
    
    print("\nTest C: XPT with INVO attachments (should fail - wrong APP)")
    result = validator.validate_for_mga(invo_attachments, 'XPT')
    print(f"  Valid: {result.is_valid}")
    print(f"  Missing: {result.missing_docs}")
    
    print("\nTest D: Partial attachments")
    result = validator.validate_for_mga(partial_attachments, 'XPT')
    print(f"  Valid: {result.is_valid}")
    print(f"  Missing: {result.missing_docs}")


def test_body_extractor():
    """Test: Extract quote body from email"""
    print("\n" + "="*60)
    print("TEST 3: Email Body Extractor")
    print("="*60)
    
    from modules.email_receiver import extract_quote_body
    
    test_body = """
From: John Doe
To: quotes@insurance.com
Date: 2026-02-07

Good Afternoon,

Please help us quote this new prospect.

*Insured name: TEST TRUCKING LLC
*Business location: Texas
*Commodities: SAND 100%

Coverages:
*A.L: $1,000,000

We will be looking forward to hearing from you.

Best regards,
John Doe
Test Insurance Agency
Tel: 555-1234
"""
    
    extracted = extract_quote_body(test_body)
    print("Extracted body:")
    print("-" * 40)
    print(extracted)
    print("-" * 40)


def test_dry_run_flag():
    """Test: Verify DRY_RUN flag is read correctly"""
    print("\n" + "="*60)
    print("TEST 4: DRY_RUN Flag")
    print("="*60)
    
    from workflow_orchestrator import QuoteWorkflowOrchestrator
    
    orchestrator = QuoteWorkflowOrchestrator()
    print(f"  DRY_RUN env var: {os.getenv('DRY_RUN')}")
    print(f"  orchestrator.dry_run: {orchestrator.dry_run}")
    
    if orchestrator.dry_run:
        print("  ✓ DRY RUN mode is ENABLED - No real emails will be sent")
    else:
        print("  ⚠️  DRY RUN mode is DISABLED - Real emails WILL be sent!")


def main():
    print("="*60)
    print("MGA EMAIL FORWARDING - COMPONENT TESTS")
    print("="*60)
    
    test_mga_email_reader()
    test_attachment_validator()
    test_body_extractor()
    test_dry_run_flag()
    
    print("\n" + "="*60)
    print("ALL TESTS COMPLETE")
    print("="*60)


if __name__ == '__main__':
    main()
