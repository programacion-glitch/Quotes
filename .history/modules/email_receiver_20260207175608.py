"""
Email Receiver Module

Monitors email inbox and filters messages by subject.
"""

import imaplib
import email
from email.header import decode_header
from typing import List, Dict, Optional, Tuple
import time
from datetime import datetime


class EmailReceiver:
    """Monitors email inbox using IMAP."""
    
    def __init__(
        self,
        email_address: str,
        password: str,
        imap_server: str = "imap.gmail.com",
        imap_port: int = 993
    ):
        """
        Initialize email receiver.
        
        Args:
            email_address: Email address to monitor
            password: Email password or app password
            imap_server: IMAP server address
            imap_port: IMAP port (default 993 for SSL)
        """
        self.email_address = email_address
        self.password = password
        self.imap_server = imap_server
        self.imap_port = imap_port
        self.mail = None
    
    def connect(self):
        """Connect to IMAP server."""
        try:
            self.mail = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            self.mail.login(self.email_address, self.password)
            print(f"✓ Connected to {self.email_address}")
            return True
        except Exception as e:
            print(f"✗ Connection failed: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from IMAP server."""
        if self.mail:
            try:
                self.mail.close()
                self.mail.logout()
                print("✓ Disconnected")
            except:
                pass
    
    def _decode_subject(self, subject_header: str) -> str:
        """Decode email subject."""
        if not subject_header:
            return ""
        
        decoded_parts = decode_header(subject_header)
        subject = ""
        
        for part, encoding in decoded_parts:
            if isinstance(part, bytes):
                subject += part.decode(encoding or 'utf-8', errors='ignore')
            else:
                subject += str(part)
        
        return subject
    
    def _extract_sender(self, from_header: str) -> Tuple[str, str]:
        """
        Extract sender name and email.
        
        Returns:
            Tuple of (name, email)
        """
        # Parse "Name <email@domain.com>" format
        if '<' in from_header and '>' in from_header:
            name = from_header.split('<')[0].strip().strip('"')
            email_addr = from_header.split('<')[1].split('>')[0].strip()
        else:
            name = ""
            email_addr = from_header.strip()
        
        return name, email_addr
    
    def _get_email_body(self, msg) -> str:
        """Extract email body text."""
        body = ""
        
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))
                
                # Get text/plain parts
                if content_type == "text/plain" and "attachment" not in content_disposition:
                    try:
                        body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                        break
                    except:
                        pass
        else:
            try:
                body = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
            except:
                pass
        
        return body
    
    def _get_attachments(self, msg) -> List[Dict[str, any]]:
        """
        Extract attachment information.
        
        Returns:
            List of dicts with filename and data
        """
        attachments = []
        
        if msg.is_multipart():
            for part in msg.walk():
                content_disposition = str(part.get("Content-Disposition"))
                
                if "attachment" in content_disposition:
                    filename = part.get_filename()
                    if filename:
                        data = part.get_payload(decode=True)
                        attachments.append({
                            "filename": filename,
                            "data": data,
                            "content_type": part.get_content_type()
                        })
        
        return attachments
    
    def fetch_unread_emails(self, subject_filter: Optional[str] = None) -> List[Dict]:
        """
        Fetch unread emails, optionally filtered by subject.
        
        Args:
            subject_filter: String that must be in subject (case-insensitive)
            
        Returns:
            List of email dictionaries
        """
        if not self.mail:
            if not self.connect():
                return []
        
        try:
            # Select inbox
            self.mail.select("INBOX")
            
            # Search for unread emails
            status, messages = self.mail.search(None, 'UNSEEN')
            
            if status != 'OK':
                print("No unread messages found")
                return []
            
            email_ids = messages[0].split()
            emails = []
            
            for email_id in email_ids:
                # Fetch email
                status, msg_data = self.mail.fetch(email_id, '(RFC822)')
                
                if status != 'OK':
                    continue
                
                # Parse email
                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)
                
                # Extract subject
                subject = self._decode_subject(msg.get('Subject', ''))
                
                # Apply subject filter
                if subject_filter:
                    if subject_filter.lower() not in subject.lower():
                        continue
                
                # Extract sender
                from_header = msg.get('From', '')
                sender_name, sender_email = self._extract_sender(from_header)
                
                # Extract body
                body = self._get_email_body(msg)
                
                # Extract attachments
                attachments = self._get_attachments(msg)
                
                # Build email dict
                email_dict = {
                    "id": email_id.decode(),
                    "subject": subject,
                    "sender_name": sender_name,
                    "sender_email": sender_email,
                    "from": from_header,
                    "date": msg.get('Date', ''),
                    "body": body,
                    "attachments": attachments,
                    "raw_message": msg
                }
                
                emails.append(email_dict)
            
            return emails
            
        except Exception as e:
            print(f"Error fetching emails: {e}")
            return []
    
    def mark_as_read(self, email_id: str):
        """Mark email as read."""
        try:
            self.mail.store(email_id.encode(), '+FLAGS', '\\Seen')
        except Exception as e:
            print(f"Error marking as read: {e}")
    
    def monitor_inbox(
        self,
        subject_filter: str,
        callback_function,
        check_interval: int = 60,
        max_iterations: Optional[int] = None
    ):
        """
        Monitor inbox continuously.
        
        Args:
            subject_filter: Subject filter string
            callback_function: Function to call for each matching email
            check_interval: Seconds between checks
            max_iterations: Max number of checks (None = infinite)
        """
        iteration = 0
        
        print(f"📧 Monitoring {self.email_address}")
        print(f"🔍 Filter: Subject contains '{subject_filter}'")
        print(f"⏱️  Check interval: {check_interval}s")
        print("-" * 60)
        
        try:
            while True:
                if max_iterations and iteration >= max_iterations:
                    print(f"Reached max iterations ({max_iterations})")
                    break
                
                iteration += 1
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                print(f"[{timestamp}] Checking for new emails... (iteration {iteration})")
                
                # Fetch unread emails
                emails = self.fetch_unread_emails(subject_filter)
                
                if emails:
                    print(f"✓ Found {len(emails)} matching email(s)")
                    
                    for email_data in emails:
                        print(f"\n  Processing: {email_data['subject']}")
                        print(f"  From: {email_data['sender_email']}")
                        
                        # Call callback function
                        try:
                            callback_function(email_data)
                            # Mark as read after processing
                            self.mark_as_read(email_data['id'])
                            print(f"  ✓ Processed successfully")
                        except Exception as e:
                            print(f"  ✗ Error in callback: {e}")
                else:
                    print("  No new matching emails")
                
                # Wait before next check
                if not max_iterations or iteration < max_iterations:
                    time.sleep(check_interval)
        
        except KeyboardInterrupt:
            print("\n\n⚠️  Monitoring stopped by user")
        finally:
            self.disconnect()


# Convenience function
def monitor_email(
    email_address: str,
    password: str,
    subject_filter: str,
    callback_function,
    check_interval: int = 60
):
    """
    Quick function to start monitoring.
    
    Args:
        email_address: Email to monitor
        password: Email password
        subject_filter: Subject filter
        callback_function: Function to process each email
        check_interval: Seconds between checks
    """
    receiver = EmailReceiver(email_address, password)
    receiver.monitor_inbox(subject_filter, callback_function, check_interval)


def extract_quote_body(body: str) -> str:
    """
    Extract the quote portion from email body.
    
    Extracts text from "Good Afternoon" (or "Good Morning", "Hello")
    until "We will be looking forward to hearing from you."
    
    Args:
        body: Full email body text
        
    Returns:
        Extracted quote portion, or original body if markers not found
    """
    import re
    
    if not body:
        return ""
    
    # Define start markers (case-insensitive)
    start_patterns = [
        r"Good\s+Afternoon",
        r"Good\s+Morning",
        r"Hello",
        r"Hi\s+there",
        r"Dear"
    ]
    
    # Define end marker
    end_pattern = r"We\s+will\s+be\s+looking\s+forward\s+to\s+hearing\s+from\s+you\.?"
    
    # Find start position
    start_pos = None
    for pattern in start_patterns:
        match = re.search(pattern, body, re.IGNORECASE)
        if match:
            start_pos = match.start()
            break
    
    # Find end position
    end_match = re.search(end_pattern, body, re.IGNORECASE)
    end_pos = end_match.end() if end_match else None
    
    # Extract content
    if start_pos is not None and end_pos is not None:
        return body[start_pos:end_pos].strip()
    elif start_pos is not None:
        # No end marker found, take from start to end
        return body[start_pos:].strip()
    else:
        # No markers found, return original body
        return body.strip()

