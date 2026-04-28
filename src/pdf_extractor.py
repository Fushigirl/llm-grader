# coding: utf-8
"""PDF text extraction with OCR fallback."""

import io
import fitz
import pdfplumber
import pytesseract
from PIL import Image

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def _cjk_ratio(text: str) -> float:
    """Return ratio of CJK characters in text."""
    printable = [c for c in text if not c.isspace()]
    if not printable:
        return 0.0
    cjk = sum(
        1 for c in printable
        if "一" <= c <= "鿿"
        or "぀" <= c <= "ヿ"
        or "＀" <= c <= "￯"
    )
    return cjk / len(printable)


def _ocr_pdf(pdf_path: str) -> str:
    """Render each page at 200 dpi and run Tesseract OCR."""
    doc = fitz.open(pdf_path)
    texts = []
    for page in doc:
        mat = fitz.Matrix(200 / 72, 200 / 72)
        pix = page.get_pixmap(matrix=mat)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        texts.append(pytesseract.image_to_string(img, lang="jpn+eng"))
    return "\n".join(texts)


def extract_pdf_text(pdf_path: str) -> str:
    """Extract text from PDF. Falls back to OCR for image-based or garbled PDFs."""
    # 1. pdfplumber
    try:
        with pdfplumber.open(pdf_path) as pdf:
            text = "\n".join(p.extract_text() or "" for p in pdf.pages)
        if _cjk_ratio(text) >= 0.05:
            return text
    except Exception:
        pass

    # 2. PyMuPDF
    try:
        doc = fitz.open(pdf_path)
        text = "\n".join(page.get_text() for page in doc)
        if _cjk_ratio(text) >= 0.05:
            return text
    except Exception:
        pass

    # 3. OCR
    try:
        return _ocr_pdf(pdf_path)
    except Exception:
        return ""
