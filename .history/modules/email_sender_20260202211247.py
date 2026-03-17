"""
Email Sender Module

Sends email responses with SMTP.
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from typing import Optional, List
from pathlib import Path


class EmailSender:
    """Sends emails using SMTP."""
    
    def __init__(
        self,
        email_address: str,
        password: str,
        smtp_server: str = "smtp.gmail.com",
        smtp_port: int = 587
    ):
        """
        Initialize email sender.
        
        Args:
            email_address: Sender email address
            password: Email password or app password
            smtp_server: SMTP server address
            smtp_port: SMTP port (default 587 for TLS)
        """
        self.email_address = email_address
        self.password = password
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
    
    def send_email(
        self,
        to_email: str,
        subject: str,
        body: str,
        reply_to_message_id: Optional[str] = None,
        in_reply_to: Optional[str] = None,
        attachments: Optional[List[str]] = None
    ) -> bool:
        """
        Send email.
        
        Args:
            to_email: Recipient email
            subject: Email subject
            body: Email body (plain text)
            reply_to_message_id: Original message ID for threading
            in_reply_to: In-Reply-To header for threading
            attachments: List of file paths to attach
            
        Returns:
            True if sent successfully
        """
        try:
            # Create message
            msg = MIMEMultipart()
            msg['From'] = self.email_address
            msg['To'] = to_email
            msg['Subject'] = subject
            
            # Add threading headers if replying
            if reply_to_message_id:
                msg['In-Reply-To'] = reply_to_message_id
                msg['References'] = reply_to_message_id
            
            if in_reply_to:
                msg['In-Reply-To'] = in_reply_to
            
            # Add body
            msg.attach(MIMEText(body, 'plain', 'utf-8'))
            
            # Add attachments if any
            if attachments:
                for file_path in attachments:
                    self._attach_file(msg, file_path)
            
            # Connect and send
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.email_address, self.password)
                server.send_message(msg)
            
            print(f"✓ Email sent to {to_email}")
            return True
            
        except Exception as e:
            print(f"✗ Failed to send email: {e}")
            return False
    
    def _attach_file(self, msg: MIMEMultipart, file_path: str):
        """Attach file to email message."""
        path = Path(file_path)
        
        if not path.exists():
            print(f"⚠️  Attachment not found: {file_path}")
            return
        
        with open(path, 'rb') as f:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(f.read())
        
        encoders.encode_base64(part)
        part.add_header(
            'Content-Disposition',
            f'attachment; filename= {path.name}'
        )
        
        msg.attach(part)
    
    def reply_to_email(
        self,
        original_email: dict,
        reply_body: str,
        reply_subject: Optional[str] = None
    ) -> bool:
        """
        Reply to an email.
        
        Args:
            original_email: Original email dict (from EmailReceiver)
            reply_body: Reply body text
            reply_subject: Optional custom subject (default: Re: original)
            
        Returns:
            True if sent successfully
        """
        # Get original sender
        to_email = original_email.get('sender_email')
        
        if not to_email:
            print("✗ No sender email found in original message")
            return False
        
        # Build subject
        if not reply_subject:
            original_subject = original_email.get('subject', '')
            if not original_subject.startswith('Re:'):
                reply_subject = f"Re: {original_subject}"
            else:
                reply_subject = original_subject
        
        # Get message ID for threading
        raw_msg = original_email.get('raw_message')
        message_id = raw_msg.get('Message-ID') if raw_msg else None
        
        # Send reply
        return self.send_email(
            to_email=to_email,
            subject=reply_subject,
            body=reply_body,
            reply_to_message_id=message_id,
            in_reply_to=message_id
        )


# Convenience function
def send_reply(
    sender_email: str,
    sender_password: str,
    original_email: dict,
    reply_body: str,
    reply_subject: Optional[str] = None
) -> bool:
    """
    Quick function to send a reply.
    
    Args:
        sender_email: Your email address
        sender_password: Your password
        original_email: Original email dict
        reply_body: Reply text
        reply_subject: Optional custom subject
        
    Returns:
        True if sent successfully
    """
    sender = EmailSender(sender_email, sender_password)
    return sender.reply_to_email(original_email, reply_body, reply_subject)
