# coding: utf-8
"""PDF text extraction with OCR fallback."""

import io
import os
import sys
import shutil
import fitz
import pdfplumber
import pytesseract
from PIL import Image

def _find_tesseract() -> str:
    # 1. PATH上を検索
    found = shutil.which("tesseract")
    if found:
        return found
    # 2. conda環境の Library/bin を確認
    conda_path = os.path.join(sys.prefix, "Library", "bin", "tesseract.exe")
    if os.path.isfile(conda_path):
        return conda_path
    # 3. システムデフォルト
    return r"C:\Program Files\Tesseract-OCR\tesseract.exe"

def _find_tessdata() -> str:
    # conda環境の share/tessdata を優先
    for base in (sys.prefix, os.path.join(sys.prefix, "Library")):
        path = os.path.join(base, "share", "tessdata")
        if os.path.isdir(path):
            return path
    return ""

pytesseract.pytesseract.tesseract_cmd = _find_tesseract()
_tessdata = _find_tessdata()
if _tessdata:
    os.environ.setdefault("TESSDATA_PREFIX", _tessdata)


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


def _ocr_pdf(pdf_path: str, last_n_pages: int = 0) -> str:
    """Render pages at 200 dpi and run Tesseract OCR.
    last_n_pages: OCR対象を末尾Nページに限定（0=全ページ）
    """
    doc = fitz.open(pdf_path)
    pages = list(doc)
    if last_n_pages > 0:
        pages = pages[-last_n_pages:]
    texts = []
    for page in pages:
        mat = fitz.Matrix(200 / 72, 200 / 72)
        pix = page.get_pixmap(matrix=mat)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        texts.append(pytesseract.image_to_string(img, lang="jpn+eng"))
    return "\n".join(texts)


def extract_pdf_text(pdf_path: str, ocr_last_pages: int = 0) -> str:
    """Extract text from PDF. Falls back to OCR for image-based or garbled PDFs.
    ocr_last_pages: OCR時に末尾Nページのみ処理（0=全ページ）
    """
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
        return _ocr_pdf(pdf_path, last_n_pages=ocr_last_pages)
    except Exception:
        return ""
