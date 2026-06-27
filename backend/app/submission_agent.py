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
from typing import List, Optional

from . import ai_client, extraction

logger = logging.getLogger(__name__)

# 抽出する提出書類の上限（暴走防止）
_MAX_DOCUMENTS = 10
# 所要期間が不明なときに見込む既定の準備バッファ（日）
_DEFAULT_LEAD_DAYS = 3
# リマインド側(SOT-1339)が提出書類を区別するためのタグ番兵
SUBMISSION_TAG = "提出書類"


def _extract_json_object(text: str) -> dict:
    """LLM 応答テキストから最初の JSON オブジェクトを取り出してパースする。"""
    if not text:
        raise ValueError("empty LLM response")
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no JSON object in LLM response")
    return json.loads(text[start : end + 1])


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
        '{"steps":["concise step", "..."],'
        '"needs_company_issuance":true or false or null,'
        '"lead_time_days":<integer number of days to obtain it, or null>,'
        '"source":"the official source URL or name, or empty string"}\n'
        '"needs_company_issuance" means whether the document must be issued by an employer / company '
        "(e.g. 就労証明書). Use null if unknown.\n"
        f"Write the steps in {language_name}. Do not fabricate; use null/empty when unknown.\n\n"
        "# Output (JSON object only)"
    )
    raw = ai_client.generate_grounded(prompt, max_output_tokens=1024)

    steps: List[str] = []
    needs_company: Optional[bool] = None
    lead_days: Optional[int] = None
    source = ""
    try:
        obj = _extract_json_object(raw)
        raw_steps = obj.get("steps")
        if isinstance(raw_steps, list):
            steps = [str(s).strip() for s in raw_steps if str(s).strip()]
        elif isinstance(raw_steps, str) and raw_steps.strip():
            steps = [raw_steps.strip()]
        nci = obj.get("needs_company_issuance")
        if isinstance(nci, bool):
            needs_company = nci
        lt = obj.get("lead_time_days")
        if isinstance(lt, bool):
            lt = None
        if isinstance(lt, (int, float)):
            lead_days = int(lt)
        elif isinstance(lt, str) and lt.strip().isdigit():
            lead_days = int(lt.strip())
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

    返り値 dict: ``{name, due_date(ISO or ""), steps(list[str]),
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

    enriched: List[dict] = []
    for doc in docs:
        name = doc.get("name", "")
        if not name:
            continue
        due_iso = extraction.normalize_date(doc.get("due_date")) or ""
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
            lines.append(f"・{s}" if ja else f"- {s}")

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


def build_submission_task_drafts(
    safe_text: str,
    detected_dates: Optional[List[str]] = None,
    language: str = "ja",
) -> List[dict]:
    """提出書類ごとの準備タスク draft（build_task_drafts と同形 + due_date/tags）を返す。

    提出期限から所要期間を逆算して event_date(準備開始日) を設定し、tags に番兵
    ``SUBMISSION_TAG`` を付ける（SOT-1339 のリマインド分類用）。常に never-throw。
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
        prep_iso = _prep_start_iso(due_iso, doc.get("lead_time_days"))
        title = (f"{name}{suffix}")[:40]
        content = _build_content(doc, language)
        category_dict = {k: [] for k in extraction.ALL_CONTENT_KEYS}
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
    return drafts
