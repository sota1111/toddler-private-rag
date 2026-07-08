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
from dataclasses import dataclass
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


def normalize_date(
    raw: Optional[str], *, reference_year: Optional[int] = None
) -> Optional[str]:
    """検出した日付文字列をベストエフォートで ISO (YYYY-MM-DD) に正規化する。

    対応: YYYY-MM-DD / YYYY/M/D / M月D日 / M/D(年なしスラッシュ, 例 7/31; SOT-1567 提案4)。
    年が明示されない表記(M月D日 / M/D)は ``reference_year``（無指定なら発行年=当年）で補完する。
    確実に解釈できない場合は None を返す。
    """
    if not raw:
        return None
    s = raw.strip()
    base_year = reference_year if reference_year else clock.today().year

    m = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$", s)
    if m:
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.match(r"^(\d{1,2})月(\d{1,2})日$", s)
        if m:
            year = base_year
            month, day = int(m.group(1)), int(m.group(2))
        else:
            # SOT-1567 提案4: M/D(年なしスラッシュ)。年は発行年(reference_year)で補完する。
            m = re.match(r"^(\d{1,2})/(\d{1,2})$", s)
            if not m:
                return None
            year = base_year
            month, day = int(m.group(1)), int(m.group(2))

    try:
        return datetime.date(year, month, day).isoformat()
    except ValueError:
        return None


# --- SOT-1567: OCR日付誤読の発行月コンテキスト補正 --------------------------------
# 「7月号のおたよりの締切が『1/31』に化ける（7→1 誤読）」のような、字形の似た文字による
# OCR日付誤認識を、発行月コンテキストで検出・補正するための純粋関数群。

# 提案3: 日付フィールドに限定した OCR 混同文字の正規化マップ。
# 和文OCRで「数字と誤認されやすい非数字」(O/〇→0, l/｜→1, Z→2, S→5, B→8 等)と全角数字だけを
# 半角数字へ寄せる。本文全体には適用しない（過補正回避）。
# 注意: 7↔1 のような「数字どうし」の混同はここでは直さない（どちらも妥当な数字で決定的に直せない）。
# それは提案1(check_deadline_consistency)＋提案2(LLM補正)で扱う。
_DATE_CHAR_CONFUSIONS = {
    "O": "0", "o": "0", "〇": "0", "○": "0", "◯": "0", "Ｏ": "0",
    "l": "1", "I": "1", "i": "1", "｜": "1", "|": "1", "！": "1", "Ｉ": "1",
    "Z": "2", "z": "2", "Ｚ": "2",
    "S": "5", "s": "5", "Ｓ": "5",
    "B": "8", "Ｂ": "8",
    "g": "9", "q": "9",
    "０": "0", "１": "1", "２": "2", "３": "3", "４": "4",
    "５": "5", "６": "6", "７": "7", "８": "8", "９": "9",
    "／": "/", "－": "-", "ー": "-", "　": " ",
}


def normalize_date_field_confusions(raw: Optional[str]) -> str:
    """日付フィールド文字列に限定して OCR 混同文字を数字へ正規化する (SOT-1567 提案3)。

    区切り(月日年 / スラッシュ / ハイフン)や漢字は保持し、数字と紛らわしい非数字・全角数字だけを
    写像する。本文全体ではなく「日付として扱う短い文字列」にのみ適用すること（過補正回避）。
    純粋関数。
    """
    if not raw:
        return ""
    return "".join(_DATE_CHAR_CONFUSIONS.get(ch, ch) for ch in raw)


# 提案3の候補スキャン用: 「数字またはその字形類似字」1文字にマッチする文字クラス。
# _DATE_CHAR_CONFUSIONS のうち「数字へ写る文字」(=区切り記号は除く)＋半角数字から生成する
# （マップと二重管理にしないため）。区切り(月/日/スラッシュ)は別に扱う。
_CONFUSABLE_DIGIT_CHARS = "0123456789" + "".join(
    k for k, v in _DATE_CHAR_CONFUSIONS.items() if v.isdigit()
)
_CONFUSABLE_DIGIT_CLASS = "[" + re.escape(_CONFUSABLE_DIGIT_CHARS) + "]"

# 混同文字を含む「日付らしい短いトークン」だけを拾う候補パターン (SOT-1567 提案3)。
# M/D(スラッシュ, 半/全角) と M月D日 の2形。前後が英数字/スラッシュのトークンは対象外にして、
# 単語の一部や YYYY/M/D の断片を拾わないようにする（過補正回避＝日付フィールド限定の担保）。
_CONFUSABLE_DATE_TOKEN_RE = re.compile(
    r"(?<![0-9A-Za-z/／])(?:"
    + _CONFUSABLE_DIGIT_CLASS + r"{1,2}[/／]" + _CONFUSABLE_DIGIT_CLASS + r"{1,2}"
    + r"|"
    + _CONFUSABLE_DIGIT_CLASS + r"{1,2}月" + _CONFUSABLE_DIGIT_CLASS + r"{1,2}日"
    + r")(?![0-9A-Za-z/／])"
)


def find_confusable_date_tokens(text: Optional[str]) -> List[str]:
    """本文から「混同文字を含む日付らしいトークン」を拾い、混同正規化した文字列で返す (SOT-1567 提案3)。

    数字と字形の紛らわしい文字(O/l/S/B 等)・全角数字・全角スラッシュを含む短い日付トークン
    (``M/D`` / ``M月D日``)だけを対象に ``normalize_date_field_confusions`` で数字へ寄せた文字列を
    返す。本文全体には広げないため過補正しない。返す文字列は ``normalize_date`` でそのまま解釈できる
    形（例: ``7／3l`` → ``7/31``）。順序保持・重複除去。純粋関数・never-throw。
    """
    if not text:
        return []
    out: List[str] = []
    try:
        for raw in _CONFUSABLE_DATE_TOKEN_RE.findall(text):
            fixed = normalize_date_field_confusions(raw)
            if fixed and fixed not in out:
                out.append(fixed)
    except Exception as e:  # noqa: BLE001 - best-effort
        logger.warning("confusable date token scan failed: %s", e)
        return []
    return out


# 提案1: 締切月と発行月の差(月数)がこれを超えたら「不自然」とみなす閾値。提出物の締切は通常、
# 発行から数か月以内。半年(6か月)を超える乖離は誤読を疑う。
_DEADLINE_MONTH_GAP_THRESHOLD = 6

# 字形が似ており OCR で入れ替わりやすい1桁数字の対（補正候補の決定的導出に使う）。
_DIGIT_CONFUSION_PAIRS = {
    "1": {"7"},
    "7": {"1"},
    "0": {"8", "6", "9"},
    "8": {"0", "6", "3"},
    "3": {"8"},
    "5": {"6", "8"},
    "6": {"0", "5", "8"},
    "9": {"0", "4"},
}


@dataclass
class DateContextFinding:
    """発行月コンテキストに対する締切日の整合判定結果 (SOT-1567 提案1)。"""

    suspicious: bool
    reason: str = ""
    # 決定的に補正候補が導ける場合の ISO（例: 7↔1 誤読 → 発行月へ寄せた候補）。無ければ None。
    suggestion: Optional[str] = None


def _suggest_issue_month_candidate(
    deadline: datetime.date, issue_date: datetime.date
) -> Optional[str]:
    """過去に化けた締切について、月を発行月へ差し替えた補正候補 ISO を決定的に導く。

    締切月と発行月が「字形の似た1桁数字の混同」で説明でき、月を発行月へ替えると発行日以降に
    なる場合のみ候補を返す（例: 発行=7月・締切=1/31 → 7/31）。それ以外は None（憶測しない）。
    """
    d_month, i_month = str(deadline.month), str(issue_date.month)
    if d_month == i_month:
        return None
    # 1桁月どうしの字形混同でなければ決定的候補は出さない（例: 12月↔2月は桁数違い）。
    if i_month not in _DIGIT_CONFUSION_PAIRS.get(d_month, set()):
        return None
    try:
        candidate = datetime.date(issue_date.year, issue_date.month, deadline.day)
    except ValueError:
        return None
    return candidate.isoformat() if candidate >= issue_date else None


def check_deadline_consistency(
    deadline_iso: Optional[str],
    issue_date: Optional[datetime.date],
    *,
    month_gap_threshold: int = _DEADLINE_MONTH_GAP_THRESHOLD,
) -> DateContextFinding:
    """締切日が発行日(発行月コンテキスト)と整合するかを決定的に判定する (SOT-1567 提案1)。

    - 締切が発行日より過去 → 疑わしい（例: 7月発行なのに締切 1/31）。
    - 締切月と発行月の差が ``month_gap_threshold`` か月を超える → 疑わしい。
    補正はここでは行わず、疑わしさのフラグと（可能なら決定的な）補正候補のみ返す。検出＋トリガ専用で、
    LLM補正(提案2)を呼ぶかどうかのゲートに使う。情報不足(発行日/締切が無い・解釈不能)のときは
    suspicious=False を返す（過検出しない）。純粋関数。
    """
    if not deadline_iso or issue_date is None:
        return DateContextFinding(False)
    try:
        deadline = datetime.date.fromisoformat(deadline_iso)
    except (ValueError, TypeError):
        return DateContextFinding(False)

    if deadline < issue_date:
        return DateContextFinding(
            True,
            reason=f"締切({deadline.isoformat()})が発行日({issue_date.isoformat()})より過去です",
            suggestion=_suggest_issue_month_candidate(deadline, issue_date),
        )

    gap = abs((deadline.year - issue_date.year) * 12 + (deadline.month - issue_date.month))
    if gap > month_gap_threshold:
        return DateContextFinding(
            True,
            reason=(
                f"締切月({deadline.year}-{deadline.month:02d})と"
                f"発行月({issue_date.year}-{issue_date.month:02d})の差が{gap}か月と大きすぎます"
            ),
        )
    return DateContextFinding(False)


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
    if any((kw in blob) or (kw in lowered) for kw in _DEADLINE_INVESTIGATION_KEYWORDS):
        return True
    # SOT-1564: 書類名が本文に明記されず手続き名だけのおたより（例: 現況確認の手続き）でも締切調査を
    # 発火させる。PR #384 は抽出関数(extract_submission_documents)側に「手続き名→就労証明書」の辞書
    # 到達を入れたが、そもそもこのゲートが手続きキーワードを知らず False を返すため、自動OCR経路
    # (routers/attachments.py の needs_deadline_investigation ゲート)で締切調査が一度も起動していな
    # かった。手続きキーワードは submission_agent の辞書を唯一の真実源として参照する（循環 import を
    # 避けるため関数内 import）。never-throw: 判定不能時は安全側で False。
    try:
        from . import submission_agent

        return submission_agent.text_has_procedure_keyword(blob)
    except Exception:  # noqa: BLE001 - best-effort ゲート判定
        return False


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


def _procedure_keyword_in_drafts(drafts: List[dict]) -> bool:
    """生成済み draft のいずれかの content に手続きキーワードが含まれるか (SOT-1588)。

    含まれていればそのタスクは needs_deadline_investigation ゲートを通り（＝締切調査へ到達する）、
    補完タスクは不要（重複させない）。never-throw: 判定不能時は False。
    """
    try:
        from . import submission_agent  # 遅延 import: 循環参照回避
    except Exception:  # noqa: BLE001 - best-effort
        return False
    for d in drafts:
        try:
            if submission_agent.text_has_procedure_keyword(d.get("content") or ""):
                return True
        except Exception:  # noqa: BLE001 - best-effort
            continue
    return False


def _procedure_supplement_draft(safe_text: str) -> Optional[dict]:
    """全文に手続きキーワードがあるのに LLM 分割で失われた場合の決定的な補完 draft (SOT-1588)。

    多トピックの長いおたよりでは LLM のタスク分割が「保育施設在籍にかかる現況確認の手続き…」の
    ような小さな依頼を落とす／語を変えることがあり、その結果どのタスクも締切調査ゲート
    (needs_deadline_investigation)を通らず、就労証明書の締切逆算タスクが一度も生成されない
    （＝SOT-1564 の辞書到達が実運用に届かない）。全文には手続きキーワードが決定的に存在するので、
    それを含む文を保持した「提出物」タスクを1件補完し、締切調査(submission_agent)へ確実に到達させる。

    締切表記（例「… 1/31 まで」）は手続き文と同じ行に載ることが多いので、キーワードを含む行を
    そのまま content に残し、submission_agent 側で締切を拾って（発行月コンテキストで OCR 補正して）
    逆算アンカーにできるようにする。event_date は敢えて空にする（明示アンカーにすると OCR 補正前の
    誤った日付で固定されてしまうため、本文検出＋補正に委ねる）。手続きキーワードが無ければ None。
    """
    try:
        from . import submission_agent  # 遅延 import: 循環参照回避
    except Exception:  # noqa: BLE001 - best-effort
        return None
    if not submission_agent.text_has_procedure_keyword(safe_text or ""):
        return None
    # 手続きキーワードを含む行/文を抽出（締切表記を同じ行に保つため行/句単位で保持）。
    segments = [seg.strip() for seg in re.split(r"[\n。]", safe_text or "") if seg.strip()]
    proc_segments = [
        seg for seg in segments if submission_agent.text_has_procedure_keyword(seg)
    ]
    content = "\n".join(proc_segments) if proc_segments else (safe_text or "")
    title = draft_title(content)
    category_dict = {k: [] for k in ALL_CONTENT_KEYS}
    return {
        "title": title,
        "info_type": "提出物",  # 締切調査対象。needs_deadline_investigation も True になる。
        "content": content,
        "items": "",
        "date": "",
        "event_date": "",
        "needs_deadline_investigation": True,
        "categories": {"title": title, **category_dict},
    }


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
    drafts = [_task_to_draft(task, safe_text) for task in tasks]

    # SOT-1588: 多トピックの長いおたよりでは LLM 分割が「現況確認の手続き…」のような手続き依頼を
    # 落とし、どの分割タスクも締切調査ゲートを通らないことがある。全文に手続きキーワードが決定的に
    # 存在するのに生成タスクのどれもそれを含まない場合は、決定的な補完タスクを1件追加して就労証明書の
    # 締切逆算へ確実に到達させる（既に含むタスクがあれば重複させない）。best-effort。
    if not _procedure_keyword_in_drafts(drafts):
        supplement = _procedure_supplement_draft(safe_text)
        if supplement is not None:
            drafts.append(supplement)
    return drafts


def is_deadline_companion(record: dict) -> bool:
    """SOT-1577 REOPEN#2 / SOT-1584: レコードが「締切調査の付随タスク」かを判定する純関数。

    写真1枚(source_info_id)からは build_task_drafts が生成する“実際の分割タスク”に加え、
    締切調査(submission_agent)が生成する付随タスクにも同じ source_info_id が付く。付随タスクは
    締切グループ(deadline_group_id)に属し、submission_agent が番兵タグ ``SUBMISSION_TAG``
    (提出書類) を必ず付ける。分割の元タスク(アンカー)は同グループに束ねられても offset 0 で、
    タグは持たない。締切調査を要さない通常の分割タスクは group もタグも無い。

    判定規則(SOT-1584):
    - ``SUBMISSION_TAG`` を持つレコードは付随タスク。これで offset に依存せず確実に除外できる。
    - 後方互換のため、従来の「deadline_group_id があり offset≠0」も付随タスクとして扱う。

    SOT-1584 修正前は offset のみで判定していたため、基準日当日に締切が来る付随タスク
    (例: 提出手順 (2/2)、offset 0) がアンカーと同じ「実タスク」と誤カウントされ、分割していない
    (=実タスク1件)のに「分割前のタスクに戻す」ボタンが出ていた。番兵タグを主判定に加えて是正する。
    表示件数や統合対象からは付随タスクを除外する。
    """
    # 番兵タグによる判定(主)。submission_agent と同じ SUBMISSION_TAG を単一の真実源として使う。
    from .submission_agent import SUBMISSION_TAG  # 遅延 import で循環参照を避ける

    tags = record.get("tags")
    if tags and SUBMISSION_TAG in str(tags):
        return True

    # 後方互換: 締切グループに属し offset≠0 のレコードも付随タスクとして扱う。
    group = record.get("deadline_group_id")
    if group in (None, ""):
        return False
    return record.get("deadline_offset_days") != 0


def merge_split_drafts_to_single(
    drafts: List[dict],
    source: Optional[dict] = None,
    anchor: Optional[dict] = None,
) -> dict:
    """SOT-1577: 同一書類から分割された複数タスク draft を「未分割の1タスク」へ統合する。

    書類→タスク分割が不要だったケースのため、仮登録画面の「分割前のタスクに戻す」から呼ばれる。
    LLM 呼び出しや I/O を行わない純関数。返り値のキー集合は build_task_drafts の各要素と同形
    （title / info_type / content / items / date / event_date）。

    - anchor (SOT-1594): 締切逆算タスクの分割群を戻すときの「分割前のタスク」（＝締切調査の元タスク、
      締切グループに offset 0・番兵タグ無しで束ねられるアンカー）。渡された場合は title / content /
      info_type / items / date / event_date をアンカー（＝文字起こし後のタスク内容, 手順1の状態）から
      復元する。締切調査の付随タスク（手順）の本文（調査結果の羅列）や写真書類のタイトルは使わない。
      anchor が無い（SOT-1577 の非締切分割）ときは従来どおりの下記挙動。
    - content: SOT-1577 REOPEN#2 で是正。書類全体(source.content=全写真の文字起こし)は流し込まず、
      分割タスク群自身の本文を出現順に重複なく連結する（「戻す」で全写真分が出るのを防ぐ）。
    - title / info_type: source を優先し、無ければ先頭 draft、いずれも無ければフォールバック。
    - date / event_date: 分割 draft 群のうち最も早い非空の日付を採用する（未分割でも1つの予定日を
      保ち、やること一覧に出るようにする）。
    - items: 分割 draft 群の非空 items を出現順に重複なく改行連結する。
    """
    drafts = [d for d in drafts if d]
    first = drafts[0] if drafts else {}
    source = source or {}
    anchor = anchor or {}

    def _clean(v) -> str:
        return str(v).strip() if v is not None else ""

    # content: SOT-1577 REOPEN#2。書類全体(source.content=全写真の文字起こし)は使わず、分割タスク
    # 群自身の本文を出現順に重複なく連結する。source を優先すると「戻す」で全写真分の文字起こしが
    # 出力されてしまうため（該当タスクの内容のみへ戻す）。
    seen: List[str] = []
    for d in drafts:
        c = _clean(d.get("content"))
        if c and c not in seen:
            seen.append(c)
    joined_content = "\n\n".join(seen)

    # SOT-1594: アンカー（分割前タスク）があれば、その content（文字起こし後のタスク内容＝手順1の状態）
    # へ戻す。締切調査の付随タスク本文（調査結果）は使わない。アンカー content が空なら退行を避けるため
    # 分割群の連結本文へフォールバックする。
    anchor_content = _clean(anchor.get("content"))
    content = anchor_content or joined_content if anchor else joined_content

    # title: SOT-1594。アンカー（締切分割前タスク）の title を最優先。写真書類(source)のタイトルには
    # しない。アンカーが無ければ従来どおり source → 先頭 draft → 生成。
    title = (
        _clean(anchor.get("title"))
        or _clean(source.get("title"))
        or _clean(first.get("title"))
        or draft_title(content)
    )
    title = title[:40]

    info_type = _clean(anchor.get("info_type")) or _clean(source.get("info_type"))
    if info_type not in INFO_TYPES:
        info_type = _clean(first.get("info_type"))
    if info_type not in INFO_TYPES:
        info_type = "資料"

    def _earliest(key: str) -> str:
        vals = sorted(v for v in (_clean(d.get(key)) for d in drafts) if v)
        return vals[0] if vals else ""

    items_seen: List[str] = []
    for d in drafts:
        it = _clean(d.get("items"))
        if it and it not in items_seen:
            items_seen.append(it)
    joined_items = "\n".join(items_seen)

    # items / date / event_date: アンカーがあれば分割前タスク(手順1)の値へ復元し、空なら分割群の集約へ
    # フォールバックする。
    if anchor:
        items = _clean(anchor.get("items")) or joined_items
        date = _clean(anchor.get("date")) or _earliest("date")
        event_date = _clean(anchor.get("event_date")) or _earliest("event_date")
    else:
        items = joined_items
        date = _earliest("date")
        event_date = _earliest("event_date")

    return {
        "title": title,
        "info_type": info_type,
        "content": content,
        "items": items,
        "date": date,
        "event_date": event_date,
    }
