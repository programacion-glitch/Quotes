import pdfplumber
import sys

path = "20260126 BLUE QUOTE.pdf"
output_file = "extracted_content.txt"

print(f"Opening {path}...")
try:
    with pdfplumber.open(path) as pdf:
        full_text = ""
        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            if text:
                full_text += f"--- PAGE {i+1} ---\n{text}\n"
            else:
                full_text += f"--- PAGE {i+1} (No text found) ---\n"
                
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(full_text)
    print(f"Successfully wrote to {output_file}")
    
except Exception as e:
    print(f"Error: {e}")
    with open("error_log.txt", "w") as f:
        f.write(str(e))
