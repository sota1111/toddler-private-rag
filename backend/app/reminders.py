"""能動リマインドエンジン (SOT-1080 / 提案5-A).

登録済みのお知らせ (NurseryInfo) を自律的に走査し、締切・行事・持ち物準備のうち
期日が近い／過ぎたものを「緊急度付きリマインド」として導出する。受動的なRAG検索から
能動的に通知するエージェントへ格上げするための中核ロジック。

このモジュールは FastAPI に依存しない純粋ロジックとして実装し、ORM モデル
(models.NurseryInfo) と Firestore データクラス (FirestoreNurseryInfo) の両方を、
属性アクセス (id/title/info_type/status/priority/due_date/event_date/date/items)
だけで扱えるようにする。LLM はダイジェスト整文のみ任意で利用し、失敗時・オフライン時は
決定的なヒューリスティックにフォールバックする。
"""

import datetime
import logging
from typing import Any, Dict, List

from . import ai_client

logger = logging.getLogger(__name__)

# 緊急度の並び順（小さいほど緊急）
URGENCY_ORDER = ["overdue", "today", "soon", "upcoming"]
_URGENCY_INDEX = {u: i for i, u in enumerate(URGENCY_ORDER)}

# 完了とみなし締切リマインドから除外する status
DONE_STATUS = "対応済み"

# 優先度の並び（高いものを上位に）
_PRIORITY_ORDER = {"高": 0, "普通": 1, "低": 2}


def _classify(days_until: int, horizon_days: int) -> str:
    """残日数を緊急度バケットに分類する。範囲外は None 相当として呼び出し側で除外。"""
    if days_until < 0:
        return "overdue"
    if days_until == 0:
        return "today"
    if 1 <= days_until <= 3:
        return "soon"
    if 4 <= days_until <= horizon_days:
        return "upcoming"
    return ""


def _iso(d: datetime.date) -> str:
    return d.isoformat()


def _deadline_message(title: str, days_until: int, urgency: str) -> str:
    if urgency == "overdue":
        return f"⚠️ 期限切れ: 「{title}」の提出期限を過ぎています（{abs(days_until)}日経過）"
    if urgency == "today":
        return f"本日締切: 「{title}」"
    if urgency == "soon":
        return f"あと{days_until}日: 「{title}」の提出期限です"
    return f"{days_until}日後: 「{title}」の提出期限です"


def _event_message(title: str, days_until: int, urgency: str) -> str:
    if urgency == "today":
        return f"本日: {title}"
    if urgency == "soon":
        return f"あと{days_until}日: {title}"
    return f"{days_until}日後: {title}"


def _reminder(info: Any, *, kind: str, target: datetime.date, days_until: int,
              urgency: str, message: str) -> Dict[str, Any]:
    return {
        "info_id": getattr(info, "id"),
        "title": getattr(info, "title", "") or "",
        "info_type": getattr(info, "info_type", "") or "",
        "kind": kind,
        "target_date": _iso(target),
        "days_until": days_until,
        "urgency": urgency,
        "status": getattr(info, "status", "") or "",
        "priority": getattr(info, "priority", "") or "",
        "message": message[:120],
    }


def build_reminders(infos: List[Any], *, today: datetime.date,
                    horizon_days: int = 7) -> List[Dict[str, Any]]:
    """全 info から緊急度付きリマインドを導出して整列済みリストで返す。

    - deadline: due_date 由来。status==対応済み は除外。overdue も含む。
    - event:    event_date 由来。過去の行事は除外（0..horizon のみ）。status では除外しない。
    - belongings: items があり、基準日(event_date or date)が「明日」のとき前日準備として通知。
    """
    reminders: List[Dict[str, Any]] = []

    for info in infos:
        title = getattr(info, "title", "") or ""
        status = getattr(info, "status", "") or ""

        # --- 締切 (deadline) ---
        due_date = getattr(info, "due_date", None)
        if isinstance(due_date, datetime.date) and status != DONE_STATUS:
            days = (due_date - today).days
            urgency = _classify(days, horizon_days)
            if urgency:
                reminders.append(_reminder(
                    info, kind="deadline", target=due_date, days_until=days,
                    urgency=urgency, message=_deadline_message(title, days, urgency),
                ))

        # --- 行事 (event) ---
        event_date = getattr(info, "event_date", None)
        if isinstance(event_date, datetime.date):
            days = (event_date - today).days
            # 過去の行事は通知しない（0..horizon のみ）
            if 0 <= days <= horizon_days:
                urgency = _classify(days, horizon_days)
                if urgency:
                    reminders.append(_reminder(
                        info, kind="event", target=event_date, days_until=days,
                        urgency=urgency, message=_event_message(title, days, urgency),
                    ))

        # --- 持ち物 (belongings, 前日準備) ---
        items = getattr(info, "items", None)
        if items and str(items).strip():
            base = event_date if isinstance(event_date, datetime.date) else getattr(info, "date", None)
            if isinstance(base, datetime.date):
                days = (base - today).days
                if days == 1:  # 明日の準備
                    items_text = " ".join(str(items).split())
                    reminders.append(_reminder(
                        info, kind="belongings", target=base, days_until=days,
                        urgency="soon",
                        message=f"明日の持ち物: {items_text}（{title}）",
                    ))

    reminders.sort(key=lambda r: (
        _URGENCY_INDEX.get(r["urgency"], len(URGENCY_ORDER)),
        r["days_until"],
        _PRIORITY_ORDER.get(r["priority"], 1),
    ))
    return reminders


def summarize_counts(reminders: List[Dict[str, Any]]) -> Dict[str, int]:
    """緊急度ごとの件数 + total を返す。"""
    counts = {u: 0 for u in URGENCY_ORDER}
    for r in reminders:
        u = r.get("urgency")
        if u in counts:
            counts[u] += 1
    counts["total"] = len(reminders)
    return counts


def _heuristic_digest(reminders: List[Dict[str, Any]], counts: Dict[str, int]) -> str:
    """通知配信向けの決定的な要約テキストを組み立てる。"""
    if not reminders:
        return "本日の能動リマインドはありません。"

    header_parts = []
    if counts.get("overdue"):
        header_parts.append(f"期限切れ{counts['overdue']}件")
    if counts.get("today"):
        header_parts.append(f"本日{counts['today']}件")
    if counts.get("soon"):
        header_parts.append(f"まもなく{counts['soon']}件")
    if counts.get("upcoming"):
        header_parts.append(f"予定{counts['upcoming']}件")
    header = "🔔 能動リマインド: " + "、".join(header_parts) if header_parts else "🔔 能動リマインド"

    lines = [header]
    for r in reminders[:5]:
        lines.append(f"・{r['message']}")
    if len(reminders) > 5:
        lines.append(f"ほか{len(reminders) - 5}件")
    return "\n".join(lines)


def build_digest(reminders: List[Dict[str, Any]], *, today: datetime.date) -> str:
    """通知配信向けの要約テキスト。AI利用可能時のみ自然文に整文し、失敗時はヒューリスティック。"""
    counts = summarize_counts(reminders)
    base = _heuristic_digest(reminders, counts)

    if not reminders or not ai_client.gemini_available():
        return base

    try:
        client = ai_client.get_genai_client()
        model = ai_client.get_model_name()
        prompt = (
            "あなたは保育園の保護者向けリマインドを通知文にまとめるアシスタントです。"
            "以下のリマインド要約を、保護者がひと目で行動できる、やさしく簡潔な日本語の通知文"
            "（3〜5行・絵文字は控えめ）に整えてください。新しい情報は追加しないでください。\n\n"
            f"# 本日: {today.isoformat()}\n# リマインド要約\n{base}\n\n# 通知文"
        )
        response = ai_client.with_retry(
            lambda: client.models.generate_content(model=model, contents=prompt)
        )
        text = (getattr(response, "text", "") or "").strip()
        return text or base
    except Exception as e:  # graceful degradation
        logger.warning("LLM digest refinement failed, using heuristic: %s", e)
        return base
