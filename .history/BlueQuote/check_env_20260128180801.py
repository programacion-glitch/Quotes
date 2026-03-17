import sys
try:
    import pypdf
    print("pypdf: installed")
except ImportError:
    print("pypdf: missing")

try:
    import PyPDF2
    print("PyPDF2: installed")
except ImportError:
    print("PyPDF2: missing")

try:
    import pdfplumber
    print("pdfplumber: installed")
except ImportError:
    print("pdfplumber: missing")

print(f"Python: {sys.version}")
