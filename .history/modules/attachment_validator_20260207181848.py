"""
Attachment Validator Module

Validates that email attachments contain all required documents for MGA submission.
"""

import re
from typing import List, Dict, Optional
from dataclasses import dataclass


@dataclass
class ValidationResult:
    """Result of attachment validation."""
    is_valid: bool
    missing_docs: List[str]
    matched_docs: Dict[str, dict]  # doc_type -> attachment data


class AttachmentValidator:
    """Validates email attachments for MGA submission requirements."""
    
    # Base required documents (for all MGAs)
    BASE_REQUIRED_DOCS = [
        "BLUE QUOTE",
        "MVR",
        "CDL",
        "IFTA",
        "LOSS RUN"
    ]
    
    # Special APP document names
    APP_GENERAL = "NEW VENTURE APP"
    APP_INVO = "NEW VENTURE APP INVO"
    
    def __init__(self):
        """Initialize validator."""
        pass
    
    def _normalize_filename(self, filename: str) -> str:
        """
        Normalize filename for matching.
        
        Removes dates, extra spaces, and converts to uppercase.
        """
        # Convert to uppercase
        normalized = filename.upper()
        
        # Remove common date patterns (YYYYMMDD, MM-DD-YYYY, etc.)
        normalized = re.sub(r'\d{8}', '', normalized)
        normalized = re.sub(r'\d{2}[-/]\d{2}[-/]\d{4}', '', normalized)
        normalized = re.sub(r'\d{4}[-/]\d{2}[-/]\d{2}', '', normalized)
        
        # Remove extra spaces
        normalized = ' '.join(normalized.split())
        
        return normalized
    
    def _matches_document(self, filename: str, doc_type: str) -> bool:
        """
        Check if filename matches a document type.
        
        Args:
            filename: Attachment filename
            doc_type: Document type to match (e.g., "BLUE QUOTE", "MVR")
            
        Returns:
            True if filename contains the document type pattern
        """
        normalized = self._normalize_filename(filename)
        doc_pattern = doc_type.upper()
        
        return doc_pattern in normalized
    
    def _matches_app_invo(self, filename: str) -> bool:
        """Check if filename matches NEW VENTURE APP INVO."""
        normalized = self._normalize_filename(filename)
        return "NEW VENTURE APP INVO" in normalized or "INVO" in normalized and "NEW VENTURE" in normalized
    
    def _matches_app_general(self, filename: str) -> bool:
        """
        Check if filename matches NEW VENTURE APP (but NOT INVO).
        """
        normalized = self._normalize_filename(filename)
        
        # Must contain NEW VENTURE APP but NOT INVO
        has_app = "NEW VENTURE APP" in normalized
        has_invo = "INVO" in normalized
        
        return has_app and not has_invo
    
    def validate_for_mga(
        self, 
        attachments: List[dict], 
        mga_name: str
    ) -> ValidationResult:
        """
        Validate attachments for a specific MGA.
        
        Args:
            attachments: List of attachment dicts with 'filename' and 'data' keys
            mga_name: MGA name (used to determine APP type)
            
        Returns:
            ValidationResult with is_valid, missing_docs, and matched_docs
        """
        matched_docs = {}
        missing_docs = []
        
        # Check base required documents
        for doc_type in self.BASE_REQUIRED_DOCS:
            found = False
            for att in attachments:
                if self._matches_document(att['filename'], doc_type):
                    matched_docs[doc_type] = att
                    found = True
                    break
            
            if not found:
                missing_docs.append(doc_type)
        
        # Check APP document based on MGA
        mga_upper = mga_name.strip().upper()
        
        if mga_upper == "INVO":
            # INVO needs NEW VENTURE APP INVO
            found_app = False
            for att in attachments:
                if self._matches_app_invo(att['filename']):
                    matched_docs[self.APP_INVO] = att
                    found_app = True
                    break
            
            if not found_app:
                missing_docs.append(self.APP_INVO)
        else:
            # All other MGAs need NEW VENTURE APP (not INVO)
            found_app = False
            for att in attachments:
                if self._matches_app_general(att['filename']):
                    matched_docs[self.APP_GENERAL] = att
                    found_app = True
                    break
            
            if not found_app:
                missing_docs.append(self.APP_GENERAL)
        
        return ValidationResult(
            is_valid=len(missing_docs) == 0,
            missing_docs=missing_docs,
            matched_docs=matched_docs
        )
    
    def get_all_matched_attachments(
        self, 
        attachments: List[dict]
    ) -> Dict[str, dict]:
        """
        Get all matched documents from attachments (ignoring MGA-specific rules).
        
        Useful for debugging which documents were found.
        """
        matched = {}
        
        # Check all base docs
        for doc_type in self.BASE_REQUIRED_DOCS:
            for att in attachments:
                if self._matches_document(att['filename'], doc_type):
                    matched[doc_type] = att
                    break
        
        # Check both APP types
        for att in attachments:
            if self._matches_app_invo(att['filename']):
                matched[self.APP_INVO] = att
            elif self._matches_app_general(att['filename']):
                matched[self.APP_GENERAL] = att
        
        return matched


# Convenience function
def validate_attachments(
    attachments: List[dict], 
    mga_name: str
) -> ValidationResult:
    """
    Quick function to validate attachments for an MGA.
    
    Args:
        attachments: List of attachment dicts
        mga_name: MGA name
        
    Returns:
        ValidationResult
    """
    validator = AttachmentValidator()
    return validator.validate_for_mga(attachments, mga_name)
