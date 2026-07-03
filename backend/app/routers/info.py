import asyncio
import datetime
import json
import logging
import os
import tempfile

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, UploadFile, File, Body
from fastapi.responses import StreamingResponse
from typing import List, Optional, Union
from .. import schemas, storage, ocr, tagging, extraction, reminders, clock, submission_agent
from ..privacy import redact_pii
from ..repository import InfoRepository, get_info_repository
from ..routers.auth import get_current_user
from ..rag.service import get_rag_service
from ..rag.hybrid import hybrid_search
from ..rag.indexing import index_info_id
from ..timing import time_block

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/info",
    tags=["info"],
)

# 写真のみ登録 (SOT-829) のバリデーション。既存の attachments.py と同一基準。
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
# フロント (InfoCreatePage) の選択肢と一致させる（共有定義は extraction 側）
INFO_TYPES = extraction.INFO_TYPES


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


# SOT-1304: 相対日付クエリ（今週/来週/再来週の予定）対策。直近の登録済み行事を日付つきで
# 必ず RAG コンテキストに含め、今日(JST)を認識する LLM が相対日付を解釈できるようにする。
_EVENT_CONTEXT_HORIZON_DAYS = 35
_EVENT_CONTEXT_MAX = 12
_EVENT_CONTENT_LIMIT = 300
_WEEKDAYS_JA = ("月", "火", "水", "木", "金", "土", "日")


def _info_event_date(info) -> Optional[datetime.date]:
    """行事日 > 予定日 > 期限日 の優先で、その情報が指す日付を返す。"""
    for attr in ("event_date", "date", "due_date"):
        val = getattr(info, attr, None)
        if isinstance(val, datetime.date):
            return val
    return None


def _upcoming_event_contexts(repo) -> List[str]:
    """直近（昨日〜35日先）の日付つき情報を、日付・曜日つきテキストとして返す。

    ベクトル検索は「再来週の予定」のような相対日付クエリでは語が一致せず登録済み行事を
    取りこぼす。回答が「情報が無い」と誤らないよう、これらを LLM コンテキストに補う (SOT-1304)。
    SQLite / Firestore どちらのモデルも属性アクセスで同じ形なのでそのまま扱える。
    """
    try:
        infos = repo.list()
    except Exception:  # pragma: no cover - defensive
        logger.exception("upcoming event context: failed to list infos")
        return []

    today = clock.today()
    start = today - datetime.timedelta(days=1)
    end = today + datetime.timedelta(days=_EVENT_CONTEXT_HORIZON_DAYS)

    dated = []
    for info in infos:
        d = _info_event_date(info)
        if d is None or d < start or d > end:
            continue
        dated.append((d, info))
    dated.sort(key=lambda pair: pair[0])

    contexts: List[str] = []
    for d, info in dated[:_EVENT_CONTEXT_MAX]:
        title = (getattr(info, "title", "") or "").strip()
        info_type = (getattr(info, "info_type", "") or "").strip()
        content = (getattr(info, "content", "") or "").strip()
        items = (getattr(info, "items", "") or "").strip()
        if len(content) > _EVENT_CONTENT_LIMIT:
            content = content[:_EVENT_CONTENT_LIMIT].rstrip() + "…"
        weekday = _WEEKDAYS_JA[d.weekday()]
        parts = [f"【{info_type or '予定'}】{title}", f"日付: {d.isoformat()}（{weekday}曜日）"]
        if content:
            parts.append(content)
        if items:
            parts.append(f"持ち物: {items}")
        contexts.append(" / ".join(parts))
    return contexts


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
    """ベクトル検索で関連情報を取得し、LLMで回答を生成する (RAG)。

    SOT-1357: RAG の検索コーパス（根拠）は写真の文字起こし（添付OCR）のみを対象とする。
    info/タスクの本文（content チャンク）は /ask では検索対象にしない（ocr_only=True）。
    SOT-1357 follow-up（「日付クエリ対策は残して」）: ただし相対日付クエリ（今週/来週/再来週の
    予定）対策の追加コンテキスト注入（SOT-1304）は維持する。ベクトル検索コーパスはOCRのみのまま、
    直近の登録済み行事を日付つきで LLM コンテキストに補い、日付クエリの取りこぼしを防ぐ。
    検索機能 (/search, /hybrid-search) は従来どおり content + ocr を対象とする。
    """
    service = get_rag_service(repo, ocr_only=True)
    extra_contexts = _upcoming_event_contexts(repo)
    # SOT-1374 / D: /ask 全体(検索+生成)の所要時間も計測する(内訳は service 側で個別に出る)。
    with time_block("ask_total", top_k=payload.top_k):
        result = service.answer(
            payload.query, top_k=payload.top_k, extra_contexts=extra_contexts
        )
    return schemas.RagAnswer(
        answer=result.answer,
        sources=[_to_rag_source(s) for s in result.sources],
    )


@router.post("/ask-stream")
def ask_info_stream(
    payload: schemas.RagQuery,
    repo: InfoRepository = Depends(get_info_repository),
    current_user: str = Depends(get_current_user),
):
    """`/ask` のストリーミング版 (SOT-1374 / C)。回答を逐次返し、体感待ち時間を縮める。

    既存の `POST /info/ask`(JSON)は後方互換のためそのまま維持する。本エンドポイントは
    Server-Sent Events 風の text/event-stream で、まず ``event: sources`` を1回、続けて
    ``event: token`` を逐次、最後に ``event: done`` を返す。フロントは未対応でも `/ask` に
    フォールバックできる。
    """
    service = get_rag_service(repo, ocr_only=True)
    extra_contexts = _upcoming_event_contexts(repo)
    sources, chunks = service.answer_stream(
        payload.query, top_k=payload.top_k, extra_contexts=extra_contexts
    )
    sources_payload = [_to_rag_source(s).model_dump() for s in sources]

    def _event_stream():
        # 先に sources(出典)を流す。
        yield "event: sources\ndata: " + json.dumps(
            sources_payload, ensure_ascii=False
        ) + "\n\n"
        with time_block("ask_stream_generate", top_k=payload.top_k):
            for piece in chunks:
                if not piece:
                    continue
                yield "event: token\ndata: " + json.dumps(
                    {"text": piece}, ensure_ascii=False
                ) + "\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(_event_stream(), media_type="text/event-stream")


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

    # OCR後の整理(enrich)は「OCR安全テキスト → draftフィールド」化を共有ヘルパーに集約 (SOT-1293)。
    # この純関数はサーバ側 background task (attachments.process_ocr) からも再利用される。
    # 内部の LLM 呼び出しはブロッキングなので別スレッドへ逃がす。
    fields = await asyncio.to_thread(
        extraction.build_draft_fields, safe_text, detected_dates, detected_items
    )

    categories = schemas.ExtractedCategories(**fields["categories"])

    return schemas.InfoExtractDraft(
        title=fields["title"],
        info_type=fields["info_type"],
        content=fields["content"],
        items=(fields["items"] or None),
        date=(fields["date"] or None),
        raw_text=safe_text,
        detected_dates=detected_dates,
        detected_items=detected_items,
        categories=categories,
    )


@router.post("/", response_model=schemas.NurseryInfoResponse)
def create_info(info: schemas.NurseryInfoCreate, background_tasks: BackgroundTasks, repo: InfoRepository = Depends(get_info_repository), current_user: str = Depends(get_current_user)):
    created = repo.create(info)
    # 登録時にベクトル化して永続化する (SOT-1294)。best-effort・background でリクエストを遅延させない。
    background_tasks.add_task(index_info_id, getattr(created, "id", None))
    return created

@router.get("/today", response_model=List[schemas.NurseryInfoResponse])
def get_today_info(repo: InfoRepository = Depends(get_info_repository), current_user: str = Depends(get_current_user)):
    return repo.list_today()

@router.get("/tomorrow", response_model=List[schemas.NurseryInfoResponse])
def get_tomorrow_info(repo: InfoRepository = Depends(get_info_repository), current_user: str = Depends(get_current_user)):
    return repo.list_tomorrow()

@router.get("/weekly", response_model=List[schemas.NurseryInfoResponse])
def get_weekly_info(repo: InfoRepository = Depends(get_info_repository), current_user: str = Depends(get_current_user)):
    return repo.list_weekly()

@router.get("/next-week", response_model=List[schemas.NurseryInfoResponse])
def get_next_week_info(repo: InfoRepository = Depends(get_info_repository), current_user: str = Depends(get_current_user)):
    return repo.list_next_week()

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
    today = clock.today()
    infos = repo.list()
    items = reminders.build_reminders(infos, today=today, horizon_days=horizon_days)
    return schemas.ReminderFeed(
        generated_at=clock.now_jst().isoformat(),
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
    today = clock.today()
    infos = repo.list()
    items = reminders.build_reminders(infos, today=today, horizon_days=horizon_days)
    return schemas.ReminderDigest(
        generated_at=clock.now_jst().isoformat(),
        horizon_days=horizon_days,
        total=len(items),
        digest=reminders.build_digest(items, today=today),
    )

# 仮登録一覧 (SOT-1113)。"/{id}" より前に宣言してリテラルパスを優先させる。
@router.get("/drafts", response_model=List[schemas.NurseryInfoResponse])
def list_drafts(repo: InfoRepository = Depends(get_info_repository), current_user: str = Depends(get_current_user)):
    return repo.list_drafts()


# 文字起こし中(processing)の件数 (SOT-1380)。"/{id}" より前に宣言してリテラルパスを優先させる。
@router.get("/drafts/processing-count")
def count_processing_drafts(repo: InfoRepository = Depends(get_info_repository), current_user: str = Depends(get_current_user)):
    return {"count": repo.count_processing()}


# 文字起こし(読み取り)中の項目一覧 (SOT-1499)。追加で自動登録した写真を、完了を待たず
# 仮登録画面に「読み取り中」カードとして表示するために使う。"/{id}" より前に宣言する。
@router.get("/drafts/processing", response_model=List[schemas.NurseryInfoResponse])
def list_processing_drafts(repo: InfoRepository = Depends(get_info_repository), current_user: str = Depends(get_current_user)):
    return repo.list_processing()


# アーカイブ一覧 (SOT-1500)。"/{id}" より前に宣言してリテラルパスを優先させる。
# アーカイブ済み(is_archived=True)の本登録項目のみを返す。やることリストと同様に一覧表示する。
@router.get("/archived", response_model=List[schemas.NurseryInfoResponse])
def list_archived_info(repo: InfoRepository = Depends(get_info_repository), current_user: str = Depends(get_current_user)):
    return repo.list_archived()


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
def update_info(id: Union[int, str], info: schemas.NurseryInfoUpdate, background_tasks: BackgroundTasks, repo: InfoRepository = Depends(get_info_repository), current_user: str = Depends(get_current_user)):
    db_info = repo.update(id, info)
    if db_info is None:
        raise HTTPException(status_code=404, detail="Info not found")
    # 内容更新時もベクトルを作り直して永続化する (SOT-1294)。
    background_tasks.add_task(index_info_id, id)
    return db_info

# 本登録 (SOT-1113): 仮登録(draft)を registered に確定する。
@router.post("/{id}/finalize", response_model=schemas.NurseryInfoResponse)
def finalize_info(id: Union[int, str], background_tasks: BackgroundTasks, repo: InfoRepository = Depends(get_info_repository), current_user: str = Depends(get_current_user)):
    db_info = repo.finalize(id)
    if db_info is None:
        raise HTTPException(status_code=404, detail="Info not found")
    # 本登録確定時にベクトルを永続化する (SOT-1294)。
    background_tasks.add_task(index_info_id, id)
    return db_info


# SOT-1369: 締め切り調査。一覧から選んだ項目に対し、提出書類先回りエージェント(SOT-1316)を
# 手動トリガで実行し、提出準備タスク(draft)を生成する。旧来は写真アップロードのOCR処理中に
# 自動実行していたが（attachments.py から撤去）、本エンドポイント経由の手動起動に変更した。
@router.post("/{id}/investigate-deadline")
def investigate_deadline(
    id: Union[int, str],
    payload: Optional[schemas.InvestigateDeadlineRequest] = Body(default=None),
    repo: InfoRepository = Depends(get_info_repository),
    current_user: str = Depends(get_current_user),
):
    db_info = repo.get(id)
    if db_info is None:
        raise HTTPException(status_code=404, detail="Info not found")

    # 調査対象テキストを集める: タイトル + 本文。
    # 手動追加タスクは書類名がタイトルに入り本文が空/簡素なことがあるため、タイトルを
    # 先頭に含める（SOT-1406: タイトルを含めないと抽出LLMが空入力で書類0件になる）。
    # 添付写真のOCRは調査対象から除外する（SOT-1406 再オープン要求）。
    parts: List[str] = []
    title = getattr(db_info, "title", None)
    if title:
        parts.append(title)
    content = getattr(db_info, "content", None)
    if content:
        parts.append(content)
    safe_text = "\n".join(p for p in parts if p)

    # 調査対象タスクに既に設定されている期限を最終提出期限の逆算アンカーとして渡す
    # （優先順: due_date → event_date → date。SOT-1399 4回目の再オープン対応）。
    final_due_iso = None
    for attr in ("due_date", "event_date", "date"):
        value = getattr(db_info, attr, None)
        if value:
            final_due_iso = value.isoformat() if hasattr(value, "isoformat") else str(value)
            break

    # 登録/設定値の市町村（SOT-1405）。市区町村窓口/公式HPから様式をDLする手順がある場合、
    # その市町村のダウンロードページ検索リンクを生成タスク本文へ付与するために渡す。
    municipality = (payload.municipality if payload else None) or None

    created_ids: List = []
    try:
        sub_drafts = submission_agent.build_submission_task_drafts(
            safe_text,
            None,
            language="ja",
            final_due_iso=final_due_iso,
            municipality=municipality,
        )
        # SOT-1411 再オープン対応: 生成した付随タスク(子)を1グループに束ね、基準日(最終提出期限)を
        # 基準にオフセットを再計算する。group_id が返れば、後段で元タスク(親)を同グループのアンカー
        # (offset 0)として加える。基準日が空のときは "" となりグループ化しない。
        group_id = (
            submission_agent.assign_anchor_group(sub_drafts, final_due_iso)
            if (final_due_iso and sub_drafts)
            else ""
        )
        for sub in sub_drafts:
            try:
                created = repo.create(
                    schemas.NurseryInfoCreate(
                        title=sub["title"],
                        info_type=sub["info_type"],
                        content=sub["content"],
                        items=(sub["items"] or None),
                        date=(sub["date"] or None),
                        event_date=(sub.get("event_date") or None),
                        due_date=(sub.get("due_date") or None),
                        tags=(sub.get("tags") or None),
                        # SOT-1411: 締切調査グループ識別子・基準日からの日数オフセット・基準日を
                        # 永続化し、基準日変更時に同グループの付随タスクをまとめてずらせるようにする。
                        deadline_group_id=sub.get("deadline_group_id"),
                        deadline_offset_days=sub.get("deadline_offset_days"),
                        deadline_base_date=(sub.get("deadline_base_date") or None),
                        # SOT-1368 follow-up: 親レコードに紐づけた子どもを引き継ぐ。
                        child_id=getattr(db_info, "child_id", None),
                        status="未確認",
                        priority="普通",
                        registration_state="draft",
                    )
                )
                cid = getattr(created, "id", None)
                if cid is not None:
                    created_ids.append(cid)
            except Exception as e:  # 1件の失敗で全体を止めない
                logger.warning("Failed to create submission draft for info %s: %s", id, e)
        # SOT-1411 再オープン対応: 元タスク(親)を締切グループのアンカー(基準日=offset 0)として
        # 加える。これにより親の詳細画面に基準日変更UIが出て、変更すると同グループの子タスクが
        # まとめてずれる。元タスクの既存期限(event_date/due_date)は変更しない。
        if group_id:
            try:
                repo.update(
                    id,
                    schemas.NurseryInfoUpdate(
                        deadline_group_id=group_id,
                        deadline_offset_days=0,
                        deadline_base_date=final_due_iso,
                    ),
                )
            except Exception as e:
                logger.warning("Failed to anchor source task %s to deadline group: %s", id, e)
    except Exception as e:  # 提出書類エージェント全体の失敗は無視
        logger.warning("Submission agent failed for info %s: %s", id, e)

    return {"created": len(created_ids), "ids": created_ids}


# SOT-1411: 締切調査タスクの基準日(最終提出期限)を変更し、同じ締切調査グループの付随タスクを
# 各子タスクの deadline_offset_days(提出目標日から何日手前か)に基づいてまとめて再計算(ずらし)する。
# 提出目標日からオフセット分だけ手前の日付を各子タスクの event_date/due_date に再設定する。
# 常に「新しい提出目標日 − オフセット」で計算するため、複数回呼んでも結果は同じ（冪等）。
# SOT-1432: アンカー(親)自身の event_date は提出目標日と独立させ、ここでは上書きしない
# （deadline_base_date のみ更新）。親の「日付」は編集モードの日付入力で別途変更する。
@router.post("/{id}/reschedule-deadline")
def reschedule_deadline(
    id: Union[int, str],
    payload: schemas.RescheduleDeadlineRequest,
    background_tasks: BackgroundTasks,
    repo: InfoRepository = Depends(get_info_repository),
    current_user: str = Depends(get_current_user),
):
    db_info = repo.get(id)
    if db_info is None:
        raise HTTPException(status_code=404, detail="Info not found")

    new_base = payload.base_date  # datetime.date

    def _shifted_date(offset_days) -> Optional[datetime.date]:
        if offset_days is None:
            return None
        try:
            return new_base - datetime.timedelta(days=int(offset_days))
        except (TypeError, ValueError):
            return None

    group_id = getattr(db_info, "deadline_group_id", None)
    # 対象タスク群を集める。グループが無い締切調査由来でないタスクでも、対象タスク単体は基準日へ更新する。
    if group_id:
        targets = repo.list_by_deadline_group(group_id)
        if not targets:
            targets = [db_info]
    else:
        targets = [db_info]

    updated_ids: List = []
    for task in targets:
        tid = getattr(task, "id", None)
        if tid is None:
            continue
        offset_days = getattr(task, "deadline_offset_days", None)
        update_fields = {"deadline_base_date": new_base}
        if offset_days == 0:
            # SOT-1432: アンカー(親, offset 0)の「日付」(event_date)と「提出目標日」(deadline_base_date)は独立。
            # 提出目標日の変更でアンカーの event_date/due_date は上書きしない（deadline_base_date のみ更新）。
            pass
        else:
            shifted = _shifted_date(offset_days)
            if shifted is not None:
                # オフセットが分かる子タスクは新しい提出目標日から手前にずらす。
                update_fields["event_date"] = shifted
                update_fields["due_date"] = shifted
        try:
            repo.update(tid, schemas.NurseryInfoUpdate(**update_fields))
            updated_ids.append(tid)
            background_tasks.add_task(index_info_id, tid)
        except Exception as e:  # 1件の失敗で全体を止めない
            logger.warning("Failed to reschedule task %s in group %s: %s", tid, group_id, e)

    return {"updated": len(updated_ids), "ids": updated_ids}


@router.delete("")
def delete_all_info(repo: InfoRepository = Depends(get_info_repository), current_user: str = Depends(get_current_user)):
    """全データ削除 (SOT-1356)。全タスク(NurseryInfo)と全写真(Attachment + ストレージ実体)を削除する。
    破壊的・不可逆操作。フロント側で確認を取った上で呼び出される想定。"""
    deleted_count, object_keys = repo.delete_all()

    # ストレージ実体(blob)を削除する。1件の失敗で全体を止めないよう best-effort で続行する。
    backend = storage.get_storage()
    for key in object_keys:
        try:
            backend.delete(key)
        except Exception:
            logger.warning("Failed to delete storage object during delete_all: %s", key)

    return {"message": "Successfully deleted all data", "deleted": deleted_count}


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

