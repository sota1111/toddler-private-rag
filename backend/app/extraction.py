"""5カテゴリ構造化抽出 (SOT-1085 / SOT-1092).

保育園のお知らせ本文から、保護者が行動するための5カテゴリを抽出する:
- submissions (提出物)
- belongings (持ち物)
- deadlines (締切)
- events    (行事予定)
- notes     (注意事項)

Gemini / Vertex AI クライアントが利用可能なら LLM で構造化抽出し、失敗時・オフライン時は
決定的なヒューリスティックにフォールバックする。テスト・オフラインでは常にヒューリスティックになる。
"""

import json
import logging
import re
from typing import Dict, List, Optional

from . import ai_client

logger = logging.getLogger(__name__)

# スキーマと一致させる5カテゴリのキー
CATEGORY_KEYS = ["submissions", "belongings", "deadlines", "events", "notes"]

# カテゴリ見出しの日本語ラベル（整理本文へ付与するセクション用）
CATEGORY_LABELS = {
    "submissions": "提出物",
    "belongings": "持ち物",
    "deadlines": "締切",
    "events": "行事予定",
    "notes": "注意事項",
}

# 各カテゴリの判定キーワード（行単位のヒューリスティックで使用）
_SUBMISSION_KW = ["提出", "申込", "申し込み", "返却", "署名", "サイン", "記入", "集金", "納入", "回収"]
_BELONGING_KW = ["持ち物", "持参", "用意", "準備するもの", "お弁当", "水筒", "着替え", "タオル", "帽子", "上履き"]
_DEADLINE_KW = ["締切", "締め切り", "〆切", "期限", "まで", "期日"]
_EVENT_KW = ["運動会", "発表会", "遠足", "参観", "面談", "プール", "行事", "イベント", "誕生日会", "懇談会", "避難訓練", "卒園", "入園"]
_NOTE_KW = ["注意", "ご注意", "お願い", "禁止", "厳禁", "控え", "ご了承", "ご協力", "気をつけ", "ご留意"]

# 行頭の箇条書き記号
_BULLET_RE = re.compile(r"^[・\-*●○〇•\d]+[.)、:：]?\s*")
# 日付らしさ（締切/行事の補助判定）
_DATE_RE = re.compile(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}月\d{1,2}日)")


def _clean_line(line: str) -> str:
    return _BULLET_RE.sub("", line.strip()).strip()


def _heuristic_categories(raw_text: str) -> Dict[str, List[str]]:
    """本文を行単位で走査し、キーワードで5カテゴリに振り分ける（決定的）。"""
    result: Dict[str, List[str]] = {k: [] for k in CATEGORY_KEYS}
    if not raw_text:
        return result

    current_section: Optional[str] = None
    for raw_line in raw_text.splitlines():
        line = _clean_line(raw_line)
        if not line:
            continue

        # 見出し行はセクション文脈を切り替える（後続の項目をそのカテゴリに寄せる）
        if any(k in line for k in _BELONGING_KW) and len(line) <= 12:
            current_section = "belongings"
        elif "提出" in line and len(line) <= 12:
            current_section = "submissions"
        elif "注意" in line and len(line) <= 12:
            current_section = "notes"

        has_date = bool(_DATE_RE.search(line))
        bucket: Optional[str] = None
        if any(k in line for k in _DEADLINE_KW):
            bucket = "deadlines"
        elif any(k in line for k in _EVENT_KW):
            bucket = "events"
        elif any(k in line for k in _SUBMISSION_KW):
            bucket = "submissions"
        elif any(k in line for k in _BELONGING_KW):
            bucket = "belongings"
        elif any(k in line for k in _NOTE_KW):
            bucket = "notes"
        elif current_section:
            bucket = current_section
        elif has_date:
            bucket = "events"

        if bucket and line not in result[bucket]:
            result[bucket].append(line)

    return result


def _extract_json(text: str) -> dict:
    """LLM 応答テキストから最初の JSON オブジェクトを取り出してパースする。"""
    if not text:
        raise ValueError("empty LLM response")
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no JSON object in LLM response")
    return json.loads(text[start : end + 1])


def _llm_categories(raw_text: str) -> Dict[str, List[str]]:
    """Gemini / Vertex AI で5カテゴリを抽出する。失敗時は例外を投げる（呼び出し側でフォールバック）。"""
    client = ai_client.get_genai_client()
    model = ai_client.get_model_name()
    prompt = (
        "あなたは保育園のお知らせから保護者の行動項目を抽出するアシスタントです。"
        "以下の本文から次の5カテゴリを抽出し、JSONのみを出力してください。"
        "各値は短い日本語の文字列の配列とし、該当が無ければ空配列にしてください。\n"
        "- submissions: 提出物（提出・申込・返却・記入が必要なもの）\n"
        "- belongings: 持ち物（当日持参・用意するもの）\n"
        "- deadlines: 締切（締切・期限・〆切。可能なら日付を含める）\n"
        "- events: 行事予定（運動会・遠足等の行事。可能なら日付を含める）\n"
        "- notes: 注意事項（注意・お願い・禁止事項など）\n\n"
        f"# 本文\n{raw_text}\n\n"
        '# 出力例\n{"submissions":["健康調査票"],"belongings":["水着","タオル"],'
        '"deadlines":["5月1日まで"],"events":["5月10日 運動会"],"notes":["車での来園は禁止"]}\n\n'
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
    data = _extract_json(text)

    out: Dict[str, List[str]] = {k: [] for k in CATEGORY_KEYS}
    for key in CATEGORY_KEYS:
        val = data.get(key)
        if isinstance(val, list):
            out[key] = [str(v).strip()[:120] for v in val if str(v).strip()][:12]
    return out


def extract_categories(raw_text: str) -> Dict[str, List[str]]:
    """5カテゴリ（提出物/持ち物/締切/行事予定/注意事項）を抽出して返す。

    LLM が利用可能なら LLM 結果を優先し、空カテゴリはヒューリスティックで補完する。
    LLM が使えない/失敗した場合はヒューリスティックのみを返す。常に5キーを持つ。
    """
    base = _heuristic_categories(raw_text)

    if not raw_text or not raw_text.strip() or not ai_client.gemini_available():
        return base

    try:
        ai = _llm_categories(raw_text)
    except Exception as e:  # graceful degradation
        logger.warning("LLM category extraction failed, using heuristic: %s", e)
        return base

    # LLM 結果を優先しつつ、空カテゴリはヒューリスティックで補う
    merged: Dict[str, List[str]] = {}
    for key in CATEGORY_KEYS:
        merged[key] = ai.get(key) or base.get(key, [])
    return merged


def _heuristic_organize(raw_text: str) -> str:
    """OCR生テキストを決定的に整形する（前後空白除去・連続空行の圧縮）。

    LLM が使えない/失敗した場合のフォールバック。原文の内容は変えず、見た目の
    ノイズ（余分な空白・連続する空行）のみ取り除いて読みやすくする。
    """
    cleaned: List[str] = []
    prev_blank = False
    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            # 連続する空行は1つに圧縮し、先頭の空行は捨てる
            if cleaned and not prev_blank:
                cleaned.append("")
                prev_blank = True
            continue
        cleaned.append(line)
        prev_blank = False
    # 末尾の空行を除去
    while cleaned and cleaned[-1] == "":
        cleaned.pop()
    return "\n".join(cleaned)


def _format_category_section(categories: Dict[str, List[str]]) -> str:
    """空でないカテゴリのみ、見出し付き箇条書きのセクション文字列を組み立てる。"""
    parts: List[str] = []
    for key in CATEGORY_KEYS:
        values = [str(v).strip() for v in (categories.get(key) or []) if str(v).strip()]
        if not values:
            continue
        parts.append(f"【{CATEGORY_LABELS[key]}】")
        parts.extend(f"・{v}" for v in values)
    return "\n".join(parts)


def _llm_organize(raw_text: str) -> str:
    """Gemini / Vertex AI でOCR生テキストを読みやすい本文へ整形する。失敗時は例外。"""
    client = ai_client.get_genai_client()
    model = ai_client.get_model_name()
    prompt = (
        "あなたは保育園のお知らせOCRテキストを整える編集者です。"
        "次のOCR生テキストを、保護者が読みやすいお知らせ本文に整理してください。"
        "OCRの不自然な改行・重複・崩れた記号を取り除き、要点を簡潔にまとめます。"
        "原文に無い情報を追加・推測しないでください。本文のみを出力し、前置きや説明は不要です。\n\n"
        f"# OCR生テキスト\n{raw_text}\n\n# 整理した本文"
    )
    cfg = ai_client.default_generate_config(max_output_tokens=4096)

    def _gen():
        if cfg is not None:
            return client.models.generate_content(
                model=model, contents=prompt, config=cfg
            )
        return client.models.generate_content(model=model, contents=prompt)

    response = ai_client.with_retry(_gen)
    return (getattr(response, "text", "") or "").strip()


def organize_body(raw_text: str) -> str:
    """OCR生テキストを整形した「本文のみ」を返す（カテゴリ見出しは付けない）。

    LLM が利用可能なら本文整形を試み、失敗時・オフライン時は決定的なヒューリスティック整形に
    フォールバックする。``raw_text`` が空なら空文字を返す。カテゴリ抽出に依存しないため、
    ``extract_categories`` / タイトル整形と並列実行できる (SOT-1292)。
    """
    if not raw_text or not raw_text.strip():
        return ""

    body = ""
    if ai_client.gemini_available():
        try:
            body = _llm_organize(raw_text)
        except Exception as e:  # graceful degradation
            logger.warning("LLM content organize failed, using heuristic: %s", e)
            body = ""
    if not body:
        body = _heuristic_organize(raw_text)
    return body


def format_category_section(categories: Dict[str, List[str]]) -> str:
    """空でないカテゴリのみ、見出し付き箇条書きのセクション文字列を組み立てる。"""
    return _format_category_section(categories)


def organize_content(
    raw_text: str, categories: Optional[Dict[str, List[str]]] = None
) -> str:
    """OCR文字起こしを「登録できる形」に整理した本文を返す (SOT-1214)。

    LLM が利用可能なら本文整形を試み、失敗時・オフライン時は決定的なヒューリスティック整形に
    フォールバックする。``categories`` が与えられれば（無ければ内部で抽出して）整理本文の末尾に
    空でないカテゴリのみ見出し付き箇条書きで付与する。``raw_text`` が空なら空文字を返す。
    """
    if not raw_text or not raw_text.strip():
        return ""

    body = organize_body(raw_text)

    if categories is None:
        categories = extract_categories(raw_text)
    section = format_category_section(categories)
    if section:
        return f"{body}\n\n{section}" if body else section
    return body
