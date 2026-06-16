import logging
from pathlib import Path
from typing import Union

logger = logging.getLogger(__name__)

def extract_text(file_path: Union[str, Path], mime_type: str) -> str:
    """
    Extract text from a file (image or PDF) using local OCR or embedded text.
    Returns extracted text or an empty string on failure.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        logger.warning("OCR source file not found")
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
        logger.warning("OCR extraction failed: %s", type(e).__name__)
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
        logger.warning("Image OCR failed: %s", type(e).__name__)
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
        logger.warning("PDF text extraction failed, falling back to OCR: %s", type(e).__name__)

    # 2. Fallback to OCR if no embedded text found
    try:
        from pdf2image import convert_from_path
        import pytesseract
        from PIL import Image
        
        # Convert PDF pages to images
        try:
            pages = convert_from_path(file_path)
        except Exception as e:
            logger.warning("Failed to convert PDF to images: %s", type(e).__name__)
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
        logger.warning("PDF OCR failed: %s", type(e).__name__)
        return text
