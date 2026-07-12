"""提出書類先回りエージェント (SOT-1316).

おたより等のOCRテキストから「提出が必要な書類」を抽出し、Google Search grounding で公式情報
（必要手順・会社/勤務先発行要否・所要期間）を調査して整理する。さらに提出期限から所要期間を逆算した
準備タスク（draft フィールド dict）を生成する。

人間が選んだ方針: 決定1=案A（既存 Gemini/Vertex AI 上の in-process 実装。ADK/Agent Engine は使わない）、
決定2=W1（Google Search grounding。利用不可時は LLM 既知知識へ graceful fallback）。

このモジュールは FastAPI に依存しない。LLM/grounding 呼び出しは全て graceful に握りつぶし、
失敗時は空リスト/None を返して例外を伝播させない（extraction.translate_text の never-throw パターン）。
"""

import datetime
import json
import logging
import re
import time
import urllib.parse
import uuid
from typing import List, Optional

from . import ai_client, clock, extraction

logger = logging.getLogger(__name__)

# 抽出する提出書類の上限（暴走防止）
_MAX_DOCUMENTS = 10
# 所要期間が不明なときに見込む既定の準備バッファ（日）
_DEFAULT_LEAD_DAYS = 3
# リマインド側(SOT-1339)が提出書類を区別するためのタグ番兵
SUBMISSION_TAG = "提出書類"

# SOT-1566: 手続き名だけで書類名が本文に明記されないおたよりから、標準的に必要な書類へ到達する
# ための「手続きキーワード → 標準書類名」の決定的マッピング。純粋関数で扱い LLM 不要（オフライン
# でも効く土台）。ここで注入した書類は inferred=True（推定=要確認）として扱う。
# 誤検出を避けるため、キーワードは「提出手続き」を強く示唆する具体語に限定する（一般語は入れない）。
_PROCEDURE_DOCUMENT_RULES = (
    (
        (
            "現況確認",
            "現況届",
            "在籍確認",
            "在籍にかかる現況",
            "就労状況確認",
            "就労状況届",
            "就労確認",
        ),
        "就労証明書",
    ),
)


def text_has_procedure_keyword(text: str) -> bool:
    """本文に『手続き名→標準書類』辞書(_PROCEDURE_DOCUMENT_RULES)の手続きキーワードが含まれるか。

    SOT-1564: 書類名が本文に明記されず手続き名だけのおたより（例:「保育施設在籍にかかる現況確認の
    手続き」）でも、締切調査（提出書類エージェント＝就労証明書への到達）を発火させるためのゲート判定に
    使う純粋関数。締切調査の要否ゲート(extraction.needs_deadline_investigation)から、辞書の手続き
    キーワードを唯一の真実源として参照する。手続きキーワードが無ければ False（＝一般文で誤発火させ
    ない）。常に never-throw。
    """
    if not text:
        return False
    return any(
        kw in text for keywords, _doc in _PROCEDURE_DOCUMENT_RULES for kw in keywords
    )

# おたより本文から締切候補を拾うための日付パターン（ocr.py の検出と同等）。
_DATE_PATTERNS = (
    r"\d{4}[-/]\d{1,2}[-/]\d{1,2}",          # 2026-07-31, 2026/7/31
    r"\d{1,2}月\d{1,2}日",                   # 7月31日（年は当年と仮定）
    r"(?:令和|平成|昭和)\d{1,2}年\d{1,2}月\d{1,2}日",  # 令和8年7月31日
    # SOT-1567 提案4: M/D(年なしスラッシュ, 例 7/31)。YYYY/M/D の一部を二重検出しないよう
    # 前後が数字/スラッシュのときは拾わない。年は発行年で補完（normalize_date 側で処理）。
    r"(?<![\d/])\d{1,2}/\d{1,2}(?![\d/])",
)


def _detect_deadline_iso(
    text: str, issue_date: Optional[datetime.date] = None
) -> str:
    """本文中の日付のうち最も遅い日付を ISO で返す（提出期限の代替アンカー）。

    LLM が書類に締切を紐づけられなかった場合でも、おたよりに書かれた締切（例: 7/31）を
    各手順の逆算アンカーとして利用するためのフォールバック。見つからなければ ""。常に never-throw。

    SOT-1567: ``issue_date``（おたよりの発行日/登録日）が与えられた場合は、検出した締切を発行月
    コンテキストで整合チェックし、OCR誤読（例: 7→1 で 7月号なのに 1/31）が疑わしいときだけ補正する。
    """
    if not text:
        return ""
    isos: List[str] = []
    try:
        ref_year = issue_date.year if issue_date else None
        for pattern in _DATE_PATTERNS:
            for raw in re.findall(pattern, text):
                iso = extraction.normalize_date(raw, reference_year=ref_year)
                if iso:
                    isos.append(iso)
        # SOT-1567 提案3: 混同文字を含む日付トークン(例 7／3l)も、日付フィールド限定で
        # 混同正規化してから拾う（本文全体には広げない）。
        for token in extraction.find_confusable_date_tokens(text):
            iso = extraction.normalize_date(token, reference_year=ref_year)
            if iso:
                isos.append(iso)
    except Exception as e:  # noqa: BLE001 - best-effort
        logger.warning("deadline date detection failed: %s", e)
        return ""
    best = max(isos) if isos else ""
    if best and issue_date is not None:
        best = _reconcile_deadline_with_issue(text, best, issue_date)
    return best


def _reconcile_deadline_with_issue(
    text: str, deadline_iso: str, issue_date: datetime.date, language: str = "ja"
) -> str:
    """発行月コンテキストで締切日を整合チェックし、疑わしい時のみ補正する (SOT-1567 提案1+2)。

    1) ``extraction.check_deadline_consistency`` で決定的に「疑わしい」かを判定（提案1＝ゲート）。
    2) 疑わしくなければ原文をそのまま返す（正常な日付は誤補正しない）。
    3) 疑わしければ、まず決定的な補正候補(例: 7↔1 の月差し替え=7/31)を採用。無ければ LLM に
       発行月コンテキストで補正/要確認を依頼（提案2）。LLM 失敗/要確認/不明時は原文維持。
    常に never-throw。
    """
    try:
        finding = extraction.check_deadline_consistency(deadline_iso, issue_date)
    except Exception as e:  # noqa: BLE001 - best-effort
        logger.warning("deadline consistency check failed: %s", e)
        return deadline_iso
    if not finding.suspicious:
        return deadline_iso
    logger.info(
        "suspicious deadline vs issue date: deadline=%s issue=%s (%s)",
        deadline_iso,
        issue_date.isoformat(),
        finding.reason,
    )
    if finding.suggestion:
        return finding.suggestion
    corrected = _llm_correct_deadline(text, deadline_iso, issue_date, language)
    return corrected or deadline_iso


def _llm_correct_deadline(
    text: str, candidate_iso: str, issue_date: datetime.date, language: str = "ja"
) -> str:
    """疑わしい締切日のみ、OCRテキスト＋発行月コンテキストを LLM に渡して補正する (SOT-1567 提案2)。

    高信頼で補正できた場合のみ ISO を返す。要確認/不明/失敗時は "" を返し、呼び出し側が原文を維持する。
    本リポの never-throw / graceful-fallback 方針に従い、例外は投げない。補正結果も「発行日以降」で
    あることを最終ゲートし、LLM が過去日へ逸脱した場合は採用しない。
    """
    if not candidate_iso or not ai_client.gemini_available():
        return ""
    started = time.perf_counter()
    ok = False
    try:
        client = ai_client.get_genai_client()
        model = ai_client.get_model_name()
        prompt = (
            "You correct a likely OCR misread of a submission DEADLINE date on a Japanese "
            "nursery-school notice. Similar-looking digits are often confused (e.g. 7 misread as 1).\n"
            f"- Notice issue date (発行日): {issue_date.isoformat()}\n"
            f"- Today: {clock.today().isoformat()}\n"
            f"- OCR-detected deadline (suspicious): {candidate_iso}\n"
            "The real deadline must be ON OR AFTER the issue date (a notice never asks to submit in the "
            "past). Using the OCR body text and the issue month as context, decide the most likely "
            "corrected deadline.\n"
            "Output ONLY a JSON object: "
            '{"corrected_date":"YYYY-MM-DD or empty string","needs_review":true or false}. '
            "Set corrected_date only when highly confident; otherwise empty string with "
            "needs_review=true.\n\n"
            f"# OCR body\n{(text or '')[:2000]}\n\n# Output (JSON only)"
        )
        cfg = ai_client.default_generate_config(max_output_tokens=256)

        def _gen():
            if cfg is not None:
                return client.models.generate_content(
                    model=model, contents=prompt, config=cfg
                )
            return client.models.generate_content(model=model, contents=prompt)

        response = ai_client.with_retry(_gen)
        raw = (getattr(response, "text", "") or "").strip()
        data = _extract_json_object(raw)
        ok = True
        corrected = extraction.normalize_date(
            str(data.get("corrected_date", "")).strip(),
            reference_year=issue_date.year,
        )
        if corrected:
            try:
                if datetime.date.fromisoformat(corrected) >= issue_date:
                    return corrected
            except ValueError:
                return ""
        return ""
    except Exception as e:  # noqa: BLE001 - never-throw
        logger.warning("LLM deadline correction failed: %s", e)
        return ""
    finally:
        ai_client.log_llm_call(
            "date_sanity_correction",
            ai_client.get_model_name(),
            (time.perf_counter() - started) * 1000,
            ok,
        )


def _extract_json_object(text: str) -> dict:
    """LLM 応答テキストから最初の JSON オブジェクトを取り出してパースする。"""
    if not text:
        raise ValueError("empty LLM response")
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no JSON object in LLM response")
    return json.loads(text[start : end + 1])


def _to_int_days(value) -> Optional[int]:
    """所要日数の値を正の int に正規化する。不正/不明は None。"""
    if isinstance(value, bool):  # bool は int のサブクラスなので先に弾く
        return None
    if isinstance(value, (int, float)):
        n = int(value)
        return n if n > 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        n = int(value.strip())
        return n if n > 0 else None
    return None


def _normalize_steps(raw_steps) -> List[dict]:
    """grounding の steps を ``[{"name": str, "lead_time_days": Optional[int]}]`` に正規化する。

    step 要素は dict (``{"name", "lead_time_days"}``) でも素の文字列でも受け付ける（後方互換）。
    name が空の要素は除外する。常に never-throw。
    """
    items = raw_steps if isinstance(raw_steps, list) else ([raw_steps] if raw_steps else [])
    steps: List[dict] = []
    for item in items:
        if isinstance(item, dict):
            name = str(item.get("name", "")).strip()
            lead = _to_int_days(item.get("lead_time_days"))
        else:
            name = str(item).strip()
            lead = None
        if not name:
            continue
        steps.append({"name": name, "lead_time_days": lead})
    return steps


def _normalize_sources(raw_sources) -> List[dict]:
    """grounding の出典を ``[{"title": str, "url": str}]`` に正規化する（SOT-1404）。

    url を持たない要素は除外し、url で重複排除する。順序は維持。常に never-throw。
    """
    items = raw_sources if isinstance(raw_sources, list) else []
    sources: List[dict] = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url", "") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        title = str(item.get("title", "") or "").strip()
        sources.append({"title": title, "url": url})
    return sources


def _format_source_links(sources: List[dict], ja: bool) -> List[str]:
    """根拠リンクセクションの本文行を返す（SOT-1404）。出典が空なら空リスト。"""
    if not sources:
        return []
    lines = ["根拠リンク:" if ja else "Source links:"]
    for s in sources:
        title = (s.get("title") or "").strip()
        url = (s.get("url") or "").strip()
        if not url:
            continue
        label = f"{title}: {url}" if title else url
        lines.append(f"・{label}" if ja else f"- {label}")
    return lines


# 「お住まいの市区町村の窓口/公式ホームページから様式をダウンロード」型の手順を検出するための語（SOT-1405）。
# 市役所/区役所/役所 や HP/ウェブサイト 等の略称・表記揺れも拾う（grounding LLM は手順名を簡潔に
# 出力するため、語彙を広めに取らないと検出漏れする。SOT-1405 3回目の再オープン対応）。
_MUNI_LOCATION_KEYWORDS = (
    "市区町村",
    "市町村",
    "自治体",
    "窓口",
    "公式ホームページ",
    "ホームページ",
    "市役所",
    "区役所",
    "町役場",
    "村役場",
    "役所",
    "役場",
    "公式サイト",
    "ウェブサイト",
    "webサイト",
    "サイト",
    "HP",
)
_MUNI_GET_KEYWORDS = ("ダウンロード", "様式", "取得", "入手")


def _has_get_keyword(text: str) -> bool:
    """手順テキストが『ダウンロード/様式/取得/入手』等の取得アクションを含むか（場所語は不問）。"""
    if not text:
        return False
    return any(k in text for k in _MUNI_GET_KEYWORDS) or "download" in text.lower()


def _is_municipality_download_step(text: str) -> bool:
    """手順テキストが『市区町村の窓口/公式HPから様式をダウンロード』型かを判定する（SOT-1405）。

    市区町村/窓口/公式HP 等の場所語と、ダウンロード/様式/取得/入手 等の取得語の両方を含むときに
    True。常に never-throw。
    """
    if not text:
        return False
    has_location = any(k in text for k in _MUNI_LOCATION_KEYWORDS)
    return has_location and _has_get_keyword(text)


def _doc_has_municipality_download(doc: dict) -> bool:
    """書類全体（書類名＋全手順を結合したテキスト）が『市区町村窓口/公式HPから様式DL』型かを判定する。

    grounding LLM は手順名を簡潔に出力するため、場所語（市区町村/窓口/公式HP）と取得語（DL/様式）が
    別々の手順に分かれて、どの単一手順も `_is_municipality_download_step` を満たさないことがある。
    その取りこぼしを防ぐため、書類スコープでまとめて判定する（SOT-1405 3回目の再オープン対応）。
    常に never-throw。
    """
    if not isinstance(doc, dict):
        return False
    parts: List[str] = [str(doc.get("name", "") or "")]
    for s in doc.get("steps") or []:
        parts.append(s.get("name", "") if isinstance(s, dict) else str(s))
    return _is_municipality_download_step("\n".join(p for p in parts if p))


def _municipality_download_url(municipality: str, doc_name: str) -> str:
    """設定済み市町村と書類名から、公式ダウンロードページに辿り着く検索URLを作る（SOT-1405）。

    検索クエリは「市町村名＋書類名＋様式」（人間指定の再オープン対応）。
    """
    terms = [(municipality or "").strip(), (doc_name or "").strip(), "様式"]
    query = " ".join(t for t in terms if t)
    return "https://www.google.com/search?q=" + urllib.parse.quote(query)


def _download_link_line(
    municipality: Optional[str], doc_name: str, ja: bool
) -> Optional[str]:
    """市町村が設定されていれば『ダウンロードページ: <url>』行を返す。未設定なら None（SOT-1405）。"""
    muni = (municipality or "").strip()
    if not muni:
        return None
    url = _municipality_download_url(muni, doc_name)
    return f"ダウンロードページ: {url}" if ja else f"Download page: {url}"


def _step_subtitle(step_name: str, limit: int = 18) -> str:
    """手順名から簡潔なサブタイトル（タイトル用）を作る。

    grounding LLM の手順名は時に長い動作文（例: 「自治体のホームページや窓口から就労証明書の
    様式を入手し、記入して提出する」）になり、そのままタイトルに使うと文の途中で切れて読めない
    （SOT-1420 再オープン）。最初の自然な区切り（、。・/改行）までを見出しとして採用し、なお
    長い場合は字数で丸めて末尾に「…」を付ける。手順名フルは本文側に残るため情報は失われない。
    既に簡潔な手順名（例「テンプレート入手」）はそのまま返す。
    """
    s = (step_name or "").strip()
    if not s:
        return ""
    # 複数動作を区切る最初の区切りまでを採用（先頭の一手順だけを見出しにする）
    for sep in ("、", "。", "\n", "・"):
        idx = s.find(sep)
        if idx > 0:
            s = s[:idx]
            break
    s = s.strip()
    if len(s) > limit:
        s = s[:limit].rstrip() + "…"
    return s


def _normalize_doc_name(name: str) -> str:
    """書類名を重複判定用に正規化する（空白除去・小文字化）。常に never-throw。"""
    return re.sub(r"\s+", "", str(name or "")).strip().lower()


def _dictionary_inferred_documents(safe_text: str) -> List[dict]:
    """本文に「提出手続き」を示す手続きキーワードが出たら、対応する標準書類を推定候補として返す（SOT-1566）。

    決定的な `_PROCEDURE_DOCUMENT_RULES` に基づく純粋関数（LLM 不要・オフライン動作）。返す各要素は
    ``{"name", "due_date": "", "inferred": True}``（推定=要確認）。手続きキーワードが無ければ空リスト
    （＝一般文で書類を湧かせない）。書類名で重複排除する。常に never-throw。
    """
    text = safe_text or ""
    if not text.strip():
        return []
    docs: List[dict] = []
    seen: set = set()
    for keywords, doc_name in _PROCEDURE_DOCUMENT_RULES:
        if any(kw in text for kw in keywords):
            key = _normalize_doc_name(doc_name)
            if key and key not in seen:
                seen.add(key)
                docs.append({"name": doc_name, "due_date": "", "inferred": True})
    return docs


def _merge_document_candidates(candidates: List[dict]) -> List[dict]:
    """複数ソース（LLM抽出・辞書推定）の書類候補を書類名で正規化マージする（SOT-1566）。

    - 書類名（正規化）で重複排除し、初出の順序・表記を維持する。
    - `inferred` は「明記（inferred=False）が1つでもあれば明記」を優先（安全側: 本文明記を推定に負けさせない）。
    - `due_date` は明記されている値を優先し、既存が空なら埋める。
    空 name の候補は捨てる。常に never-throw。
    """
    merged: dict = {}
    order: List[str] = []
    for c in candidates:
        if not isinstance(c, dict):
            continue
        name = str(c.get("name", "") or "").strip()
        key = _normalize_doc_name(name)
        if not name or not key:
            continue
        inferred = bool(c.get("inferred", False))
        due = str(c.get("due_date", "") or "").strip()
        if key not in merged:
            merged[key] = {"name": name, "due_date": due, "inferred": inferred}
            order.append(key)
        else:
            existing = merged[key]
            if not inferred:  # 明記が勝つ
                existing["inferred"] = False
            if due and not existing["due_date"]:
                existing["due_date"] = due
    return [merged[k] for k in order]


def _llm_extract_documents(safe_text: str, language: str) -> List[dict]:
    """提出が必要な書類とその提出期限のみを抽出する LLM ステップ。失敗時は例外。"""
    client = ai_client.get_genai_client()
    model = ai_client.get_model_name()
    language_name = extraction._LANGUAGE_NAMES.get(
        language, extraction._LANGUAGE_NAMES["ja"]
    )
    prompt = (
        "You extract the documents/forms that a parent must SUBMIT "
        "(提出が必要な書類) from a nursery-school notice. "
        "Ignore anything that is not a submittable document (events, belongings, general notes). "
        "Output ONLY a JSON array. If none apply, return [].\n"
        "Each element has this shape:\n"
        '{"name":"the document name",'
        '"due_date":"the submission deadline as M月D日 or YYYY-MM-DD; empty string if unknown",'
        '"inferred":true or false}\n'
        "Rules for inference (重要):\n"
        "- If a document name is written explicitly in the body, output it with \"inferred\":false.\n"
        "- If the body describes a SUBMISSION PROCEDURE (提出手続き) but does NOT name the document "
        "(e.g. 『保育施設在籍にかかる現況確認の手続き』『就労状況の確認』『現況届の提出』), "
        "infer the standard document that procedure requires (e.g. 現況確認/在籍確認/就労状況確認 → 就労証明書) "
        "and output it with \"inferred\":true.\n"
        "- Only infer when a concrete submission procedure is mentioned. Do NOT invent documents from "
        "general notices, events, or belongings. When unsure, output nothing rather than guessing.\n"
        f"Write name in {language_name}.\n\n"
        f"# Body\n{safe_text}\n\n"
        "# Example output\n"
        '[{"name":"健康調査票","due_date":"5月1日","inferred":false},'
        '{"name":"就労証明書","due_date":"","inferred":true}]\n\n'
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
    data = extraction._extract_json_array(text)

    docs: List[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip().splitlines()[0][:40] if item.get("name") else ""
        if not name:
            continue
        due_raw = str(item.get("due_date", "")).strip()
        # SOT-1566: 手続きから推論した書類は inferred=True。明示されていない/未指定は明記扱い(False)。
        inferred = bool(item.get("inferred", False))
        docs.append({"name": name, "due_date": due_raw, "inferred": inferred})
    return docs[:_MAX_DOCUMENTS]


def _grounded_enrich(name: str, language: str) -> dict:
    """1書類について公式情報を grounding で調査し、手順/会社発行要否/所要期間/出典を返す。

    grounding が利用不可/失敗でも例外は出さず、可能な範囲の値（または既定値）を返す。
    """
    language_name = extraction._LANGUAGE_NAMES.get(
        language, extraction._LANGUAGE_NAMES["ja"]
    )
    prompt = (
        "Research official public information about how to obtain and submit the following "
        "document required by a Japanese nursery school / municipality, then output ONLY a JSON object.\n"
        f"# Document\n{name}\n\n"
        "JSON shape:\n"
        '{"steps":[{"name":"concise step","lead_time_days":<average days this step takes, or null>}, "..."],'
        '"needs_company_issuance":true or false or null,'
        '"lead_time_days":<total integer number of days to obtain it, or null>,'
        '"source":"the official source URL or name, or empty string"}\n'
        "List the steps in EXECUTION ORDER (earliest action first, final submission last). "
        'For each step, estimate the AVERAGE number of days it typically takes in "lead_time_days" '
        "(use null only when truly unknown).\n"
        '"needs_company_issuance" means whether the document must be issued by an employer / company '
        "(e.g. 就労証明書). Use null if unknown.\n"
        f"Write each step name in {language_name}. Do not fabricate; use null/empty when unknown.\n\n"
        "# Output (JSON object only)"
    )
    raw, grounding_sources = ai_client.generate_grounded_with_sources(
        prompt, max_output_tokens=1024
    )

    steps: List[dict] = []
    needs_company: Optional[bool] = None
    lead_days: Optional[int] = None
    source = ""
    try:
        obj = _extract_json_object(raw)
        steps = _normalize_steps(obj.get("steps"))
        nci = obj.get("needs_company_issuance")
        if isinstance(nci, bool):
            needs_company = nci
        lead_days = _to_int_days(obj.get("lead_time_days"))
        src = obj.get("source")
        if isinstance(src, str):
            source = src.strip()
    except Exception as e:  # noqa: BLE001 - grounding/parse best-effort
        logger.warning("submission enrich parse failed for %s: %s", name, e)

    # 根拠となる出典リンク（SOT-1404）: 実 grounding の出典を最優先で採用する。
    # grounding メタデータが無くても、LLM 自己申告の source が http(s) URL ならフォールバックで使う。
    sources = _normalize_sources(grounding_sources)
    if not sources and source.startswith(("http://", "https://")):
        sources = [{"title": source, "url": source}]

    return {
        "steps": steps,
        "needs_company_issuance": needs_company,
        "lead_time_days": lead_days,
        "source": source,
        "sources": sources,
    }


def extract_submission_documents(
    safe_text: str,
    detected_dates: Optional[List[str]] = None,
    language: str = "ja",
    final_due_iso: Optional[str] = None,
    issue_date: Optional[datetime.date] = None,
) -> List[dict]:
    """提出書類を抽出し、grounding で公式情報を付与した dict のリストを返す。

    返り値 dict: ``{name, due_date(ISO or ""), steps(list[{name, lead_time_days}]),
    needs_company_issuance(bool|None), lead_time_days(int|None), source(str)}``.
    safe_text が空、または AI クライアント不可のときは空リスト。常に never-throw。

    ``final_due_iso`` が与えられた場合（締切調査の実行対象タスクに既に設定されている期限。
    SOT-1399 4回目の再オープン対応）は、それを最終提出期限の逆算アンカーとして**最優先**で
    採用する（LLM 抽出の書類別締切や本文検出より優先）。
    """
    safe_text = safe_text or ""
    if not safe_text.strip():
        return []

    # SOT-1564: LLM 抽出は Gemini 利用可能なときだけ試みる。以前はこの関数先頭で
    # ``not ai_client.gemini_available()`` のとき即 [] を返しており、下の決定的辞書
    # (_dictionary_inferred_documents) が一切効かず、SOT-1566 の「LLM 不在でも辞書だけで書類へ到達
    # できる（オフライン土台）」が実運用で機能していなかった。gemini ゲートは LLM 抽出のみに限定し、
    # 辞書由来の書類は Gemini 不在でも到達できるようにする（grounding は下で never-throw フォールバック）。
    docs: List[dict] = []
    if ai_client.gemini_available():
        try:
            docs = _llm_extract_documents(safe_text, language)
        except Exception as e:  # noqa: BLE001 - graceful degradation
            logger.warning("submission document extraction failed: %s", e)
            docs = []

    # SOT-1566: 手続きキーワードから標準書類を推定する決定的な辞書候補を注入し、LLM抽出結果と
    # 書類名でマージ（重複排除・明記優先）。LLM が失敗/不在でも辞書だけで書類へ到達できる（オフライン土台）。
    dict_docs = _dictionary_inferred_documents(safe_text)
    docs = _merge_document_candidates(list(docs) + dict_docs)[:_MAX_DOCUMENTS]
    if not docs:
        return []

    # タスク自身に設定済みの最終期限（最優先アンカー）。
    explicit_due_iso = extraction.normalize_date(final_due_iso) if final_due_iso else ""
    # LLM が書類に締切を紐づけられなかったときの逆算アンカー（本文の最も遅い日付）。
    # SOT-1567: 発行日(issue_date)があれば発行月コンテキストで締切の OCR 誤読を補正する。
    fallback_due_iso = _detect_deadline_iso(safe_text, issue_date)

    enriched: List[dict] = []
    for doc in docs:
        name = doc.get("name", "")
        if not name:
            continue
        # 優先順: タスク設定日付 ＞ LLM抽出の書類別締切 ＞ 本文の最終締切（前向き累積に落とさない）。
        due_iso = (
            explicit_due_iso
            or extraction.normalize_date(doc.get("due_date"))
            or fallback_due_iso
        )
        try:
            info = _grounded_enrich(name, language)
        except Exception as e:  # noqa: BLE001 - never let one doc break the batch
            logger.warning("submission enrich failed for %s: %s", name, e)
            info = {
                "steps": [],
                "needs_company_issuance": None,
                "lead_time_days": None,
                "source": "",
                "sources": [],
            }
        enriched.append(
            {
                "name": name,
                "due_date": due_iso,
                "steps": info["steps"],
                "needs_company_issuance": info["needs_company_issuance"],
                "lead_time_days": info["lead_time_days"],
                "source": info["source"],
                "sources": info.get("sources") or [],
                # SOT-1566: 辞書/推論由来の書類は inferred=True（推定=要確認）。本文明記は False。
                "inferred": bool(doc.get("inferred", False)),
            }
        )
    return enriched


def _prep_start_iso(due_iso: str, lead_days: Optional[int]) -> str:
    """提出期限から所要期間を逆算した準備開始日 (ISO)。due 不明なら ""。"""
    if not due_iso:
        return ""
    try:
        due = datetime.date.fromisoformat(due_iso)
    except ValueError:
        return ""
    buffer = lead_days if isinstance(lead_days, int) and lead_days > 0 else _DEFAULT_LEAD_DAYS
    start = due - datetime.timedelta(days=buffer)
    if start > due:  # 念のため（buffer<0 はあり得ないが防御的に）
        start = due
    return start.isoformat()


def _inferred_notice_line(ja: bool) -> str:
    """推定（辞書/LLM推論）由来の書類であることを利用者へ明示し、否定（削除）を促す行（SOT-1566）。"""
    return (
        "※ 推定（要確認）: 本文に書類名が明記されていないため、手続きから推定した書類です。"
        "不要な場合はこのタスクを削除してください。"
        if ja
        else "Note (please verify): inferred from the described procedure — the document name is not "
        "written in the notice. Delete this task if it does not apply."
    )


def _build_content(
    doc: dict, language: str, municipality: Optional[str] = None
) -> str:
    """書類の手順/会社発行要否/所要期間/提出期限/出典を読みやすい本文にまとめる。"""
    ja = language != "en"
    lines: List[str] = []
    name = doc.get("name", "")
    if name:
        lines.append(name)
    # SOT-1566: 推定由来の書類は「推定（要確認）」を明示し、安全側フォールバック（削除導線）を持たせる。
    if doc.get("inferred"):
        lines.append(_inferred_notice_line(ja))

    steps = doc.get("steps") or []
    if steps:
        lines.append("【手順】" if ja else "Steps:")
        for s in steps:
            label = s.get("name", "") if isinstance(s, dict) else str(s)
            if label:
                lines.append(f"・{label}" if ja else f"- {label}")
        # 市区町村の窓口/公式HPから様式をDLする書類なら、設定済み市町村のDLページリンクを1行付与（SOT-1405）。
        # 場所語と取得語が別々の手順に分かれていても拾えるよう書類スコープで判定する。
        if _doc_has_municipality_download(doc):
            link = _download_link_line(municipality, name, ja)
            if link:
                lines.append(link)

    nci = doc.get("needs_company_issuance")
    if nci is True:
        lines.append("会社/勤務先の発行が必要です。" if ja else "Requires issuance by your employer.")
    elif nci is False:
        lines.append("会社発行は不要です。" if ja else "No employer issuance required.")

    lead = doc.get("lead_time_days")
    if isinstance(lead, int):
        lines.append(f"所要期間の目安: 約{lead}日" if ja else f"Estimated lead time: ~{lead} days")

    due = doc.get("due_date")
    if due:
        lines.append(f"提出期限: {due}" if ja else f"Submission deadline: {due}")
    else:
        # SOT-1598: 提出期限が本文から判明しないときは「不明」であることを明記する。
        lines.append(
            "提出期限: 不明（本文に提出期限の記載がありません）"
            if ja
            else "Submission deadline: unknown (no deadline stated in the notice)"
        )

    # 根拠となる出典リンク（SOT-1404）: grounding 由来の実URLがあればリンク一覧を出し、
    # 無ければ従来どおり LLM 自己申告の単一「出典」行を出す。
    source_lines = _format_source_links(doc.get("sources") or [], ja)
    if source_lines:
        lines.extend(source_lines)
    else:
        source = doc.get("source")
        if source:
            lines.append(f"出典: {source}" if ja else f"Source: {source}")

    return "\n".join(lines) if lines else (name or "")


def _today() -> datetime.date:
    """本日の日付。テストで monkeypatch できるよう関数に切り出す。"""
    return datetime.date.today()


def _step_deadlines(
    due_iso: str, steps: List[dict], doc_lead: Optional[int]
) -> List[dict]:
    """各手順の所要期間から手順ごとの締切(ISO)を付与して返す。

    ``steps`` は実行順（最初の手順が先頭、最終提出が末尾）。返り値も実行順で、各要素は
    ``{name, lead_time_days(有効値), due_iso}``。

    - 最終提出期限が判明している場合: 提出期限から各手順の所要日数だけ後ろ向きに逆算する。
    - 最終提出期限が不明（空/不正）な場合: 本日起点で各手順の所要日数を前向きに累積し、各手順に
      具体的な締切を設定する（やることリストに日付が登録されるようにするため。SOT-1399 再オープン対応）。

    常に never-throw。
    """
    n = len(steps)
    # 手順固有の所要日数が無いときのフォールバック日数
    if isinstance(doc_lead, int) and doc_lead > 0 and n > 0:
        fallback = max(1, round(doc_lead / n))
    else:
        fallback = _DEFAULT_LEAD_DAYS
    effective = [
        lead if isinstance((lead := s.get("lead_time_days")), int) and lead > 0 else fallback
        for s in steps
    ]

    due: Optional[datetime.date] = None
    if due_iso:
        try:
            due = datetime.date.fromisoformat(due_iso)
        except ValueError:
            due = None

    dues: List[str] = [""] * n
    # SOT-1411: 基準日(最終提出期限)から各手順締切まで「何日手前か」のオフセット。基準日が判明する
    # ときのみ意味を持つ（前向き累積時は基準日が無いので None）。基準日変更時の付随タスクずらしに使う。
    offsets: List[Optional[int]] = [None] * n
    if due is not None:
        cursor = due
        # 末尾(最終提出)から先頭へ、各手順の所要日数だけ遡って締切を決める
        for i in range(n - 1, -1, -1):
            cursor = cursor - datetime.timedelta(days=effective[i])
            dues[i] = cursor.isoformat()
            offsets[i] = (due - cursor).days
    else:
        # 最終期限が不明なときは本日起点で前向きに累積し、各手順に具体日付を割り当てる
        cursor = _today()
        for i in range(n):
            cursor = cursor + datetime.timedelta(days=effective[i])
            dues[i] = cursor.isoformat()
        # SOT-1411 再オープン対応: 最終提出期限が不明でも、グループ内の最終タスク(末尾)を基準
        # (offset=0)として各タスクのオフセットを記録する。これが無いと基準日変更時に付随タスクの
        # ずらし量を計算できず、編集したタスク1件しか動かない（=「他のやることの日付が変わらない」）。
        if n > 0:
            try:
                base_d = datetime.date.fromisoformat(dues[n - 1])
                for i in range(n):
                    offsets[i] = (base_d - datetime.date.fromisoformat(dues[i])).days
            except ValueError:
                pass

    return [
        {"name": s.get("name", ""), "lead_time_days": eff, "due_iso": d, "offset_days": off}
        for s, eff, d, off in zip(steps, effective, dues, offsets)
    ]


def _build_step_content(
    doc: dict,
    step: dict,
    idx: int,
    total: int,
    language: str,
    municipality: Optional[str] = None,
) -> str:
    """1手順ぶんのタスク本文。手順位置・平均所要日数の注意事項・手順締切・最終提出期限などを含む。"""
    ja = language != "en"
    lines: List[str] = []
    name = doc.get("name", "")
    if name:
        lines.append(f"{name}（手順 {idx}/{total}）" if ja else f"{name} (step {idx}/{total})")
    # SOT-1566: 推定由来の書類は各手順タスク本文にも「推定（要確認）」を明示する。
    if doc.get("inferred"):
        lines.append(_inferred_notice_line(ja))

    step_name = step.get("name", "")
    if step_name:
        lines.append(f"・{step_name}" if ja else f"- {step_name}")
        # 市区町村の窓口/公式HPから様式をDLする手順なら、設定済み市町村のDLページリンクを付与（SOT-1405）。
        # 単一手順で場所語＋取得語が揃う場合に加え、書類全体がDL型でこの手順が取得アクション
        # （DL/様式/取得/入手）の場合も付与する。grounding LLM が手順名を簡潔に出力して場所語が
        # 別手順に分かれても取りこぼさないようにするため（SOT-1405 3回目の再オープン対応）。
        if _is_municipality_download_step(step_name) or (
            _doc_has_municipality_download(doc) and _has_get_keyword(step_name)
        ):
            link = _download_link_line(municipality, name, ja)
            if link:
                lines.append(link)

    lead = step.get("lead_time_days")
    if isinstance(lead, int):
        lines.append(f"所要期間の目安: 約{lead}日" if ja else f"Estimated lead time: ~{lead} days")

    step_due = step.get("due_iso")
    if step_due:
        lines.append(f"この手順の締切: {step_due}" if ja else f"Step deadline: {step_due}")

    nci = doc.get("needs_company_issuance")
    if nci is True:
        lines.append("会社/勤務先の発行が必要です。" if ja else "Requires issuance by your employer.")
    elif nci is False:
        lines.append("会社発行は不要です。" if ja else "No employer issuance required.")

    due = doc.get("due_date")
    if due:
        lines.append(f"最終提出期限: {due}" if ja else f"Final submission deadline: {due}")
    else:
        # SOT-1598: 最終提出期限が本文から判明しないときは「不明」であることを明記する。
        # この場合の各手順の締切は本日起点で前向きに割り当てた目安なので、その旨も伝える。
        lines.append(
            "最終提出期限: 不明（本文に提出期限の記載がないため、上記の日付は本日起点の目安です）"
            if ja
            else "Final submission deadline: unknown (not stated in the notice; the dates above "
            "are estimates from today)"
        )

    # 根拠となる出典リンク（SOT-1404）: 各手順タスクにも grounding 由来の根拠リンクを表示する。
    source_lines = _format_source_links(doc.get("sources") or [], ja)
    if source_lines:
        lines.extend(source_lines)
    else:
        source = doc.get("source")
        if source:
            lines.append(f"出典: {source}" if ja else f"Source: {source}")

    return "\n".join(lines) if lines else (step_name or name or "")


def build_submission_task_drafts(
    safe_text: str,
    detected_dates: Optional[List[str]] = None,
    language: str = "ja",
    final_due_iso: Optional[str] = None,
    municipality: Optional[str] = None,
    issue_date: Optional[datetime.date] = None,
) -> List[dict]:
    """提出書類ごとの準備タスク draft（build_task_drafts と同形 + due_date/tags）を返す。

    手順情報がある書類は手順ごとにタスクを分割し、提出期限から各手順の所要期間を後ろ向きに
    逆算して各タスクの締切(event_date/due_date)を設定する。手順情報が無い書類は従来どおり
    1タスク（event_date=準備開始日）。tags に番兵 ``SUBMISSION_TAG`` を付ける（SOT-1339 の
    リマインド分類用）。常に never-throw。

    ``final_due_iso`` は締切調査の実行対象タスクに設定済みの期限（最優先の逆算アンカー。
    SOT-1399 4回目の再オープン対応）。

    ``municipality`` は登録/設定値の市町村（SOT-1405）。市区町村の窓口/公式ホームページから様式を
    ダウンロードする手順がある場合に、その市町村のダウンロードページ検索リンクを本文へ付与する。
    未設定（空/None）のときはリンクを付与しない。

    ``issue_date`` はおたよりの発行日/登録日（SOT-1567）。与えられると本文検出の締切を発行月
    コンテキストで整合チェックし、OCR誤読（例: 7→1 の 1/31）を疑わしい時だけ補正する。
    """
    try:
        docs = extract_submission_documents(
            safe_text, detected_dates, language, final_due_iso, issue_date
        )
    except Exception as e:  # noqa: BLE001 - graceful degradation
        logger.warning("build_submission_task_drafts failed: %s", e)
        return []

    suffix = "の準備" if language != "en" else " prep"
    drafts: List[dict] = []
    for doc in docs:
        name = doc.get("name", "")
        if not name:
            continue
        due_iso = doc.get("due_date") or ""
        steps = doc.get("steps") or []
        category_dict = {k: [] for k in extraction.ALL_CONTENT_KEYS}
        # SOT-1411: 1書類ぶんの手順タスク群をまとめるグループ識別子。基準日(最終提出期限=due_iso)を
        # 変更したとき、このグループの付随タスクを保存済みオフセットでまとめてずらす。
        group_id = uuid.uuid4().hex
        base_date = due_iso or ""

        if not steps:
            # 手順情報が無い書類は従来どおり 1 タスク（後方互換）
            prep_iso = _prep_start_iso(due_iso, doc.get("lead_time_days"))
            title = (f"{name}{suffix}")[:40]
            content = _build_content(doc, language, municipality)
            # 基準日が判明していれば「準備開始日が基準日から何日手前か」をオフセットとして記録する。
            offset_days = None
            if due_iso and prep_iso:
                try:
                    offset_days = (
                        datetime.date.fromisoformat(due_iso)
                        - datetime.date.fromisoformat(prep_iso)
                    ).days
                except ValueError:
                    offset_days = None
            drafts.append(
                {
                    "title": title,
                    "info_type": "提出物",
                    "content": content,
                    "items": "",
                    "date": "",
                    "event_date": prep_iso,
                    "due_date": due_iso,
                    "tags": SUBMISSION_TAG,
                    "deadline_group_id": group_id,
                    "deadline_offset_days": offset_days,
                    "deadline_base_date": base_date,
                    # SOT-1566: 推定由来（辞書/LLM推論）の書類フラグを下流（表示/確認導線）へ伝播。
                    "inferred": bool(doc.get("inferred", False)),
                    "categories": {"title": title, **category_dict},
                }
            )
            continue

        # 手順ごとにタスクを分割し、各手順の締切を後ろ向きに逆算する
        scheduled = _step_deadlines(due_iso, steps, doc.get("lead_time_days"))
        total = len(scheduled)
        # SOT-1411 再オープン対応: 最終提出期限が判明していればそれを、不明なら前向き累積した
        # 最終タスク(末尾)の日付をグループの基準日とする。空のままだと基準日変更で付随タスクを
        # ずらせない。
        step_base_date = due_iso or (scheduled[-1]["due_iso"] if scheduled else "")
        for i, step in enumerate(scheduled):
            step_due = step.get("due_iso") or ""
            # SOT-1420(再オープン): タイトル(表紙)に「書類名(何番目/全何ステップ) + 手順の要約文」を
            # 併記する。手順名が長文でも _step_subtitle で簡潔化し、文の途中で切れないようにする。
            # 手順の詳細本文は content 側(_build_step_content)に従来どおり残る。
            prefix = f"{name}({i + 1}/{total})"
            subtitle = _step_subtitle(step.get("name", ""))
            title = (f"{prefix} {subtitle}".rstrip())[:40]
            content = _build_step_content(
                doc, step, i + 1, total, language, municipality
            )
            drafts.append(
                {
                    "title": title,
                    "info_type": "提出物",
                    "content": content,
                    "items": "",
                    "date": "",
                    "event_date": step_due,
                    "due_date": step_due,
                    "tags": SUBMISSION_TAG,
                    "deadline_group_id": group_id,
                    "deadline_offset_days": step.get("offset_days"),
                    "deadline_base_date": step_base_date,
                    # SOT-1566: 推定由来（辞書/LLM推論）の書類フラグを下流（表示/確認導線）へ伝播。
                    "inferred": bool(doc.get("inferred", False)),
                    "categories": {"title": title, **category_dict},
                }
            )
    return drafts


def assign_anchor_group(drafts: List[dict], base_iso: str) -> str:
    """1回の締切調査で生成した全 draft を、base_iso(最終提出期限)を基準とする単一の締切グループに
    まとめ直すヘルパー(SOT-1411 再オープン対応)。

    build_submission_task_drafts は書類ごとに別グループ(別 group_id・別 base_date)を付けるが、
    締切調査の呼び出し元(手動: routers/info.py / 自動: routers/attachments.py)はこのヘルパーで
    全 draft を1グループに束ね、各 draft の deadline_offset_days を「基準日(base_iso)から何日手前か」
    = (base_iso - due_date).days で再計算する。これにより締切調査の元タスク(親)を同じグループの
    アンカー(offset 0)として加え、基準日変更で子タスクを一括でずらせるようにする。

    生成した group_id を返す。base_iso が空(最終提出期限なし)のときは drafts を変更せず "" を返す。
    常に never-throw。
    """
    if not base_iso:
        return ""
    try:
        base_d = datetime.date.fromisoformat(base_iso)
    except (TypeError, ValueError):
        return ""
    group_id = uuid.uuid4().hex
    for d in drafts:
        d["deadline_group_id"] = group_id
        d["deadline_base_date"] = base_iso
        offset_days: Optional[int] = None
        due = d.get("due_date") or ""
        if due:
            try:
                offset_days = (base_d - datetime.date.fromisoformat(due)).days
            except (TypeError, ValueError):
                offset_days = None
        d["deadline_offset_days"] = offset_days
    return group_id
