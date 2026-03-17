"""Quick test script for PDF extraction"""
from modules.pdf_extractor import BlueQuotePDFExtractor
import json

pdf_path = "BlueQuote/20260108 BLUE QUOTE.pdf"
print(f"Testing PDF: {pdf_path}")
print("=" * 60)

extractor = BlueQuotePDFExtractor(pdf_path)
data = extractor.extract()

# Print key fields
print(f"Business Name: {data.get('applicant_info', {}).get('business_name', 'N/A')}")
print(f"USDOT: {data.get('applicant_info', {}).get('usdot', 'N/A')}")
print(f"Commodities: {data.get('applicant_info', {}).get('commodities', 'N/A')}")
print(f"Drivers: {len(data.get('drivers', []))}")
print(f"Vehicles: {len(data.get('vehicles', []))}")

# Save full output
with open("test_extraction.json", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, default=str, ensure_ascii=False)
    
print("\nFull output saved to: test_extraction.json")
