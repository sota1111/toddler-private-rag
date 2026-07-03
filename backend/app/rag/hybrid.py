"""ハイブリッド検索 (SOT-1039 / 提案6).

ベクトル検索 (RagService) + キーワード一致 + ファセット (種別/ステータス/優先度/タグ/日付範囲)
を組み合わせて情報をランキングする。ファセットは事前フィルタ、キーワードとベクトルでスコアリングする。
"""

import datetime
import logging
from dataclasses import dataclass, field
from typing import Any, List, Optional

from .service import get_rag_service

logger = logging.getLogger(__name__)

# キーワード(0.6) とベクトル(0.4) の重み
_KW_WEIGHT = 0.6
_VEC_WEIGHT = 0.4


@dataclass
class HybridHit:
    info: Any
    score: float
    vector_score: float
    keyword_score: float
    matched_by: List[str] = field(default_factory=list)


def _to_date(val: Optional[str]) -> Optional[datetime.date]:
    if not val:
        return None
    try:
        return datetime.date.fromisoformat(str(val).strip())
    except ValueError:
        return None


def _info_primary_date(info: Any) -> Optional[datetime.date]:
    return getattr(info, "date", None) or getattr(info, "event_date", None) or getattr(info, "due_date", None)


def _created_key(info: Any) -> datetime.datetime:
    created = getattr(info, "created_at", None)
    if isinstance(created, datetime.datetime):
        return created
    return datetime.datetime.min


def _keyword_score(info: Any, tokens: List[str]) -> tuple[float, List[str]]:
    if not tokens:
        return 0.0, []
    title = (getattr(info, "title", "") or "").lower()
    content = (getattr(info, "content", "") or "").lower()
    tags = (getattr(info, "tags", "") or "").lower()
    items = (getattr(info, "items", "") or "").lower()
    ocr_parts = []
    for att in getattr(info, "attachments", None) or []:
        ocr_text = getattr(att, "ocr_text", None)
        if ocr_text:
            ocr_parts.append(ocr_text.lower())
    ocr = " ".join(ocr_parts)
    haystack = " ".join([title, content, tags, items, ocr])

    matched = [tok for tok in tokens if tok in haystack]
    fields: List[str] = []
    if any(tok in title for tok in tokens):
        fields.append("title")
    if any(tok in content for tok in tokens):
        fields.append("content")
    if any(tok in tags for tok in tokens):
        fields.append("tags")
    if any(tok in ocr for tok in tokens):
        fields.append("ocr")
    return (len(matched) / len(tokens)), fields


def hybrid_search(
    repo,
    *,
    q: Optional[str] = None,
    info_type: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    tag: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    top_k: int = 20,
) -> List[HybridHit]:
    try:
        # SOT-1504: 検索(hybrid-search)の対象にはアーカイブ済み(is_archived=True)の項目も含める。
        infos = repo.list(include_archived=True)
    except Exception:  # pragma: no cover - defensive
        logger.exception("hybrid_search: failed to list infos")
        return []

    df = _to_date(date_from)
    dt = _to_date(date_to)

    # --- ファセット事前フィルタ ---
    candidates: List[Any] = []
    for info in infos:
        if info_type and getattr(info, "info_type", None) != info_type:
            continue
        if status and getattr(info, "status", None) != status:
            continue
        if priority and getattr(info, "priority", None) != priority:
            continue
        if tag:
            raw_tags = getattr(info, "tags", None) or ""
            tag_list = [x.strip() for x in raw_tags.split(",") if x.strip()]
            if tag not in tag_list:
                continue
        if df or dt:
            d = _info_primary_date(info)
            if d is None:
                continue
            if df and d < df:
                continue
            if dt and d > dt:
                continue
        candidates.append(info)

    query = (q or "").strip()
    tokens = [t for t in query.lower().split() if t]

    # --- ベクトルスコア (クエリがある場合のみ) ---
    vec_scores: dict = {}
    if query:
        service = get_rag_service(repo)
        for src in service.search(query, top_k=max(top_k, 20)):
            iid = src.info_id
            for key in (iid, str(iid)):
                vec_scores[key] = max(vec_scores.get(key, 0.0), src.score)

    hits: List[HybridHit] = []
    for info in candidates:
        kw_score, kw_fields = _keyword_score(info, tokens)
        info_id = getattr(info, "id", None)
        vec = vec_scores.get(info_id, vec_scores.get(str(info_id), 0.0))
        matched_by = list(kw_fields)
        if vec > 0:
            matched_by.append("vector")
        score = _KW_WEIGHT * kw_score + _VEC_WEIGHT * vec if query else 0.0
        hits.append(
            HybridHit(
                info=info,
                score=score,
                vector_score=vec,
                keyword_score=kw_score,
                matched_by=matched_by,
            )
        )

    if query:
        hits.sort(key=lambda h: (h.score, _created_key(h.info)), reverse=True)
    else:
        hits.sort(key=lambda h: _created_key(h.info), reverse=True)

    return hits[:top_k]
