import logging
import re
from pathlib import Path
from typing import Union

logger = logging.getLogger(__name__)

def build_extraction(raw_text: str) -> "DocumentExtraction":
    """
    Build a DocumentExtraction object from raw text by detecting dates and items.
    """
    from .schemas import DocumentExtraction
    
    # Date detection (best effort)
    date_patterns = [
        r"\d{4}[-/]\d{1,2}[-/]\d{1,2}",  # 2023-01-01, 2023/1/1
        r"\d{1,2}月\d{1,2}日",            # 1月1日
        r"(?:令和|平成|昭和)\d{1,2}年\d{1,2}月\d{1,2}日", # 令和5年1月1日
    ]
    detected_dates = []
    for pattern in date_patterns:
        matches = re.findall(pattern, raw_text)
        detected_dates.extend(matches)
    
    # Item detection (best effort)
    # Lines starting with bullet points
    bullet_pattern = r"^[・\-*●○〇].+$"
    detected_items = []
    lines = raw_text.splitlines()
    
    in_item_section = False
    for line in lines:
        line_strip = line.strip()
        if not line_strip:
            continue
            
        # Check for bullets
        if re.match(bullet_pattern, line_strip):
            detected_items.append(line_strip)
            continue
            
        # Check for headings that might precede items
        if any(h in line_strip for h in ["持ち物", "準備", "用意するもの"]):
            in_item_section = True
            continue
        
        # If we are in an item section, treat following short lines as items
        if in_item_section:
            if len(line_strip) < 50:
                detected_items.append(line_strip)
            else:
                in_item_section = False

    return DocumentExtraction(
        raw_text=raw_text,
        detected_dates=list(dict.fromkeys(detected_dates)), # Deduplicate
        detected_items=list(dict.fromkeys(detected_items)), # Deduplicate
    )

def extract_structured(file_path: Union[str, Path], mime_type: str) -> "DocumentExtraction":
    """
    Extract text and return a structured DocumentExtraction object.
    """
    raw_text = extract_text(file_path, mime_type)
    return build_extraction(raw_text)

def extract_text(file_path: Union[str, Path], mime_type: str) -> str:
    """
    Extract text from a file (image or PDF) using local OCR or embedded text.
    Returns extracted text or an empty string on failure.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        logger.warning("OCR target file not found")
        return ""

    try:
        if mime_type.startswith("image/"):
            return _extract_from_image(file_path)
        elif mime_type == "application/pdf":
            return _extract_from_pdf(file_path)
        else:
            logger.warning(f"Unsupported mime type for OCR: {mime_type}")
            return ""
    except Exception as e:
        logger.warning(f"OCR extraction failed (ext={file_path.suffix}): {type(e).__name__}")
        return ""

def _extract_from_image(file_path: Path) -> str:
    try:
        from PIL import Image
        import pytesseract
    except ImportError:
        logger.warning("OCR libraries (Pillow/pytesseract) not installed")
        return ""

    try:
        img = Image.open(file_path)
        # Try with Japanese and English
        try:
            text = pytesseract.image_to_string(img, lang="jpn+eng")
        except pytesseract.TesseractError:
            # Fallback to default if jpn/eng data is missing
            logger.warning("Tesseract Japanese/English data missing, falling back to default language")
            text = pytesseract.image_to_string(img)
        
        return text.strip()
    except Exception as e:
        logger.warning(f"Image OCR failed: {type(e).__name__}")
        return ""

def _extract_from_pdf(file_path: Path) -> str:
    text = ""
    
    # 1. Try extracting embedded text first
    try:
        from pypdf import PdfReader
        reader = PdfReader(file_path)
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        
        text = text.strip()
        if text:
            return text
    except Exception as e:
        logger.warning(f"PDF text extraction failed, falling back to OCR: {type(e).__name__}")

    # 2. Fallback to OCR if no embedded text found
    try:
        from pdf2image import convert_from_path
        import pytesseract
        from PIL import Image
        
        # Convert PDF pages to images
        try:
            pages = convert_from_path(file_path)
        except Exception as e:
            logger.warning(f"Failed to convert PDF to images: {type(e).__name__}")
            return text # Return whatever was gathered (likely "")

        ocr_text = ""
        for page_img in pages:
            try:
                page_ocr = pytesseract.image_to_string(page_img, lang="jpn+eng")
            except pytesseract.TesseractError:
                page_ocr = pytesseract.image_to_string(page_img)
            
            if page_ocr:
                ocr_text += page_ocr + "\n"
        
        final_text = (text + "\n" + ocr_text).strip()
        return final_text
    except ImportError:
        logger.warning("OCR libraries (pdf2image/pytesseract) not installed for PDF OCR")
        return text
    except Exception as e:
        logger.warning(f"PDF OCR failed: {type(e).__name__}")
        return text
