"""
Commodity Matcher Module

Performs fuzzy matching to identify business type from commodity string.
Uses difflib for fuzzy string matching without external dependencies.
"""

import re
from difflib import SequenceMatcher
from typing import List, Tuple, Optional


class CommodityMatcher:
    """Fuzzy matcher for commodity to business type classification."""
    
    def __init__(self, business_types: List[str], threshold: float = 60.0):
        """
        Initialize the matcher.
        
        Args:
            business_types: List of valid business types from Excel
            threshold: Minimum similarity score (0-100) for a valid match
        """
        self.business_types = business_types
        self.threshold = threshold
        
    @staticmethod
    def normalize_commodity(commodity: str) -> str:
        """
        Normalize commodity string for matching.
        
        Removes:
        - Percentages (e.g., "100%")
        - Extra whitespace
        - Special characters (keeping only alphanumeric, spaces, &, /)
        
        Args:
            commodity: Raw commodity string
            
        Returns:
            Normalized commodity string
        """
        if not commodity:
            return ""
        
        # Convert to uppercase
        text = commodity.upper()
        
        # Remove percentages (e.g., "100%", "50%")
        text = re.sub(r'\d+%', '', text)
        
        # Keep only letters, numbers, spaces, &, /, and commas
        text = re.sub(r'[^A-Z0-9\s&/,]', '', text)
        
        # Remove extra whitespace
        text = ' '.join(text.split())
        
        return text.strip()
    
    def calculate_similarity(self, str1: str, str2: str) -> float:
        """
        Calculate similarity score between two strings.
        
        Uses SequenceMatcher for ratio-based comparison.
        
        Args:
            str1: First string
            str2: Second string
            
        Returns:
            Similarity score (0-100)
        """
        norm1 = self.normalize_commodity(str1)
        norm2 = self.normalize_commodity(str2)
        
        # Basic SequenceMatcher comparison
        ratio = SequenceMatcher(None, norm1, norm2).ratio()
        
        # Bonus for substring matches (e.g., "SAND & GRAVEL" in "DIRT, SAND & GRAVEL")
        if norm1 in norm2 or norm2 in norm1:
            ratio = min(ratio + 0.15, 1.0)  # Boost by 15%, cap at 100%
        
        return ratio * 100
    
    def find_best_match(
        self, 
        commodity: str, 
        top_n: int = 3
    ) -> Optional[Tuple[str, float]]:
        """
        Find the best matching business type for a commodity.
        
        Args:
            commodity: Commodity string from PDF
            top_n: Number of top matches to consider (for debugging)
            
        Returns:
            Tuple of (matched_type, score) or None if no match above threshold
        """
        if not commodity or not self.business_types:
            return None
        
        # Calculate similarity for all business types
        matches = []
        for business_type in self.business_types:
            score = self.calculate_similarity(commodity, business_type)
            matches.append((business_type, score))
        
        # Sort by score descending
        matches.sort(key=lambda x: x[1], reverse=True)
        
        # Return best match if above threshold
        if matches and matches[0][1] >= self.threshold:
            return matches[0]
        
        return None
    
    def get_top_matches(
        self, 
        commodity: str, 
        n: int = 5
    ) -> List[Tuple[str, float]]:
        """
        Get top N matches for debugging/inspection.
        
        Args:
            commodity: Commodity string
            n: Number of top matches to return
            
        Returns:
            List of (business_type, score) tuples, sorted by score
        """
        matches = []
        for business_type in self.business_types:
            score = self.calculate_similarity(commodity, business_type)
            matches.append((business_type, score))
        
        matches.sort(key=lambda x: x[1], reverse=True)
        return matches[:n]


# Convenience function for simple use cases
def find_best_match(
    commodity: str,
    business_types: List[str],
    threshold: float = 60.0
) -> Optional[Tuple[str, float]]:
    """
    Find best matching business type (convenience function).
    
    Args:
        commodity: Commodity string from PDF
        business_types: List of valid business types
        threshold: Minimum similarity score (0-100)
        
    Returns:
        Tuple of (matched_type, score) or None
    """
    matcher = CommodityMatcher(business_types, threshold)
    return matcher.find_best_match(commodity)
