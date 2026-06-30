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

import datetime
import hashlib
import json
import logging
import re
from typing import Dict, List, Optional

from . import ai_client, clock
from .concurrency import BoundedCache

logger = logging.getLogger(__name__)

# SOT-1374 / B: LLM 結果のプロセス内キャッシュ。同一入力の高コストな LLM 呼び出し
# (翻訳・enrich) を再計算しないために使う。キーは入力テキスト+言語のハッシュ。
_LLM_RESULT_CACHE = BoundedCache(maxsize=128)


def _llm_cache_key(kind: str, text: str, language: str) -> str:
    digest = hashlib.sha256((text or "").encode("utf-8")).hexdigest()
    return f"{kind}:{language}:{digest}"

# スキーマと一致させる5カテゴリのキー（LLM抽出の対象）
CATEGORY_KEYS = ["submissions", "belongings", "deadlines", "events", "notes"]

# その他（どのカテゴリにも該当しない事項。RAGから漏らさないための受け皿 SOT-1294）
OTHER_KEY = "other"

# 構造化content（RAG対象兼表示用）に出力する全カテゴリ。5カテゴリ＋その他。
ALL_CONTENT_KEYS = CATEGORY_KEYS + [OTHER_KEY]

# フロント (InfoCreatePage) の選択肢と一致させる種別一覧
INFO_TYPES = ["資料", "掲示", "行事", "持ち物", "提出物", "お知らせ", "給食", "休園変更"]

# カテゴリ見出しの日本語ラベル（整理本文へ付与するセクション用）
CATEGORY_LABELS = {
    "submissions": "提出物",
    "belongings": "持ち物",
    "deadlines": "締切",
    "events": "行事予定",
    "notes": "注意事項",
    "other": "その他",
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
    """本文を行単位で走査し、キーワードで5カテゴリ＋その他に振り分ける（決定的）。

    どのキーワード／セクション文脈にも当てはまらない非空行は ``other``（その他）に収容し、
    RAG対象の構造化contentから漏れないようにする (SOT-1294)。返り値は常に6キーを持つ。
    """
    result: Dict[str, List[str]] = {k: [] for k in ALL_CONTENT_KEYS}
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
        else:
            # どのカテゴリにも該当しない行は「その他」へ（RAGから漏らさない SOT-1294）
            bucket = OTHER_KEY

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


def _extract_json_array(text: str) -> list:
    """LLM 応答テキストから最初の JSON 配列を取り出してパースする (SOT-1307)。"""
    if not text:
        raise ValueError("empty LLM response")
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no JSON array in LLM response")
    return json.loads(text[start : end + 1])


def _llm_categories(raw_text: str, language: str = "ja") -> dict:
    """Gemini / Vertex AI でタイトル＋5カテゴリを抽出する。失敗時は例外を投げる（呼び出し側でフォールバック）。

    返り値は5カテゴリ(list) に加えて ``title``(str) を含む dict。
    ``language`` は生成する ``title`` の出力言語（既定 ja, SOT-1336）。カテゴリ値の言語は変更しない。
    """
    client = ai_client.get_genai_client()
    model = ai_client.get_model_name()
    language_name = _LANGUAGE_NAMES.get(language, _LANGUAGE_NAMES["ja"])
    prompt = (
        "あなたは保育園のお知らせからタイトルと保護者の行動項目を抽出するアシスタントです。"
        "以下の本文からタイトルと次の5カテゴリを抽出し、JSONのみを出力してください。\n"
        f"- title: お知らせ全体の簡潔なタイトル（{language_name}で1行、20文字程度まで）\n"
        "各カテゴリの値は短い日本語の文字列の配列とし、該当が無ければ空配列にしてください。\n"
        "- submissions: 提出物（提出・申込・返却・記入が必要なもの）\n"
        "- belongings: 持ち物（当日持参・用意するもの）\n"
        "- deadlines: 締切（締切・期限・〆切。可能なら日付を含める）\n"
        "- events: 行事予定（運動会・遠足等の行事。可能なら日付を含める）\n"
        "- notes: 注意事項（注意・お願い・禁止事項など）\n"
        "- other: その他（上記5カテゴリのどれにも当てはまらないが本文に含まれる事項。"
        "情報を漏らさないため、分類できない内容は必ずここに入れる）\n\n"
        f"# 本文\n{raw_text}\n\n"
        '# 出力例\n{"title":"プール開きのお知らせ","submissions":["健康調査票"],'
        '"belongings":["水着","タオル"],"deadlines":["5月1日まで"],'
        '"events":["5月10日 運動会"],"notes":["車での来園は禁止"],'
        '"other":["駐車場は北側を利用"]}\n\n'
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

    out: dict = {k: [] for k in ALL_CONTENT_KEYS}
    for key in ALL_CONTENT_KEYS:
        val = data.get(key)
        if isinstance(val, list):
            out[key] = [str(v).strip()[:120] for v in val if str(v).strip()][:12]
    title = data.get("title")
    out["title"] = str(title).strip().splitlines()[0][:40] if title and str(title).strip() else ""
    return out


def extract_categories(raw_text: str) -> Dict[str, List[str]]:
    """5カテゴリ＋その他（提出物/持ち物/締切/行事予定/注意事項/その他）を抽出して返す。

    LLM が利用可能なら LLM 結果を優先し、空カテゴリはヒューリスティックで補完する。
    LLM が使えない/失敗した場合はヒューリスティックのみを返す。常に6キー（5＋other）を持つ (SOT-1294)。
    """
    base = _heuristic_categories(raw_text)

    if not raw_text or not raw_text.strip() or not ai_client.gemini_available():
        return base

    try:
        ai = _llm_categories(raw_text)
    except Exception as e:  # graceful degradation
        logger.warning("LLM category extraction failed, using heuristic: %s", e)
        return base

    # LLM 結果を優先しつつ、空カテゴリはヒューリスティックで補う（other含む）
    merged: Dict[str, List[str]] = {}
    for key in ALL_CONTENT_KEYS:
        merged[key] = ai.get(key) or base.get(key, [])
    return merged


def extract_titled_categories(raw_text: str, language: str = "ja") -> dict:
    """タイトル＋5カテゴリを1回のLLM呼び出しでまとめて抽出する (SOT-1292)。

    enrich を AI 1呼び出しに集約するための関数。返り値は ``title``(str) と5カテゴリ(list) を持つ dict。
    LLM が利用可能なら ``_llm_categories`` を1回だけ呼び、空カテゴリはヒューリスティックで補完する。
    LLM が使えない/失敗した場合は ``title=""`` ＋ ヒューリスティック5カテゴリを返す（例外は投げない）。
    ``language`` は生成する ``title`` の出力言語（既定 ja, SOT-1336）。
    """
    base = _heuristic_categories(raw_text)
    result: dict = {"title": "", **{k: base.get(k, []) for k in ALL_CONTENT_KEYS}}

    if not raw_text or not raw_text.strip() or not ai_client.gemini_available():
        return result

    try:
        ai = _llm_categories(raw_text, language)
    except Exception as e:  # graceful degradation
        logger.warning("LLM titled-category extraction failed, using heuristic: %s", e)
        return result

    result["title"] = ai.get("title") or ""
    for key in ALL_CONTENT_KEYS:
        result[key] = ai.get(key) or base.get(key, [])
    return result


def build_structured_content(categories: Dict[str, List[str]]) -> str:
    """整形済みカテゴリから、RAG対象兼表示用の構造化テキストを組み立てる (SOT-1292)。

    空でないカテゴリのみ見出し付き箇条書き（``【提出物】\\n・xxx`` 形式）で返す。全カテゴリが空なら空文字。
    """
    return _format_category_section(categories)


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
    """空でないカテゴリのみ、見出し付き箇条書きのセクション文字列を組み立てる。

    5カテゴリに加え「その他」(SOT-1294) も末尾に出力し、未分類の事項を RAG content に残す。
    """
    parts: List[str] = []
    for key in ALL_CONTENT_KEYS:
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


# --- draft フィールド生成 (SOT-1293) ------------------------------------------
# 「OCR安全テキスト → 仮登録(draft)フィールド」化のロジックを、ルータ(`/info/extract`)と
# 写真アップロード後のサーバ側 background task の両方から呼べる純関数として提供する。


def normalize_date(raw: Optional[str]) -> Optional[str]:
    """検出した日付文字列をベストエフォートで ISO (YYYY-MM-DD) に正規化する。

    対応: YYYY-MM-DD / YYYY/M/D / M月D日 (年は当年と仮定)。
    確実に解釈できない場合は None を返す。
    """
    if not raw:
        return None
    s = raw.strip()

    m = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$", s)
    if m:
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.match(r"^(\d{1,2})月(\d{1,2})日$", s)
        if not m:
            return None
        year = clock.today().year
        month, day = int(m.group(1)), int(m.group(2))

    try:
        return datetime.date(year, month, day).isoformat()
    except ValueError:
        return None


def guess_info_type(text: str, has_items: bool) -> str:
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


# SOT-1407: 締め切り調査(提出書類の期限調査)が必要そうなタスクかを判定するヒューリスティック。
_DEADLINE_INVESTIGATION_KEYWORDS = (
    "提出", "証明書", "申請", "書類", "届", "様式", "記入", "捺印", "押印",
    "submit", "submission", "certificate", "application", "form",
)


def needs_deadline_investigation(info_type: str, text: str) -> bool:
    """このタスクが締め切り調査(提出書類の準備)を要するかを推定する (SOT-1407)。

    info_type が「提出物」、または本文/タイトルに提出書類系のキーワードが含まれるとき True。
    """
    if info_type == "提出物":
        return True
    blob = text or ""
    lowered = blob.lower()
    return any((kw in blob) or (kw in lowered) for kw in _DEADLINE_INVESTIGATION_KEYWORDS)


def draft_title(text: str) -> str:
    """安全テキストの先頭の非空行をタイトルにする（最大40文字）。"""
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line[:40]
    return "写真から登録"


def build_draft_fields(
    safe_text: str,
    detected_dates: Optional[List[str]] = None,
    detected_items: Optional[List[str]] = None,
    language: str = "ja",
) -> dict:
    """OCR安全テキストから仮登録(draft)用のフィールド一式を生成する (SOT-1293)。

    返り値 dict のキー:
    - title: タイトル(空ならヒューリスティック)
    - info_type: INFO_TYPES のいずれか
    - content: 整形済みカテゴリの構造化テキスト(全カテゴリ空なら safe_text にフォールバック)。RAG対象。
    - items: 検出した持ち物を改行連結("")
    - date: 検出日付の最初に解釈できたISO("")
    - categories: ExtractedCategories 構築用 dict(title + 5カテゴリ + その他)
    """
    detected_dates = detected_dates or []
    detected_items = detected_items or []
    safe_text = safe_text or ""

    # SOT-1374 / B: 同一入力(本文+検出日付/持ち物+言語)の draft フィールド生成結果は
    # キャッシュから返す。内部の enrich(LLM, extract_titled_categories)を省ける。
    cache_key = _llm_cache_key(
        "draft_fields",
        safe_text + "\x1f" + "|".join(detected_dates) + "\x1f" + "|".join(detected_items),
        language,
    )
    cached = _LLM_RESULT_CACHE.get(cache_key)
    if cached is not None:
        return dict(cached)

    date_iso: Optional[str] = None
    for d in detected_dates:
        date_iso = normalize_date(d)
        if date_iso:
            break

    items = "\n".join(detected_items) if detected_items else ""
    info_type = guess_info_type(safe_text, bool(detected_items))
    heuristic_title = draft_title(safe_text)
    content_text = safe_text

    # OCR後の整理(enrich)は「タイトル＋5カテゴリ抽出」を AI 1呼び出しに集約する (SOT-1292)。
    # extract_titled_categories は LLM 不可/失敗時もヒューリスティックに落ちて例外を投げない。
    try:
        enriched = extract_titled_categories(safe_text, language)
    except Exception as e:  # graceful degradation
        logger.warning("Enrich (titled categories) failed in build_draft_fields: %s", e)
        enriched = {"title": ""}

    title = (enriched.get("title") or "").strip()[:40] or heuristic_title
    # SOT-1329: 文字起こし後のカテゴリ分類(【提出物】等の見出し付き本文)は廃止する。
    # content は分類せずプレーンな文字起こし本文(safe_text)のままにする。
    # （title 抽出と categories キーは /info/extract の互換のため維持する。）
    category_dict = {k: enriched.get(k, []) for k in ALL_CONTENT_KEYS}

    final_info_type = info_type if info_type in INFO_TYPES else "資料"
    result = {
        "title": title,
        "info_type": final_info_type,
        "content": content_text,
        "items": items,
        "date": date_iso or "",
        # SOT-1407: 締め切り調査が必要なタスクか（タイトル+本文から推定）。
        "needs_deadline_investigation": needs_deadline_investigation(
            final_info_type, f"{title}\n{content_text}"
        ),
        "categories": {"title": title, **category_dict},
    }
    _LLM_RESULT_CACHE.set(cache_key, dict(result))
    return result


# --- タスクごとの仮登録(draft)生成 (SOT-1307 / 案B) ----------------------------
# 文字起こし(OCR/enrich)結果を「タスク(行動項目)」単位に分割し、各タスクを1件の draft
# フィールド dict にする。各 draft は build_draft_fields と同形のキー集合に加えて
# ``event_date``（タスクの予定日 ISO or ""）を必ず持つ。仮登録画面では各 draft レコードを
# 個別に編集・登録・削除できる（既存UIを流用）。

# タスクのカテゴリ(submissions/...) を保育園情報の種別(INFO_TYPES)へ写像する。
_CATEGORY_INFO_TYPE = {
    "events": "行事",
    "belongings": "持ち物",
    "submissions": "提出物",
    "deadlines": "お知らせ",
    "notes": "お知らせ",
}

# 1写真から作るタスク(=draft)の上限。誤検出が大量の draft になるのを防ぐ。
_MAX_TASKS = 8


# SOT-1315: タスク登録の出力言語。設定画面の言語に合わせて title/detail を生成する。
_LANGUAGE_NAMES = {"ja": "日本語", "en": "English"}


def translate_text(text: str, language: str = "ja") -> str:
    """文字起こし(OCR原文)を、内容を変えずに ``language`` の言語へ翻訳する (SOT-1325)。

    「言語のみ設定言語で表示する」ための翻訳。意味・構成・改行・順序は保ち、要約や
    並べ替え・追記・削除は行わない（言語だけを変換する）。

    LLM が使えない / 入力が空 / 失敗・空応答のときは、入力テキストをそのまま返す
    （決して例外を投げない）。
    """
    if not text or not text.strip():
        return text
    language_name = _LANGUAGE_NAMES.get(language, _LANGUAGE_NAMES["ja"])
    if not ai_client.gemini_available():
        return text

    # SOT-1374 / B: 同一テキスト+言語の翻訳結果はキャッシュから返す。
    cache_key = _llm_cache_key("translate", text, language)
    cached = _LLM_RESULT_CACHE.get(cache_key)
    if cached is not None:
        return cached

    try:
        client = ai_client.get_genai_client()
        model = ai_client.get_model_name()
        prompt = (
            f"Translate the following text into {language_name}. "
            "Preserve the meaning, content, and structure (line breaks and order) exactly; "
            "change only the language. "
            "Do not summarize, reorder, add, or remove any information. "
            f"If the text is already written in {language_name}, output it unchanged. "
            "Output only the translated text, with no preamble, explanation, or surrounding quotes.\n\n"
            f"# Text\n{text}\n\n"
            f"# Translation ({language_name})"
        )
        cfg = ai_client.default_generate_config(max_output_tokens=4096)

        def _gen():
            if cfg is not None:
                return client.models.generate_content(
                    model=model, contents=prompt, config=cfg
                )
            return client.models.generate_content(model=model, contents=prompt)

        response = ai_client.with_retry(_gen)
        translated = (getattr(response, "text", "") or "").strip()
        result = translated or text
        _LLM_RESULT_CACHE.set(cache_key, result)
        return result
    except Exception as e:  # graceful degradation
        logger.warning("translate_text failed, returning original text: %s", e)
        return text


def _llm_tasks(raw_text: str, language: str = "ja") -> List[dict]:
    """Gemini / Vertex AI で本文をタスク(行動項目)ごとに分割する。失敗時は例外。

    返り値は ``{title, date, detail, category}`` の dict のリスト。
    ``language`` は生成する title/detail の出力言語（既定 ja）。
    """
    client = ai_client.get_genai_client()
    model = ai_client.get_model_name()
    language_name = _LANGUAGE_NAMES.get(language, _LANGUAGE_NAMES["ja"])
    prompt = (
        "You are an assistant that extracts the tasks (action items / scheduled events / deadlines) "
        "a parent must handle from a nursery-school notice. "
        "Split the body below into individual tasks and output ONLY a JSON array. "
        "Use one element per action, event, or deadline. If none apply, return an empty array [].\n"
        "If several details concern the SAME event on the SAME date (for example an event together with "
        "its belongings, dress code, or requests), output them as ONE element whose detail combines that "
        "information — do NOT split a single event into multiple elements.\n"
        "Each element has this shape:\n"
        '{"title":"a short heading of about 20 characters",'
        '"date":"the scheduled/due date if known, as M月D日 or YYYY-MM-DD; empty string if unknown",'
        '"detail":"the content (body) of that task",'
        '"category":"one of submissions|belongings|deadlines|events|notes|other"}\n'
        "Do not infer or add any information that is not present in the source text.\n"
        f"Write title and detail in {language_name} (keep the category value as the specified English code).\n\n"
        f"# Body\n{raw_text}\n\n"
        "# Example output\n"
        '[{"title":"運動会","date":"5月10日","detail":"5月10日に運動会を開催します","category":"events"},'
        '{"title":"健康調査票の提出","date":"5月1日","detail":"申込書は5月1日までにご提出ください","category":"submissions"}]\n\n'
        "# Output (JSON array only)"
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
    data = _extract_json_array(text)

    tasks: List[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip().splitlines()[0][:40] if item.get("title") else ""
        date = str(item.get("date", "")).strip()
        detail = str(item.get("detail", "")).strip()
        category = str(item.get("category", "")).strip()
        if category not in ALL_CONTENT_KEYS:
            category = OTHER_KEY
        if not (title or detail):
            continue
        tasks.append({"title": title, "date": date, "detail": detail, "category": category})
    return tasks[:_MAX_TASKS]


def _task_to_draft(task: dict, safe_text: str) -> dict:
    """1タスク dict を draft フィールド dict（build_draft_fields と同形 + event_date）に写像する。"""
    category = task.get("category") if task.get("category") in ALL_CONTENT_KEYS else OTHER_KEY
    detail = (task.get("detail") or "").strip()
    title = (task.get("title") or "").strip()[:40] or draft_title(detail or safe_text)
    event_iso = normalize_date(task.get("date")) or ""
    is_belonging = category == "belongings"

    if category in _CATEGORY_INFO_TYPE:
        info_type = _CATEGORY_INFO_TYPE[category]
    else:
        info_type = guess_info_type(detail or safe_text, is_belonging)
    if info_type not in INFO_TYPES:
        info_type = "資料"

    items = detail if is_belonging else ""
    # SOT-1329: タスク本文をカテゴリ分類(【提出物】等)せず、プレーンなタスク本文にする。
    content = detail or safe_text
    category_dict = {k: [] for k in ALL_CONTENT_KEYS}

    return {
        "title": title,
        "info_type": info_type,
        "content": content,
        "items": items,
        "date": "",
        "event_date": event_iso,
        # SOT-1407: 締め切り調査が必要なタスクか（タイトル+本文から推定）。
        "needs_deadline_investigation": needs_deadline_investigation(
            info_type, f"{title}\n{content}"
        ),
        "categories": {"title": title, **category_dict},
    }


def _single_task_fallback(
    safe_text: str,
    detected_dates: Optional[List[str]],
    detected_items: Optional[List[str]],
) -> dict:
    """タスク分割ができない場合の後方互換 draft（従来の単一 draft に event_date キーを補う）。"""
    fields = build_draft_fields(safe_text, detected_dates, detected_items)
    fields.setdefault("event_date", "")
    fields.setdefault("needs_deadline_investigation", False)
    return fields


# SOT-1350: 同一日・同一イベントのタスクを1件に統合する後処理。
# 共通接頭辞がこの文字数以上のとき「同じイベント」とみなす（過剰マージを防ぐ保守的な閾値）。
_EVENT_MERGE_MIN_PREFIX = 3

# 統合時に採用する代表 category の優先順位（events を最優先 → info_type 行事になる）。
_MERGE_CATEGORY_PRIORITY = ["events", "submissions", "belongings", "deadlines", "notes", OTHER_KEY]


def _normalized_event_key(title: Optional[str]) -> str:
    """イベント名比較用に title から空白・記号類を除いた正規化キーを返す。"""
    raw = (title or "").strip()
    return "".join(ch for ch in raw if not ch.isspace() and ch not in "・,，、.。:：;；/／-ー()（）[]【】")


def _common_prefix_len(a: str, b: str) -> int:
    """2文字列の longest common prefix の長さ（文字数）。"""
    n = 0
    for ca, cb in zip(a, b):
        if ca != cb:
            break
        n += 1
    return n


def _consolidate_tasks(tasks: List[dict]) -> List[dict]:
    """同一 event_date かつ同一イベント名のタスクを1件へ統合する (SOT-1350)。

    - 日付（normalize_date 結果）が空のタスクは決してマージしない（同一日と確認できないため）。
    - 正規化イベント名の共通接頭辞が ``_EVENT_MERGE_MIN_PREFIX`` 文字以上、かつ
      正規化日付キーが等しいタスク同士を同一イベントとみなす。
    - 入力順を保ち、貪欲(greedy)にグルーピングする。LLM 呼び出しや I/O は行わない純関数。
    """
    groups: List[dict] = []  # {"date_key", "event_key", "tasks": [...]}
    for task in tasks:
        date_key = normalize_date(task.get("date")) or ""
        event_key = _normalized_event_key(task.get("title"))
        placed = False
        if date_key:  # 日付不明はマージ対象外
            for group in groups:
                if group["date_key"] != date_key:
                    continue
                gk = group["event_key"]
                if not (event_key and gk):
                    continue
                prefix = _common_prefix_len(event_key, gk)
                if prefix >= _EVENT_MERGE_MIN_PREFIX:
                    group["tasks"].append(task)
                    # グループキーは短い方（より一般的なイベント名）に寄せる
                    if len(event_key) < len(gk):
                        group["event_key"] = event_key
                    placed = True
                    break
        if not placed:
            groups.append({"date_key": date_key, "event_key": event_key, "tasks": [task]})

    merged: List[dict] = []
    for group in groups:
        members = group["tasks"]
        if len(members) == 1:
            merged.append(members[0])
            continue
        merged.append(_merge_task_group(members))
    return merged


def _merge_task_group(members: List[dict]) -> dict:
    """同一イベントとみなされたタスク群を1件のタスク dict に統合する。"""

    def _category(task: dict) -> str:
        cat = task.get("category")
        return cat if cat in ALL_CONTENT_KEYS else OTHER_KEY

    # 代表タスク: category 優先順位（events 優先）で最初に出現したもの
    representative = members[0]
    best_rank = len(_MERGE_CATEGORY_PRIORITY)
    for task in members:
        cat = _category(task)
        rank = _MERGE_CATEGORY_PRIORITY.index(cat) if cat in _MERGE_CATEGORY_PRIORITY else len(_MERGE_CATEGORY_PRIORITY)
        if rank < best_rank:
            best_rank = rank
            representative = task

    # detail: 出現順を保ち、重複・空を除いて改行連結
    details: List[str] = []
    for task in members:
        d = (task.get("detail") or "").strip()
        if d and d not in details:
            details.append(d)

    # date: 非空の日付を1つ採用
    date = ""
    for task in members:
        d = (task.get("date") or "").strip()
        if d:
            date = d
            break

    return {
        "title": (representative.get("title") or "").strip(),
        "date": date,
        "detail": "\n".join(details),
        "category": _category(representative),
    }


def build_task_drafts(
    safe_text: str,
    detected_dates: Optional[List[str]] = None,
    detected_items: Optional[List[str]] = None,
    language: str = "ja",
) -> List[dict]:
    """OCR安全テキストを「タスクごと」の draft フィールド dict のリストにする (SOT-1307)。

    LLM が使えるときは本文をタスク(行動項目)単位に分割し、各タスクを1件の draft にする。
    LLM が使えない・失敗した・1件も抽出できない場合は、従来の単一 draft を1件返す（後方互換）。
    各 draft dict のキー集合は build_draft_fields と同形＋``event_date``。常に1件以上を返す。
    """
    safe_text = safe_text or ""
    detected_dates = detected_dates or []
    detected_items = detected_items or []

    if not safe_text.strip() or not ai_client.gemini_available():
        return [_single_task_fallback(safe_text, detected_dates, detected_items)]

    try:
        tasks = _llm_tasks(safe_text, language)
    except Exception as e:  # graceful degradation
        logger.warning("LLM task split failed, using single draft: %s", e)
        tasks = []

    if not tasks:
        return [_single_task_fallback(safe_text, detected_dates, detected_items)]

    # SOT-1350: 同一日・同一イベントのタスクを draft 化前に1件へ統合する。
    tasks = _consolidate_tasks(tasks)
    return [_task_to_draft(task, safe_text) for task in tasks]
