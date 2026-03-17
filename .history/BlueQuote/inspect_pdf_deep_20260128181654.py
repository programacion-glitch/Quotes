import pdfplumber
import sys

path = "20260126 BLUE QUOTE.pdf"

print(f"Inspecting {path}...")
try:
    with pdfplumber.open(path) as pdf:
        page = pdf.pages[0]
        
        # Check for annotations
        if page.annots:
            print(f"Found {len(page.annots)} annotations:")
            for a in page.annots:
                print(f" - {a.get('data', {}).get('T')} : {a.get('data', {}).get('V')}")
        else:
            print("No annotations found.")

        # Check for images
        if page.images:
            print(f"Found {len(page.images)} images.")
            for img in page.images:
                print(f" - Image at {img['x0']},{img['top']} size {img['width']}x{img['height']}")
        else:
            print("No images found.")

        # Text extraction with layout
        print("\n--- Text with layout ---")
        print(page.extract_text(layout=True))
        
        # Word extraction to see positions
        print("\n--- First 20 Words ---")
        words = page.extract_words()
        for w in words[:20]:
            print(f"'{w['text']}' at {w['x0']:.1f}, {w['top']:.1f}")

except Exception as e:
    print(f"Error: {e}")
