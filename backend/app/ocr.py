import hashlib
import logging
import os
import re
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Union

from .concurrency import BoundedCache

if TYPE_CHECKING:
    from .schemas import DocumentExtraction

logger = logging.getLogger(__name__)

# SOT-1374 / B: 同じ画像/PDF を再 OCR しないためのプロセス内キャッシュ。
# キー = (ファイルバイト列のハッシュ, mime_type)。OCR は外部API待ちが主体なので、
# 同一バイト列の再アップロード時に外部呼び出しを丸ごと省ける。
_OCR_CACHE = BoundedCache(maxsize=128)


def _ocr_max_image_dim() -> int:
    """OCR 前に画像を縮小する最大辺(px)。``OCR_MAX_IMAGE_DIM``、既定 2048。0 以下で無効。"""
    try:
        return int(os.getenv("OCR_MAX_IMAGE_DIM", "2048"))
    except (TypeError, ValueError):
        return 2048


def _maybe_downscale_image(file_path: Path) -> Optional[Path]:
    """画像の最大辺が上限を超える場合のみ、縮小したコピーを temp に作って返す (SOT-1374 / C)。

    縮小不要 / Pillow 不在 / 失敗時は ``None`` を返す(呼び出し側は元ファイルを使う)。
    返り値が Path のときは呼び出し側が使用後に削除する責務を持つ。
    元ファイルは一切上書きしない。
    """
    max_dim = _ocr_max_image_dim()
    if max_dim <= 0:
        return None
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(file_path) as img:
            width, height = img.size
            if max(width, height) <= max_dim:
                return None
            scale = max_dim / float(max(width, height))
            new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
            resized = img.convert("RGB") if img.mode not in ("RGB", "L") else img.copy()
            resized = resized.resize(new_size)
            fd, tmp_name = tempfile.mkstemp(suffix=".jpg", prefix="ocr_down_")
            os.close(fd)
            tmp_path = Path(tmp_name)
            resized.save(tmp_path, format="JPEG", quality=85)
        logger.info(
            "[ocr] downscaled image %dx%d -> %dx%d for OCR", width, height, *new_size
        )
        return tmp_path
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("image downscale failed, using original: %s", type(e).__name__)
        return None


def _gemini_ocr_enabled() -> bool:
    """Whether to attempt Gemini vision OCR for images.

    Enabled when an AI client is available (Vertex AI mode on, or a Gemini API key
    present) and OCR_PROVIDER is not explicitly set to a non-Gemini engine. Falls
    back to local Tesseract otherwise.
    """
    from .ai_client import gemini_available

    if not gemini_available():
        return False
    return os.getenv("OCR_PROVIDER", "").strip().lower() not in ("tesseract", "fake", "local")


def _vision_ocr_enabled() -> bool:
    """Whether to attempt Google Cloud Vision API OCR for images.

    Enabled when ``OCR_PROVIDER`` is explicitly ``"vision"``, or when ``OCR_PROVIDER`` is
    unset AND Cloud Vision credentials look available (Vertex mode on, or a GCP project /
    service-account credentials are configured). Conservative by design: when unsure it
    returns False so the existing Gemini/Tesseract paths are used.
    """
    provider = os.getenv("OCR_PROVIDER", "").strip().lower()
    if provider == "vision":
        return True
    if provider:
        # An explicit non-vision provider (tesseract/fake/local/gemini) disables Vision.
        return False

    # Auto mode: only prefer Vision when GCP credentials are plausibly available.
    from .ai_client import use_vertex

    return (
        use_vertex()
        or bool(os.getenv("GOOGLE_CLOUD_PROJECT"))
        or bool(os.getenv("GOOGLE_APPLICATION_CREDENTIALS"))
    )


def _extract_from_image_vision(file_path: Path) -> str:
    """Extract text from an image using the Google Cloud Vision API.

    Uses document text detection, which handles multi-line documents (園だより/プリント)
    better than sparse text detection. Returns an empty string on any failure (missing
    SDK, credentials, network error, etc.) so the caller can fall back to other OCR paths.
    """
    try:
        from google.cloud import vision
    except ImportError:
        logger.warning("google-cloud-vision not installed; skipping Cloud Vision OCR")
        return ""

    try:
        from google.api_core import exceptions as gexc
    except ImportError:  # api_core は通常同梱されるが、無くても動作させる
        gexc = None

    def _is_transient(exc: Exception) -> bool:
        # 一時的なサービス混雑 (ServiceUnavailable/503) や期限超過は再試行する。
        if gexc is not None and isinstance(
            exc, (gexc.ServiceUnavailable, gexc.DeadlineExceeded)
        ):
            return True
        msg = str(exc).lower()
        return any(
            k in msg for k in ("serviceunavailable", "503", "unavailable", "deadline")
        )

    try:
        client = vision.ImageAnnotatorClient()
        content = file_path.read_bytes()
        image = vision.Image(content=content)

        # Cloud Vision は間欠的に ServiceUnavailable を返すことがあるため数回リトライし、
        # 一時障害で不要にフォールバック(精度の劣るエンジン)へ落ちないようにする。
        attempts = 3
        response = None
        for i in range(attempts):
            try:
                response = client.document_text_detection(image=image)
                break
            except Exception as e:  # noqa: BLE001
                if _is_transient(e) and i < attempts - 1:
                    logger.warning(
                        "Cloud Vision transient error (%s); retrying %d/%d",
                        type(e).__name__,
                        i + 1,
                        attempts - 1,
                    )
                    time.sleep(1.0 * (2 ** i))
                    continue
                raise

        if getattr(response, "error", None) and response.error.message:
            logger.warning("Cloud Vision OCR returned error; falling back to other OCR")
            return ""

        full = getattr(response, "full_text_annotation", None)
        if full and (full.text or "").strip():
            return full.text.strip()

        annotations = getattr(response, "text_annotations", None) or []
        if annotations:
            return (annotations[0].description or "").strip()

        return ""
    except Exception as e:
        logger.warning(f"Cloud Vision OCR failed, falling back to other OCR: {type(e).__name__}")
        return ""


def _extract_from_image_gemini(file_path: Path) -> str:
    """Extract text from an image using Gemini vision via Vertex AI (or API-key fallback).

    Returns an empty string on any failure (missing client/SDK, network error, etc.)
    so the caller can fall back to local OCR.
    """
    from .ai_client import get_genai_client, get_model_name, with_retry

    try:
        from PIL import Image
    except ImportError:
        logger.warning("Pillow not installed; skipping Gemini OCR")
        return ""

    # gemini-2.5 系は "thinking" が既定で有効。OCR(本文の全文書き起こし)では思考トークンが
    # 出力枠を食い潰し、本文テキストが空のまま finish_reason=MAX_TOKENS で正常終了する
    # ことがある(例外は出ず、ログにも残らない → 文字起こし失敗の主因)。思考を無効化し
    # 十分な出力上限を明示して、空テキストになる事象を防ぐ。
    config = None
    try:
        from google.genai import types

        config = types.GenerateContentConfig(
            max_output_tokens=8192,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )
    except Exception:  # SDK 差異で types/ThinkingConfig が無い場合は設定なしで続行
        config = None

    try:
        client = get_genai_client()
        img = Image.open(file_path)
        prompt = (
            "この画像に含まれる文字をそのまま日本語/英語ですべて書き起こしてください。"
            "説明や前置きは不要で、本文テキストのみ返してください。"
        )

        def _generate():
            if config is not None:
                return client.models.generate_content(
                    model=get_model_name(), contents=[prompt, img], config=config
                )
            return client.models.generate_content(
                model=get_model_name(), contents=[prompt, img]
            )

        response = with_retry(_generate)
        text = (getattr(response, "text", "") or "").strip()
        if not text:
            finish_reason = None
            try:
                candidates = getattr(response, "candidates", None) or []
                if candidates:
                    finish_reason = getattr(candidates[0], "finish_reason", None)
            except Exception:
                finish_reason = None
            logger.warning(
                "Gemini OCR returned empty text (finish_reason=%s); falling back to local OCR",
                finish_reason,
            )
        return text
    except Exception as e:
        logger.warning(f"Gemini OCR failed, falling back to local OCR: {type(e).__name__}")
        return ""

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
        # SOT-1567 提案4: M/D(年なしスラッシュ, 例 7/31)。前後が数字/スラッシュのときは
        # YYYY/M/D の一部なので拾わない（負の先読み/後読みで二重検出を防ぐ）。年は発行年で補完。
        r"(?<![\d/])\d{1,2}/\d{1,2}(?![\d/])",
    ]
    detected_dates = []
    for pattern in date_patterns:
        matches = re.findall(pattern, raw_text)
        detected_dates.extend(matches)

    # SOT-1567 提案3: 混同文字を含む日付らしいトークン(例 7／3l)を、日付フィールド限定で
    # 混同正規化してから拾う（本文全体には広げない＝過補正回避）。正規化後の文字列(例 7/31)を
    # 候補に加え、下流の normalize_date でそのまま解釈できるようにする。
    from . import extraction
    detected_dates.extend(extraction.find_confusable_date_tokens(raw_text))
    
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

    # SOT-1470 D3: extraction producing no text is a silent-degradation signal under
    # never-throw. Emit an explicit token so a log-based metric / alert can track the
    # extraction-0 rate (see infra/terraform/monitoring.tf).
    if not raw_text.strip():
        logger.warning("ocr_extraction_empty char_count=%d", len(raw_text))

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

    # SOT-1374 / B: 同一バイト列 + mime の OCR 結果はキャッシュから返し、再 OCR を省く。
    cache_key = None
    try:
        digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
        cache_key = (digest, mime_type)
        cached = _OCR_CACHE.get(cache_key)
        if cached is not None:
            logger.info("[ocr] cache hit (mime=%s)", mime_type)
            return cached
    except Exception:  # pragma: no cover - hashing must never break OCR
        cache_key = None

    try:
        if mime_type.startswith("image/"):
            result = _extract_from_image(file_path)
        elif mime_type == "application/pdf":
            result = _extract_from_pdf(file_path)
        else:
            logger.warning(f"Unsupported mime type for OCR: {mime_type}")
            return ""
    except Exception as e:
        logger.warning(f"OCR extraction failed (ext={file_path.suffix}): {type(e).__name__}")
        return ""

    if cache_key is not None and result:
        _OCR_CACHE.set(cache_key, result)
    return result

def _extract_from_image(file_path: Path) -> str:
    # どのエンジンを試したかを記録し、全エンジンが空を返したときに原因追跡できるようにする。
    attempted: list[str] = []

    # SOT-1374 / C: 大きすぎる画像は OCR 前に縮小し、転送・処理時間を削減する。
    # 縮小コピーは temp に作り、元ファイルは変更しない。使用後に削除する。
    downscaled = _maybe_downscale_image(file_path)
    work_path = downscaled or file_path
    try:
        # Prefer Cloud Vision API when configured; fall back to Gemini, then local OCR.
        if _vision_ocr_enabled():
            attempted.append("vision")
            vision_text = _extract_from_image_vision(work_path)
            if vision_text:
                return vision_text

        # Prefer Gemini vision when configured; fall back to local OCR on empty/failure.
        if _gemini_ocr_enabled():
            attempted.append("gemini")
            gemini_text = _extract_from_image_gemini(work_path)
            if gemini_text:
                return gemini_text

        attempted.append("tesseract")
        return _tesseract_image(work_path, attempted)
    finally:
        if downscaled is not None:
            try:
                os.remove(downscaled)
            except OSError:
                pass


def _tesseract_image(file_path: Path, attempted: list[str]) -> str:
    try:
        from PIL import Image
        import pytesseract
    except ImportError:
        logger.warning("OCR libraries (Pillow/pytesseract) not installed")
        # tesseract も使えない場合、それ以前に試したエンジン名を記録しておく。
        prior = [a for a in attempted if a != "tesseract"]
        if prior:
            logger.warning(
                "OCR produced no text (engines attempted: %s; tesseract unavailable)",
                ", ".join(prior),
            )
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

        result = text.strip()
        if not result:
            logger.warning(
                "OCR produced no text (engines attempted: %s)", ", ".join(attempted)
            )
        return result
    except Exception as e:
        logger.warning(f"Image OCR failed: {type(e).__name__}")
        logger.warning(
            "OCR produced no text (engines attempted: %s)", ", ".join(attempted)
        )
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
