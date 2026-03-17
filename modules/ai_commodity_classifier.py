"""
AI Commodity Classifier Module

Uses OpenAI Local Proxy to classify complex commodity strings into predefined business types.
"""

from typing import List, Optional
import openai
from modules.config_manager import get_config

class AICommodityClassifier:
    """Classifies commodities using OpenAI LLM via a local proxy."""
    
    def __init__(self):
        """Initialize the AI classifier with proxy settings."""
        self.config = get_config()
        self.base_url = self.config.openai_base_url
        self.api_key = self.config.openai_api_key
        
        # Initialize OpenAI client pointing to the proxy
        self.client = openai.OpenAI(
            base_url=self.base_url,
            api_key=self.api_key
        )
        
    def classify_commodity(self, commodity_text: str, business_types: List[str]) -> Optional[str]:
        """
        Classifies a given commodity string into one of the allowed business types.
        
        Args:
            commodity_text: Raw commodity string from the PDF (can contain multiple items)
            business_types: List of valid business types (from Excel)
            
        Returns:
            The exact matched business type, or None if classification fails
        """
        if not commodity_text or not commodity_text.strip():
            return None
            
        if not business_types:
            return None
            
        # Format the list of valid business types for the prompt
        types_list = "\n".join([f"- {t}" for t in business_types])
        
        system_prompt = f"""You are an expert underwriter for commercial auto/trucking insurance in the USA.
Your task is to analyze a raw string of commodities extracted from a quote request, and map it to exactly ONE business type from the provided list.

Rules:
1. If the text contains multiple commodities or percentages, determine which one represents the HIGHEST RISK or primary exposure, and categorize it based on that.
2. You must return EXACTLY AND ONLY the name of the business type from the allowed list. No extra text, no periods, no explanations.
3. If the commodity clearly does not match anything or is completely unknown, return an empty string.

Allowed Business Types:
{types_list}
"""

        user_prompt = f"Categorize the following commodity text:\n\n{commodity_text}"
        
        try:
            # We use 'gpt-4o' or 'gpt-4' as placeholder; the proxy determines the actual model.
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.0, # Deterministic response
                max_tokens=50
            )
            
            result = response.choices[0].message.content.strip()
            
            # Additional validation: the result MUST be in the exact list
            # We do a case-insensitive check just in case, but return the exact casing
            result_upper = result.upper()
            for b_type in business_types:
                if result_upper == b_type.upper():
                    return b_type
                    
            print(f"⚠️  AI returned '{result}' which is not in the allowed list.")
            return None
            
        except Exception as e:
            print(f"✗ Failed to classify commodity via AI: {e}")
            return None
