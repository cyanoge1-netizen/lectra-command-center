# -*- coding: utf-8 -*-
import os

try:
    from PIL import Image, ImageOps
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import pytesseract
    PYTESSERACT_AVAILABLE = True
except ImportError:
    PYTESSERACT_AVAILABLE = False


class OCREngine:
    """Extracts text from a photo (a phone shot of a whiteboard, a
    textbook page, printed handouts, etc.) via Tesseract OCR.

    Requires two things, both external to this repo's requirements.txt:
      1. The `pytesseract` and `Pillow` pip packages.
      2. The Tesseract OCR *binary* installed system-wide:
           Ubuntu/Debian: sudo apt install tesseract-ocr
           macOS:         brew install tesseract
           Windows:       https://github.com/UB-Mannheim/tesseract/wiki
    is_available() lets the GUI detect a missing binary up front and show
    an install hint instead of a raw traceback.
    """

    def is_available(self) -> bool:
        if not (PIL_AVAILABLE and PYTESSERACT_AVAILABLE):
            return False
        try:
            pytesseract.get_tesseract_version()
            return True
        except Exception:
            return False

    def extract_text(self, image_path: str, lang: str = "eng") -> str:
        """Runs OCR on the given image and returns the extracted text.
        Raises FileNotFoundError / RuntimeError with a readable message
        rather than letting a raw Tesseract error surface."""
        if not PIL_AVAILABLE or not PYTESSERACT_AVAILABLE:
            raise RuntimeError(
                "OCR requires the 'pytesseract' and 'Pillow' packages "
                "(pip install pytesseract Pillow)."
            )
        if not image_path or not os.path.exists(image_path):
            raise FileNotFoundError(f"Image not found: {image_path}")

        image = Image.open(image_path)
        # Grayscale + auto-contrast noticeably improves accuracy on phone
        # photos (uneven lighting, glare) versus flatbed scans, without
        # needing a heavier dependency like OpenCV.
        image = ImageOps.exif_transpose(image)  # respect phone photo rotation
        image = image.convert("L")
        image = ImageOps.autocontrast(image)

        try:
            text = pytesseract.image_to_string(image, lang=lang)
        except pytesseract.TesseractNotFoundError:
            raise RuntimeError(
                "Tesseract OCR is not installed on this system. Install it "
                "with 'sudo apt install tesseract-ocr' (Ubuntu/Debian) and "
                "try again."
            )
        return text.strip()
