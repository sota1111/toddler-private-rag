"""登録時のAI自動タグ付け (SOT-1039 / 提案3).

入力（タイトル・内容・持ち物）から、種別 / 優先度 / 日付 / 提出期限 / 行事日 / タグ を推定する。
Gemini / Vertex AI クライアントが利用可能なら LLM で構造化推定し、失敗時やオフライン時は
決定的なヒューリスティックにフォールバックする。テスト・オフラインでは常にヒューリスティックになる。
"""

import datetime
import json
import logging
import re
from typing import List, Optional

from . import ai_client

logger = logging.getLogger(__name__)

# フロント (infoFormOptions.ts) と一致させる
INFO_TYPES = ["資料", "掲示", "行事", "持ち物", "提出物", "お知らせ", "給食", "休園変更"]
PRIORITY_TYPES = ["高", "普通", "低"]

# タグ候補の辞書（本文に含まれていれば採用）
_TAG_KEYWORDS = [
    "遠足", "運動会", "発表会", "参観", "面談", "健康診断", "予防接種", "身体測定",
    "給食", "献立", "誕生日", "プール", "持ち物", "提出", "集金", "写真", "お弁当",
    "保護者会", "懇談会", "避難訓練", "卒園", "入園",
]

_HIGH_PRIORITY_KW = ["至急", "必ず", "重要", "締切", "締め切り", "期限", "忘れず", "本日", "明日まで"]
_LOW_PRIORITY_KW = ["任意", "参考", "ご自由", "お知らせのみ"]
_DUE_KW = ["締切", "締め切り", "期限", "提出", "返却", "申込", "申し込み"]
_EVENT_KW = ["運動会", "発表会", "遠足", "参観", "面談", "プール", "誕生日会", "行事"]

_DATE_RE = re.compile(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}月\d{1,2}日)")


def _normalize_date(raw: Optional[str]) -> Optional[str]:
    """日付文字列をベストエフォートで ISO (YYYY-MM-DD) に正規化する。"""
    if not raw:
        return None
    s = str(raw).strip()
    m = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$", s)
    if m:
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.match(r"^(\d{1,2})月(\d{1,2})日$", s)
        if not m:
            return None
        year = datetime.date.today().year
        month, day = int(m.group(1)), int(m.group(2))
    try:
        return datetime.date(year, month, day).isoformat()
    except ValueError:
        return None


def _scan_dates(text: str) -> List[str]:
    out: List[str] = []
    for raw in _DATE_RE.findall(text):
        iso = _normalize_date(raw)
        if iso and iso not in out:
            out.append(iso)
    return out


def _heuristic(
    title: str, content: str, items: Optional[str], info_type: Optional[str]
) -> dict:
    text = "\n".join([title or "", content or "", items or ""])

    # 種別: 明示があり妥当ならそれを尊重、無ければ推定
    it = info_type if info_type in INFO_TYPES else None
    if not it:
        if items and items.strip():
            it = "持ち物"
        elif any(k in text for k in ["運動会", "発表会", "遠足", "行事", "イベント", "参観", "プール"]):
            it = "行事"
        elif "給食" in text or "献立" in text:
            it = "給食"
        elif "休園" in text or "休み" in text:
            it = "休園変更"
        elif any(k in text for k in ["提出", "申込", "申し込み", "返却", "集金"]):
            it = "提出物"
        elif "掲示" in text:
            it = "掲示"
        else:
            it = "お知らせ"

    # 優先度
    if any(k in text for k in _HIGH_PRIORITY_KW):
        pr = "高"
    elif any(k in text for k in _LOW_PRIORITY_KW):
        pr = "低"
    else:
        pr = "普通"

    # 日付
    dates = _scan_dates(text)
    date = dates[0] if dates else None
    due_date = None
    event_date = None
    if dates and any(k in text for k in _DUE_KW):
        due_date = dates[-1]
    if it == "行事" and dates:
        event_date = dates[0]

    # タグ
    tags = [k for k in _TAG_KEYWORDS if k in text]

    return {
        "info_type": it,
        "priority": pr,
        "date": date,
        "due_date": due_date,
        "event_date": event_date,
        "tags": tags,
    }


def _extract_json(text: str) -> dict:
    """LLM 応答テキストから最初の JSON オブジェクトを取り出してパースする。"""
    if not text:
        raise ValueError("empty LLM response")
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no JSON object in LLM response")
    return json.loads(text[start : end + 1])


def _llm_suggest(title: str, content: str, items: Optional[str]) -> dict:
    """Gemini / Vertex AI で構造化推定する。失敗時は例外を投げる（呼び出し側でフォールバック）。"""
    client = ai_client.get_genai_client()
    model = ai_client.get_model_name()
    prompt = (
        "あなたは保育園のお知らせを正確に分類するアシスタントです。"
        "以下の本文から登録用メタデータを推定し、JSONのみを出力してください。\n\n"
        f"## info_type（必ず次のいずれか1つ）: {INFO_TYPES}\n"
        "各種別の定義:\n"
        "- 資料: 園だより・クラスだより等の配布おたより/資料で、提出や持参を求めないもの。\n"
        "- 掲示: 園内の掲示板・掲示物の内容（その場で読むもの。配布物ではない）。\n"
        "- 行事: 運動会・発表会・遠足・参観・面談・プール・誕生日会など行事/イベントの案内。\n"
        "- 持ち物: 特定の物を持参・準備するよう求めるもの（持ち物リストが主目的）。\n"
        "- 提出物: 書類・申込・集金・返却など、提出や締切を伴うもの。\n"
        "- お知らせ: 上記いずれにも明確に当てはまらない一般連絡・周知。\n"
        "- 給食: 給食・献立・食物アレルギーなど食事関連。\n"
        "- 休園変更: 休園・休み・開園/登園時間や登園日の変更など予定変更。\n"
        "判別の優先順位（複数該当する場合は上から順に適用）:\n"
        "1. 提出/締切/申込/集金/返却があれば「提出物」。\n"
        "2. 物の持参・準備の指示が主目的なら「持ち物」。\n"
        "3. 行事/イベントの案内なら「行事」。\n"
        "4. 給食/献立なら「給食」。\n"
        "5. 休園/時間変更/登園日変更なら「休園変更」。\n"
        "6. 掲示物なら「掲示」、配布おたより/資料なら「資料」。\n"
        "7. それ以外は「お知らせ」。\n\n"
        f"## priority（次のいずれか）: {PRIORITY_TYPES}\n"
        "締切・至急・必須など緊急性が高ければ「高」、任意・参考程度なら「低」、通常は「普通」。\n\n"
        "## 日付\n"
        "- date: 主要な日付 (YYYY-MM-DD) または null\n"
        "- due_date: 提出/締切の日付 (YYYY-MM-DD) または null\n"
        "- event_date: 行事の日付 (YYYY-MM-DD) または null\n"
        "- tags: 内容を表す日本語の短いタグ配列 (最大6個)\n\n"
        "## 分類例\n"
        "本文「上履きを月曜日に持たせてください」"
        '→ {"info_type":"持ち物","priority":"普通","date":null,"due_date":null,"event_date":null,"tags":["上履き","持ち物"]}\n'
        "本文「健康調査票を4月20日までに提出してください」"
        '→ {"info_type":"提出物","priority":"高","date":"2026-04-20","due_date":"2026-04-20","event_date":null,"tags":["提出","健康調査票"]}\n'
        "本文「5月1日に運動会を行います。お弁当をご持参ください」"
        '→ {"info_type":"行事","priority":"普通","date":"2026-05-01","due_date":null,"event_date":"2026-05-01","tags":["運動会","お弁当"]}\n\n'
        f"# タイトル\n{title}\n\n# 内容\n{content}\n\n# 持ち物\n{items or ''}\n\n"
        "# 出力(JSONのみ)"
    )
    cfg = ai_client.default_generate_config()

    def _gen():
        if cfg is not None:
            return client.models.generate_content(
                model=model, contents=prompt, config=cfg
            )
        return client.models.generate_content(model=model, contents=prompt)

    response = ai_client.with_retry(_gen)
    text = (getattr(response, "text", "") or "").strip()
    return _extract_json(text)


def suggest_metadata(
    title: str,
    content: str,
    items: Optional[str] = None,
    info_type: Optional[str] = None,
) -> dict:
    """登録用メタデータ（種別/優先度/日付/期限/行事日/タグ）を推定して返す。

    返り値には推定の出所を示す ``source`` ("ai" | "heuristic") を含む。
    """
    base = _heuristic(title, content, items, info_type)

    if not ai_client.gemini_available():
        base["source"] = "heuristic"
        return base

    try:
        ai = _llm_suggest(title, content, items)
    except Exception as e:  # graceful degradation
        logger.warning("LLM auto-tagging failed, falling back to heuristic: %s", e)
        base["source"] = "heuristic"
        return base

    merged = dict(base)
    if ai.get("info_type") in INFO_TYPES:
        merged["info_type"] = ai["info_type"]
    if ai.get("priority") in PRIORITY_TYPES:
        merged["priority"] = ai["priority"]
    for key in ("date", "due_date", "event_date"):
        norm = _normalize_date(ai.get(key))
        if norm:
            merged[key] = norm
    if isinstance(ai.get("tags"), list):
        tags = [str(t).strip()[:20] for t in ai["tags"] if str(t).strip()]
        if tags:
            merged["tags"] = tags[:6]
    merged["source"] = "ai"
    return merged
