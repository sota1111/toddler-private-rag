import asyncio
import datetime
import logging
import os
import re
import tempfile

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from typing import List, Optional, Union
from .. import schemas, storage, ocr, tagging, extraction, reminders, ai_client
from ..privacy import redact_pii
from ..rag.providers import get_llm_provider
from ..repository import InfoRepository, get_info_repository
from ..routers.auth import get_current_user
from ..rag.service import get_rag_service
from ..rag.hybrid import hybrid_search

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


def _snippet(text: Optional[str], limit: int = 160) -> Optional[str]:
    """根拠チャンクの元テキストを表示用に短縮する (SOT-1094)。"""
    if not text:
        return None
    normalized = " ".join(text.split())
    if not normalized:
        return None
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "…"


def _to_rag_source(source) -> schemas.RagSource:
    return schemas.RagSource(
        info_id=source.info_id,
        title=source.title,
        source=source.source,
        score=source.score,
        filename=source.filename,
        label=_source_label(source),
        snippet=_snippet(getattr(source, "text", None)),
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


# SOT-1039 / 提案3: 登録時AI自動タグ付け。"/{id}" より前に宣言する必要はないが、関連エンドポイントの近くに置く。
@router.post("/suggest-tags", response_model=schemas.InfoTagSuggestResponse)
def suggest_tags(
    payload: schemas.InfoTagSuggestRequest,
    current_user: str = Depends(get_current_user),
):
    """登録フォームの入力からメタデータ（種別/優先度/日付/期限/行事日/タグ）を推定する。"""
    result = tagging.suggest_metadata(
        payload.title, payload.content, payload.items, payload.info_type
    )
    return schemas.InfoTagSuggestResponse(**result)


# SOT-1039 / 提案6: ハイブリッド検索。"/{id}" (GET) より前に宣言してリテラルパスを優先させる。
@router.get("/hybrid-search", response_model=schemas.HybridSearchResponse)
def hybrid_search_info(
    q: Optional[str] = Query(None, description="検索キーワード"),
    info_type: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    tag: Optional[str] = None,
    date_from: Optional[str] = Query(None, description="日付下限 YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="日付上限 YYYY-MM-DD"),
    top_k: int = 20,
    repo: InfoRepository = Depends(get_info_repository),
    current_user: str = Depends(get_current_user),
):
    """ベクトル＋キーワード＋日付/種別ファセットを組み合わせたハイブリッド検索。"""
    hits = hybrid_search(
        repo,
        q=q,
        info_type=info_type,
        status=status,
        priority=priority,
        tag=tag,
        date_from=date_from,
        date_to=date_to,
        top_k=top_k,
    )
    return schemas.HybridSearchResponse(
        query=q or "",
        results=[
            schemas.HybridSearchResultItem(
                info=h.info,
                score=round(h.score, 4),
                vector_score=round(h.vector_score, 4),
                keyword_score=round(h.keyword_score, 4),
                matched_by=h.matched_by,
            )
            for h in hits
        ],
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
    heuristic_title = _draft_title(safe_text)
    content_text = safe_text

    # OCR後の整理(enrich)は「タイトル整形・5カテゴリ抽出・本文整理」の3つのAI呼び出しから成る。
    # これらは互いに独立(いずれも safe_text のみに依存)なので、直列ではなく並列に実行して
    # レイテンシを「3呼び出し分」から「実質1呼び出し分」へ短縮する。直列実行のままだと本番で
    # 24〜44秒かかり、クライアント/プロキシのタイムアウトを超えて「写真から登録（要手入力）」の
    # フォールバック表示になっていた (SOT-1292)。各タスクは自分の例外を内部で握りつぶし、
    # 1つの失敗が他へ波及しないようにする(graceful degradation)。

    # タイトル整形: LLM が利用可能なら洗練、失敗/未利用ならヒューリスティック。
    # 判定は OCR・カテゴリ抽出・本文整理と同じ ai_client.gemini_available() に統一する (SOT-1280)。
    def _refine_title() -> str:
        if not (safe_text.strip() and ai_client.gemini_available()):
            return heuristic_title
        try:
            provider = get_llm_provider()
            refined = provider.generate(
                "次の保育園のお知らせ本文に簡潔なタイトルを1行で付けてください。",
                [safe_text],
            )
            if refined and refined.strip():
                return refined.strip().splitlines()[0][:40]
        except Exception as e:  # graceful degradation
            logger.warning("LLM title refinement failed in /info/extract: %s", e)
        return heuristic_title

    # 5カテゴリ構造化抽出 (提出物/持ち物/締切/行事予定/注意事項)。失敗時も空で返す。
    def _extract_categories() -> schemas.ExtractedCategories:
        try:
            return schemas.ExtractedCategories(**extraction.extract_categories(safe_text))
        except Exception as e:  # graceful degradation
            logger.warning("Category extraction failed in /info/extract: %s", e)
            return schemas.ExtractedCategories()

    # 本文整理 (SOT-1214): 整理本文(カテゴリ見出しは含まない)。失敗時は空で返す。
    def _organize_body() -> str:
        try:
            return extraction.organize_body(safe_text)
        except Exception as e:  # graceful degradation
            logger.warning("Content organize failed in /info/extract: %s", e)
            return ""

    title, categories, organized_body = await asyncio.gather(
        asyncio.to_thread(_refine_title),
        asyncio.to_thread(_extract_categories),
        asyncio.to_thread(_organize_body),
    )

    # 整理本文 + 空でないカテゴリ見出しセクション (organize_content と同じ出力形)。
    section = extraction.format_category_section(categories.model_dump())
    if organized_body and section:
        content_text = f"{organized_body}\n\n{section}"
    elif organized_body or section:
        content_text = organized_body or section

    return schemas.InfoExtractDraft(
        title=title,
        info_type=info_type,
        content=content_text,
        items=items,
        date=date_iso,
        raw_text=safe_text,
        detected_dates=detected_dates,
        detected_items=detected_items,
        categories=categories,
    )


@router.post("/", response_model=schemas.NurseryInfoResponse)
def create_info(info: schemas.NurseryInfoCreate, repo: InfoRepository = Depends(get_info_repository), current_user: str = Depends(get_current_user)):
    return repo.create(info)

@router.get("/today", response_model=List[schemas.NurseryInfoResponse])
def get_today_info(repo: InfoRepository = Depends(get_info_repository), current_user: str = Depends(get_current_user)):
    return repo.list_today()

@router.get("/tomorrow", response_model=List[schemas.NurseryInfoResponse])
def get_tomorrow_info(repo: InfoRepository = Depends(get_info_repository), current_user: str = Depends(get_current_user)):
    return repo.list_tomorrow()

@router.get("/weekly", response_model=List[schemas.NurseryInfoResponse])
def get_weekly_info(repo: InfoRepository = Depends(get_info_repository), current_user: str = Depends(get_current_user)):
    return repo.list_weekly()

@router.get("/pending", response_model=List[schemas.NurseryInfoResponse])
def get_pending_info(repo: InfoRepository = Depends(get_info_repository), current_user: str = Depends(get_current_user)):
    return repo.list_pending()


# 能動リマインド (SOT-1080 / 提案5-A)。"/{id}" より前に宣言してリテラルパスを優先させる。
@router.get("/reminders", response_model=schemas.ReminderFeed)
def get_reminders(
    horizon_days: int = Query(7, ge=1, le=60, description="先読みする日数"),
    repo: InfoRepository = Depends(get_info_repository),
    current_user: str = Depends(get_current_user),
):
    """登録済み情報から締切/行事/持ち物を自律走査し、緊急度付きリマインドを返す。"""
    today = datetime.date.today()
    infos = repo.list()
    items = reminders.build_reminders(infos, today=today, horizon_days=horizon_days)
    return schemas.ReminderFeed(
        generated_at=datetime.datetime.now().isoformat(),
        horizon_days=horizon_days,
        counts=reminders.summarize_counts(items),
        items=[schemas.ReminderItem(**r) for r in items],
        digest=reminders.build_digest(items, today=today),
    )


@router.get("/reminders/digest", response_model=schemas.ReminderDigest)
def get_reminders_digest(
    horizon_days: int = Query(7, ge=1, le=60, description="先読みする日数"),
    repo: InfoRepository = Depends(get_info_repository),
    current_user: str = Depends(get_current_user),
):
    """通知配信向けのリマインドダイジェスト（Cloud Scheduler等での定期push素材）を返す。"""
    today = datetime.date.today()
    infos = repo.list()
    items = reminders.build_reminders(infos, today=today, horizon_days=horizon_days)
    return schemas.ReminderDigest(
        generated_at=datetime.datetime.now().isoformat(),
        horizon_days=horizon_days,
        total=len(items),
        digest=reminders.build_digest(items, today=today),
    )

# 仮登録一覧 (SOT-1113)。"/{id}" より前に宣言してリテラルパスを優先させる。
@router.get("/drafts", response_model=List[schemas.NurseryInfoResponse])
def list_drafts(repo: InfoRepository = Depends(get_info_repository), current_user: str = Depends(get_current_user)):
    return repo.list_drafts()


@router.get("/", response_model=List[schemas.NurseryInfoResponse])
def list_info(
    q: Optional[str] = None,
    info_type: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    tag: Optional[str] = None,
    include_attachments: bool = True,
    repo: InfoRepository = Depends(get_info_repository),
    current_user: str = Depends(get_current_user)
):
    return repo.list(q=q, info_type=info_type, status=status, priority=priority, tag=tag,
                     include_attachments=include_attachments)

@router.get("/{id}", response_model=schemas.NurseryInfoResponse)
def get_info(id: Union[int, str], repo: InfoRepository = Depends(get_info_repository), current_user: str = Depends(get_current_user)):
    db_info = repo.get(id)
    if db_info is None:
        raise HTTPException(status_code=404, detail="Info not found")
    return db_info

@router.put("/{id}", response_model=schemas.NurseryInfoResponse)
def update_info(id: Union[int, str], info: schemas.NurseryInfoUpdate, repo: InfoRepository = Depends(get_info_repository), current_user: str = Depends(get_current_user)):
    db_info = repo.update(id, info)
    if db_info is None:
        raise HTTPException(status_code=404, detail="Info not found")
    return db_info

# 本登録 (SOT-1113): 仮登録(draft)を registered に確定する。
@router.post("/{id}/finalize", response_model=schemas.NurseryInfoResponse)
def finalize_info(id: Union[int, str], repo: InfoRepository = Depends(get_info_repository), current_user: str = Depends(get_current_user)):
    db_info = repo.finalize(id)
    if db_info is None:
        raise HTTPException(status_code=404, detail="Info not found")
    return db_info


@router.delete("/{id}")
def delete_info(id: Union[int, str], repo: InfoRepository = Depends(get_info_repository), current_user: str = Depends(get_current_user)):
    # List attachments to delete physical files
    attachments = repo.list_attachments_for_info(id)
    
    # Delete physical files
    backend = storage.get_storage()
    for attachment in attachments:
        backend.delete(attachment.object_key or attachment.stored_filename)

    if not repo.delete(id):
        raise HTTPException(status_code=404, detail="Info not found")
        
    return {"message": "Successfully deleted"}

