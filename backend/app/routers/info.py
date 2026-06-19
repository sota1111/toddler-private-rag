import datetime
import logging
import os
import re
import tempfile

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from typing import List, Optional
from .. import schemas, storage, ocr
from ..privacy import redact_pii
from ..rag.providers import get_llm_provider
from ..repository import InfoRepository, get_info_repository
from ..routers.auth import get_current_user
from ..rag.service import get_rag_service

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/info",
    tags=["info"],
)

# 写真のみ登録 (SOT-829) のバリデーション。既存の attachments.py と同一基準。
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
# フロント (InfoCreatePage) の選択肢と一致させる
INFO_TYPES = ["資料", "掲示", "行事", "持ち物", "提出物", "お知らせ", "給食", "休園変更"]


def _normalize_date(raw: str) -> Optional[str]:
    """検出した日付文字列をベストエフォートで ISO (YYYY-MM-DD) に正規化する。

    対応: YYYY-MM-DD / YYYY/M/D / M月D日 (年は当年と仮定)。
    確実に解釈できない場合は None を返す。
    """
    if not raw:
        return None
    s = raw.strip()

    # YYYY-MM-DD / YYYY/M/D
    m = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$", s)
    if m:
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        # M月D日 (年は当年と仮定)
        m = re.match(r"^(\d{1,2})月(\d{1,2})日$", s)
        if not m:
            return None
        year = datetime.date.today().year
        month, day = int(m.group(1)), int(m.group(2))

    try:
        return datetime.date(year, month, day).isoformat()
    except ValueError:
        return None


def _guess_info_type(text: str, has_items: bool) -> str:
    """検出結果からヒューリスティックに種別を推定する（必ず INFO_TYPES のいずれか）。"""
    if has_items:
        return "持ち物"
    if any(kw in text for kw in ["行事", "イベント", "運動会", "発表会", "遠足"]):
        return "行事"
    if "給食" in text or "献立" in text:
        return "給食"
    if "休園" in text or "休み" in text:
        return "休園変更"
    return "お知らせ"


def _draft_title(text: str) -> str:
    """安全テキストの先頭の非空行をタイトルにする（最大40文字）。"""
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line[:40]
    return "写真から登録"


def _source_label(source) -> str:
    """出典の表示用ラベルを生成する (タイトル + 添付ファイル名)。"""
    if source.source == "ocr" and source.filename:
        return f"{source.title}（添付: {source.filename}）"
    return source.title


def _to_rag_source(source) -> schemas.RagSource:
    return schemas.RagSource(
        info_id=source.info_id,
        title=source.title,
        source=source.source,
        score=source.score,
        filename=source.filename,
        label=_source_label(source),
    )


# NOTE: declared before the "/{id}" route so the literal paths take precedence.
@router.post("/ask", response_model=schemas.RagAnswer)
def ask_info(
    payload: schemas.RagQuery,
    repo: InfoRepository = Depends(get_info_repository),
    current_user: str = Depends(get_current_user),
):
    """ベクトル検索で関連情報を取得し、LLMで回答を生成する (RAG)。"""
    service = get_rag_service(repo)
    result = service.answer(payload.query, top_k=payload.top_k)
    return schemas.RagAnswer(
        answer=result.answer,
        sources=[_to_rag_source(s) for s in result.sources],
    )


@router.get("/search", response_model=schemas.RagSearchResponse)
def vector_search_info(
    q: str = Query(..., description="検索クエリ"),
    top_k: int = 4,
    repo: InfoRepository = Depends(get_info_repository),
    current_user: str = Depends(get_current_user),
):
    """埋め込みベースのベクトル検索のみを実行し、関連チャンク（出典）を返す。"""
    service = get_rag_service(repo)
    sources = service.search(q, top_k=top_k)
    return schemas.RagSearchResponse(
        query=q,
        sources=[_to_rag_source(s) for s in sources],
    )


# NOTE: 写真のみ登録 (SOT-829)。"/{id}" より前に宣言し、リテラルパスを優先させる。
@router.post("/extract", response_model=schemas.InfoExtractDraft)
async def extract_info_draft(
    file: UploadFile = File(...),
    current_user: str = Depends(get_current_user),
):
    """画像をOCR・構造化し、登録フォーム用ドラフトを返す (DB未保存)。"""
    # バリデーション (attachments.py と同一基準)
    content_type = file.content_type or ""
    if content_type != "application/pdf" and not content_type.startswith("image/"):
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Allowed types: image/*, application/pdf",
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {MAX_FILE_SIZE / (1024 * 1024)}MB",
        )

    # OCR は実ファイルパスを必要とするため一時ファイルに書き出す
    suffix = os.path.splitext(file.filename or "")[1]
    tmp_path: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        raw = ocr.extract_text(tmp_path, content_type)
    except Exception as e:  # OCR 失敗時もフォールバックでドラフトを返す
        logger.warning("OCR extraction failed in /info/extract: %s", e)
        raw = ""
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

    structured = ocr.build_extraction(raw)
    safe_text = redact_pii(structured.raw_text)

    detected_dates = structured.detected_dates
    detected_items = structured.detected_items

    date_iso: Optional[str] = None
    for d in detected_dates:
        date_iso = _normalize_date(d)
        if date_iso:
            break

    items = "\n".join(detected_items) if detected_items else None
    info_type = _guess_info_type(safe_text, bool(detected_items))
    title = _draft_title(safe_text)
    content_text = safe_text

    # LLM が利用可能なら title/content を洗練する（失敗時はヒューリスティックにフォールバック）
    if safe_text.strip() and os.getenv("LLM_PROVIDER", "fake").lower() == "gemini":
        try:
            provider = get_llm_provider()
            refined = provider.generate(
                "次の保育園のお知らせ本文に簡潔なタイトルを1行で付けてください。",
                [safe_text],
            )
            if refined and refined.strip():
                title = refined.strip().splitlines()[0][:40]
        except Exception as e:  # graceful degradation
            logger.warning("LLM title refinement failed in /info/extract: %s", e)

    return schemas.InfoExtractDraft(
        title=title,
        info_type=info_type,
        content=content_text,
        items=items,
        date=date_iso,
        raw_text=safe_text,
        detected_dates=detected_dates,
        detected_items=detected_items,
    )


@router.post("/", response_model=schemas.NurseryInfoResponse)
def create_info(info: schemas.NurseryInfoCreate, repo: InfoRepository = Depends(get_info_repository), current_user: str = Depends(get_current_user)):
    return repo.create(info)

@router.get("/tomorrow", response_model=List[schemas.NurseryInfoResponse])
def get_tomorrow_info(repo: InfoRepository = Depends(get_info_repository), current_user: str = Depends(get_current_user)):
    return repo.list_tomorrow()

@router.get("/weekly", response_model=List[schemas.NurseryInfoResponse])
def get_weekly_info(repo: InfoRepository = Depends(get_info_repository), current_user: str = Depends(get_current_user)):
    return repo.list_weekly()

@router.get("/pending", response_model=List[schemas.NurseryInfoResponse])
def get_pending_info(repo: InfoRepository = Depends(get_info_repository), current_user: str = Depends(get_current_user)):
    return repo.list_pending()

@router.get("/", response_model=List[schemas.NurseryInfoResponse])
def list_info(
    q: Optional[str] = None,
    info_type: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    tag: Optional[str] = None,
    repo: InfoRepository = Depends(get_info_repository),
    current_user: str = Depends(get_current_user)
):
    return repo.list(q=q, info_type=info_type, status=status, priority=priority, tag=tag)

@router.get("/{id}", response_model=schemas.NurseryInfoResponse)
def get_info(id: int, repo: InfoRepository = Depends(get_info_repository), current_user: str = Depends(get_current_user)):
    db_info = repo.get(id)
    if db_info is None:
        raise HTTPException(status_code=404, detail="Info not found")
    return db_info

@router.put("/{id}", response_model=schemas.NurseryInfoResponse)
def update_info(id: int, info: schemas.NurseryInfoUpdate, repo: InfoRepository = Depends(get_info_repository), current_user: str = Depends(get_current_user)):
    db_info = repo.update(id, info)
    if db_info is None:
        raise HTTPException(status_code=404, detail="Info not found")
    return db_info

@router.delete("/{id}")
def delete_info(id: int, repo: InfoRepository = Depends(get_info_repository), current_user: str = Depends(get_current_user)):
    # List attachments to delete physical files
    attachments = repo.list_attachments_for_info(id)
    
    # Delete physical files
    backend = storage.get_storage()
    for attachment in attachments:
        backend.delete(attachment.object_key or attachment.stored_filename)

    if not repo.delete(id):
        raise HTTPException(status_code=404, detail="Info not found")
        
    return {"message": "Successfully deleted"}

