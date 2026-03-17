import sys
import os

pdf_path = "20260126 BLUE QUOTE.pdf"

def try_extract():
    try:
        from pypdf import PdfReader
        print("Using pypdf")
        return extract_with_reader(PdfReader(pdf_path))
    except ImportError:
        pass
        
    try:
        import PyPDF2
        from PyPDF2 import PdfReader
        print("Using PyPDF2")
        return extract_with_reader(PdfReader(pdf_path))
    except ImportError:
        pass
        
    print("No suitable library found (pypdf, PyPDF2).")
    return None

def extract_with_reader(reader):
    text = []
    for i, page in enumerate(reader.pages):
        page_text = page.extract_text()
        if page_text:
            text.append(f"--- Page {i+1} ---")
            text.append(page_text)
    return "\n".join(text)

if __name__ == "__main__":
    content = try_extract()
    if content:
        print("SUCCESS_EXTRACTION")
        try:
            # Print safely for console
            print(content.encode(sys.stdout.encoding, errors='replace').decode(sys.stdout.encoding))
        except Exception as e:
            print(f"Error printing content: {e}")
            # Fallback
            print(content.encode('utf-8', errors='ignore').decode('utf-8', errors='ignore'))
    else:
        print("FAILED_EXTRACTION")
