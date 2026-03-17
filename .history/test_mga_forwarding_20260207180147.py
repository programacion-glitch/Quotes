"""
Test script for MGA Email Forwarding (DRY RUN mode)

Simulates the workflow with fake email data to verify the flow works correctly.
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

from workflow_orchestrator import QuoteWorkflowOrchestrator

# Create simulated email data
test_email = {
    'id': 'TEST_001',
    'subject': 'Submission New Venture //TEST TRUCKING LLC // Effective date:02/15/2026//USDOT:1234567',
    'sender_name': 'Test Sender',
    'sender_email': 'test@example.com',
    'from': 'Test Sender <test@example.com>',
    'body': '''
Dear Team,

Good Afternoon,

Please help us quote this new prospect.

*Insured name: TEST TRUCKING LLC
*Business location: Texas
*Commodities: SAND 100%
*Number of trucks: 5

Coverages requested:
*A.L: $1,000,000
*Cargo: $100,000

We will be looking forward to hearing from you.

Best regards,
Test Sender
Insurance Agency
    ''',
    'attachments': [
        {
            'filename': '20260207 BLUE QUOTE TEST TRUCKING.pdf',
            'data': b'fake pdf content for blue quote',
            'content_type': 'application/pdf'
        },
        {
            'filename': 'MVR DRIVER JOHN DOE.pdf',
            'data': b'fake pdf content for mvr',
            'content_type': 'application/pdf'
        },
        {
            'filename': 'CDL LICENSE JOHN DOE.pdf',
            'data': b'fake pdf content for cdl',
            'content_type': 'application/pdf'
        },
        {
            'filename': 'IFTAS REPORT 2025.pdf',
            'data': b'fake pdf content for iftas',
            'content_type': 'application/pdf'
        },
        {
            'filename': 'LOSS RUN 5 YEARS.pdf',
            'data': b'fake pdf content for loss run',
            'content_type': 'application/pdf'
        },
        {
            'filename': 'NEW VENTURE APP GENERAL.pdf',
            'data': b'fake pdf content for app',
            'content_type': 'application/pdf'
        }
    ],
    'raw_message': None
}


def main():
    print("=" * 60)
    print("DRY RUN TEST - MGA Email Forwarding")
    print("=" * 60)
    print(f"DRY_RUN = {os.getenv('DRY_RUN')}")
    print()
    
    # Initialize orchestrator
    orchestrator = QuoteWorkflowOrchestrator()
    
    print(f"dry_run flag = {orchestrator.dry_run}")
    print()
    
    # Process the test email
    orchestrator.process_email(test_email)


if __name__ == '__main__':
    main()
