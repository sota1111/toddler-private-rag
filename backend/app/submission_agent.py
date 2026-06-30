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
    raw = ai_client.generate_grounded(prompt, max_output_tokens=1024)

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

    return {
        "steps": steps,
        "needs_company_issuance": needs_company,
        "lead_time_days": lead_days,
        "source": source,
    }


def extract_submission_documents(
    safe_text: str,
    detected_dates: Optional[List[str]] = None,
    language: str = "ja",
) -> List[dict]:
    """提出書類を抽出し、grounding で公式情報を付与した dict のリストを返す。

    返り値 dict: ``{name, due_date(ISO or ""), steps(list[{name, lead_time_days}]),
    needs_company_issuance(bool|None), lead_time_days(int|None), source(str)}``.
    safe_text が空、または AI クライアント不可のときは空リスト。常に never-throw。
    """
    safe_text = safe_text or ""
    if not safe_text.strip() or not ai_client.gemini_available():
        return []

    try:
        docs = _llm_extract_documents(safe_text, language)
    except Exception as e:  # noqa: BLE001 - graceful degradation
        logger.warning("submission document extraction failed: %s", e)
        return []

    # LLM が書類に締切を紐づけられなかったときの逆算アンカー（本文の最も遅い日付）。
    fallback_due_iso = _detect_deadline_iso(safe_text)

    enriched: List[dict] = []
    for doc in docs:
        name = doc.get("name", "")
        if not name:
            continue
        # 書類固有の締切が無ければ本文から拾った最終締切で逆算する（前向き累積に落とさない）。
        due_iso = extraction.normalize_date(doc.get("due_date")) or fallback_due_iso
        try:
            info = _grounded_enrich(name, language)
        except Exception as e:  # noqa: BLE001 - never let one doc break the batch
            logger.warning("submission enrich failed for %s: %s", name, e)
            info = {
                "steps": [],
                "needs_company_issuance": None,
                "lead_time_days": None,
                "source": "",
            }
        enriched.append(
            {
                "name": name,
                "due_date": due_iso,
                "steps": info["steps"],
                "needs_company_issuance": info["needs_company_issuance"],
                "lead_time_days": info["lead_time_days"],
                "source": info["source"],
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


def _build_content(doc: dict, language: str) -> str:
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
    if due is not None:
        cursor = due
        # 末尾(最終提出)から先頭へ、各手順の所要日数だけ遡って締切を決める
        for i in range(n - 1, -1, -1):
            cursor = cursor - datetime.timedelta(days=effective[i])
            dues[i] = cursor.isoformat()
    else:
        # 最終期限が不明なときは本日起点で前向きに累積し、各手順に具体日付を割り当てる
        cursor = _today()
        for i in range(n):
            cursor = cursor + datetime.timedelta(days=effective[i])
            dues[i] = cursor.isoformat()

    return [
        {"name": s.get("name", ""), "lead_time_days": eff, "due_iso": d}
        for s, eff, d in zip(steps, effective, dues)
    ]


def _build_step_content(
    doc: dict, step: dict, idx: int, total: int, language: str
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

    source = doc.get("source")
    if source:
        lines.append(f"出典: {source}" if ja else f"Source: {source}")

    return "\n".join(lines) if lines else (step_name or name or "")


def build_submission_task_drafts(
    safe_text: str,
    detected_dates: Optional[List[str]] = None,
    language: str = "ja",
) -> List[dict]:
    """提出書類ごとの準備タスク draft（build_task_drafts と同形 + due_date/tags）を返す。

    手順情報がある書類は手順ごとにタスクを分割し、提出期限から各手順の所要期間を後ろ向きに
    逆算して各タスクの締切(event_date/due_date)を設定する。手順情報が無い書類は従来どおり
    1タスク（event_date=準備開始日）。tags に番兵 ``SUBMISSION_TAG`` を付ける（SOT-1339 の
    リマインド分類用）。常に never-throw。
    """
    try:
        docs = extract_submission_documents(safe_text, detected_dates, language)
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

        if not steps:
            # 手順情報が無い書類は従来どおり 1 タスク（後方互換）
            prep_iso = _prep_start_iso(due_iso, doc.get("lead_time_days"))
            title = (f"{name}{suffix}")[:40]
            content = _build_content(doc, language)
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
            # ステップ番号（何番目/全何ステップ）をタイトルに付ける（例: 在籍証明書(1/5) サブタイトル）
            prefix = f"{name}({i + 1}/{total})"
            title = (f"{prefix} {step_name}".rstrip())[:40]
            content = _build_step_content(doc, step, i + 1, total, language)
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
                    "categories": {"title": title, **category_dict},
                }
            )
    return drafts
