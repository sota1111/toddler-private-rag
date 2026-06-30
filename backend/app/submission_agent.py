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
import urllib.parse
import uuid
from typing import List, Optional

from . import ai_client, extraction

logger = logging.getLogger(__name__)

# 抽出する提出書類の上限（暴走防止）
_MAX_DOCUMENTS = 10
# 所要期間が不明なときに見込む既定の準備バッファ（日）
_DEFAULT_LEAD_DAYS = 3
# リマインド側(SOT-1339)が提出書類を区別するためのタグ番兵
SUBMISSION_TAG = "提出書類"

# おたより本文から締切候補を拾うための日付パターン（ocr.py の検出と同等）。
_DATE_PATTERNS = (
    r"\d{4}[-/]\d{1,2}[-/]\d{1,2}",          # 2026-07-31, 2026/7/31
    r"\d{1,2}月\d{1,2}日",                   # 7月31日（年は当年と仮定）
    r"(?:令和|平成|昭和)\d{1,2}年\d{1,2}月\d{1,2}日",  # 令和8年7月31日
)


def _detect_deadline_iso(text: str) -> str:
    """本文中の日付のうち最も遅い日付を ISO で返す（提出期限の代替アンカー）。

    LLM が書類に締切を紐づけられなかった場合でも、おたよりに書かれた締切（例: 7/31）を
    各手順の逆算アンカーとして利用するためのフォールバック。見つからなければ ""。常に never-throw。
    """
    if not text:
        return ""
    isos: List[str] = []
    try:
        for pattern in _DATE_PATTERNS:
            for raw in re.findall(pattern, text):
                iso = extraction.normalize_date(raw)
                if iso:
                    isos.append(iso)
    except Exception as e:  # noqa: BLE001 - best-effort
        logger.warning("deadline date detection failed: %s", e)
        return ""
    return max(isos) if isos else ""


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

    grounding LLM の手順名は時に長い動作文（例: 「勤務先（会社の人事や総務担当部署）に様式を
    提出し、証明書の記入・発行を依頼する」）になり、そのままタイトルに使うと文の途中で切れて
    読めない（SOT-1402 再オープン）。最初の自然な区切り（、。・/改行）までを見出しとして採用し、
    なお長い場合は字数で丸めて末尾に「…」を付ける。手順名フルは本文側に残るため情報は失われない。
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


def _llm_extract_documents(safe_text: str, language: str) -> List[dict]:
    """提出が必要な書類とその提出期限のみを抽出する LLM ステップ。失敗時は例外。"""
    client = ai_client.get_genai_client()
    model = ai_client.get_model_name()
    language_name = extraction._LANGUAGE_NAMES.get(
        language, extraction._LANGUAGE_NAMES["ja"]
    )
    prompt = (
        "You extract ONLY the documents/forms that a parent must SUBMIT "
        "(提出が必要な書類) from a nursery-school notice. "
        "Ignore anything that is not a submittable document (events, belongings, general notes). "
        "Output ONLY a JSON array. If none apply, return [].\n"
        "Each element has this shape:\n"
        '{"name":"the document name",'
        '"due_date":"the submission deadline as M月D日 or YYYY-MM-DD; empty string if unknown"}\n'
        "Do not invent documents that are not present in the source text.\n"
        f"Write name in {language_name}.\n\n"
        f"# Body\n{safe_text}\n\n"
        "# Example output\n"
        '[{"name":"健康調査票","due_date":"5月1日"},'
        '{"name":"就労証明書","due_date":"2026-05-10"}]\n\n'
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
        docs.append({"name": name, "due_date": due_raw})
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
    if not safe_text.strip() or not ai_client.gemini_available():
        return []

    try:
        docs = _llm_extract_documents(safe_text, language)
    except Exception as e:  # noqa: BLE001 - graceful degradation
        logger.warning("submission document extraction failed: %s", e)
        return []

    # タスク自身に設定済みの最終期限（最優先アンカー）。
    explicit_due_iso = extraction.normalize_date(final_due_iso) if final_due_iso else ""
    # LLM が書類に締切を紐づけられなかったときの逆算アンカー（本文の最も遅い日付）。
    fallback_due_iso = _detect_deadline_iso(safe_text)

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


def _build_content(
    doc: dict, language: str, municipality: Optional[str] = None
) -> str:
    """書類の手順/会社発行要否/所要期間/提出期限/出典を読みやすい本文にまとめる。"""
    ja = language != "en"
    lines: List[str] = []
    name = doc.get("name", "")
    if name:
        lines.append(name)

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
    """
    try:
        docs = extract_submission_documents(
            safe_text, detected_dates, language, final_due_iso
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
                    "categories": {"title": title, **category_dict},
                }
            )
            continue

        # 手順ごとにタスクを分割し、各手順の締切を後ろ向きに逆算する
        scheduled = _step_deadlines(due_iso, steps, doc.get("lead_time_days"))
        total = len(scheduled)
        for i, step in enumerate(scheduled):
            step_due = step.get("due_iso") or ""
            step_name = step.get("name", "")
            # ステップ番号（何番目/全何ステップ）+ 簡潔なサブタイトルをタイトルに付ける
            # （例: 在籍証明書(1/5) サブタイトル）。手順名が長文でも途中切れせず読める見出しにする。
            prefix = f"{name}({i + 1}/{total})"
            subtitle = _step_subtitle(step_name)
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
                    "deadline_base_date": base_date,
                    "categories": {"title": title, **category_dict},
                }
            )
    return drafts
