from pypdf import PdfReader
import sys

path = "20260126 BLUE QUOTE.pdf"
try:
    reader = PdfReader(path)
    fields = reader.get_fields()
    if fields:
        print("--- FORM FIELDS FOUND ---")
        for key, value in fields.items():
            # Value might be a dictionary or object, try to get value
            v = value.get('/V', 'No Value') if isinstance(value, dict) else value
            print(f"{key}: {v}")
    else:
        print("--- NO FORM FIELDS FOUND ---")

    print("\n--- TEXT DUMP ---")
    for i, page in enumerate(reader.pages):
        print(f"Page {i+1}:")
        print(page.extract_text())
        
except Exception as e:
    print(f"Error: {e}")
