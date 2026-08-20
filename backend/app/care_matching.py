"""SOT-2733: おたより内容 × 個別配慮プロファイル 照合エンジン v1（辞書 × LLM・根拠必須・棄権）。

届いたおたより（抽出テキスト／献立 ``menu_json`` の原材料）と、子ども一人ひとりの個別配慮
プロファイル（SOT-2729 ``CareProfile``：アレルゲン・配慮カテゴリ・自由記述）を突き合わせ、
**根拠付きの「要確認（Attention）」候補** を生成する。

設計原則（親 SOT-2728 / Deliverable 12 S4）:

1. **決定論辞書で一次照合**（SOT-2730 ``care_normalization``）。表記ゆれを正規形へ寄せてから
   突き合わせるので、同じ入力に対して常に同じ候補集合を返す（テスト可能・監査可能）。
2. **献立 ``menu_json`` の原材料を第一根拠**に使う。アレルゲンは献立の品目/主要食材から拾うのを
   最優先とし（confidence=high）、本文テキストからの検出は補助（confidence=medium）。
3. **LLM クロスチェックは文脈確認のみで、断定はしない**。決定論が出した Attention を消したり
   格下げしたりは絶対にしない。LLM は (a) 既存候補への補足ノート付与か、(b) 辞書が取りこぼした
   曖昧候補を **棄権（要確認）** として追加する方向にだけ働く。オフライン/失敗時は静かに無視。
4. **各候補に根拠を必須付与**：``evidence`` に「該当文書箇所(span)」「対応プロファイル項目
   (profile_item)」「信頼度(confidence)」を必ず含める。根拠なしの候補は作らない。
5. **情報不足・曖昧時は棄権**：沈黙で通さず「情報不足のため要確認」を明示する候補を立てる
   （例：食に関する予定があるのに献立の原材料情報が無く、アレルゲン該当を断定できない）。

この照合層自体は I/O を持たない純ロジック（LLM 呼び出しを除く）。呼び出し側が
``CareProfile`` とおたより本文・``menu_json`` を渡す。返り値は API/UI から扱いやすい dict。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from . import ai_client, care_normalization as cn

logger = logging.getLogger(__name__)

# 候補の種別・状態（安定キー）。
KIND_ALLERGEN = "allergen"
KIND_CARE_CATEGORY = "care_category"

STATUS_ATTENTION = "attention"  # 要確認候補（根拠あり）
STATUS_ABSTAIN = "abstain"      # 情報不足のため要確認（断定しない棄権）

# 信頼度（安定キー）。
CONF_HIGH = "high"      # 献立原材料など第一根拠での辞書一致
CONF_MEDIUM = "medium"  # 本文テキストでの辞書一致
CONF_LOW = "low"        # 棄権（情報不足・曖昧）

# おたよりに「食に関する予定」があると判断するためのキーワード（棄権判定に使用）。
# 献立の原材料情報が無いのにこれらがあると、アレルゲン該当を断定できない＝棄権にする。
_FOOD_EVENT_KEYWORDS = (
    "給食", "おやつ", "間食", "試食", "試食会", "クッキング", "クッキング保育",
    "調理", "調理保育", "食育", "バイキング", "お弁当作り", "おやつ作り", "会食",
    "誕生会", "誕生日会", "パーティ",
)

# LLM クロスチェックで一度に見せる候補件数の上限（プロンプト肥大の防止）。
_LLM_MAX_CANDIDATES = 20


# --- プロファイル読み取り（object / dict 両対応） --------------------------------


def _pget(profile: Any, key: str, default: Any = None) -> Any:
    """``CareProfile`` オブジェクト or dict の両方から属性を安全に読む。"""
    if profile is None:
        return default
    if isinstance(profile, dict):
        value = profile.get(key, default)
    else:
        value = getattr(profile, key, default)
    return default if value is None else value


def _profile_allergen_pairs(profile: Any) -> List[Dict[str, str]]:
    """プロファイルの生アレルゲン表記 → {raw, canonical} のリスト（未知語は除外）。"""
    pairs: List[Dict[str, str]] = []
    seen = set()
    for raw in _pget(profile, "allergens", []) or []:
        canonical = cn.normalize_allergen(raw)
        if canonical and canonical not in seen:
            seen.add(canonical)
            pairs.append({"raw": str(raw), "canonical": canonical})
    return pairs


def _profile_category_pairs(profile: Any) -> List[Dict[str, str]]:
    """プロファイルの生配慮カテゴリ表記 → {raw, canonical} のリスト（未知語は除外）。"""
    pairs: List[Dict[str, str]] = []
    seen = set()
    for raw in _pget(profile, "care_categories", []) or []:
        canonical = cn.normalize_care_category(raw)
        if canonical and canonical not in seen:
            seen.add(canonical)
            pairs.append({"raw": str(raw), "canonical": canonical})
    return pairs


# --- 献立 menu_json からの品目テキスト抽出 ---------------------------------------

_MENU_ITEM_KEYS = ("morning_snack", "lunch", "afternoon_snack")
_MENU_ING_KEYS = ("red", "yellow", "green", "other")


def _menu_day_items(day: Dict[str, Any]) -> List[str]:
    """1日分の献立レコードから、走査対象の品目/食材文字列を平坦なリストで返す。"""
    items: List[str] = []
    for key in _MENU_ITEM_KEYS:
        for it in day.get(key) or []:
            if it is not None and str(it).strip():
                items.append(str(it).strip())
    mi = day.get("main_ingredients") or {}
    for key in _MENU_ING_KEYS:
        for it in mi.get(key) or []:
            if it is not None and str(it).strip():
                items.append(str(it).strip())
    return items


def _snippet(text: str, needle_surfaces, *, width: int = 24) -> str:
    """本文から該当箇所周辺の短いスニペットを切り出す（根拠 span 用）。見つからなければ先頭。"""
    if not text:
        return ""
    lowered = text
    for surface in needle_surfaces or []:
        idx = lowered.find(surface)
        if idx != -1:
            start = max(0, idx - width // 2)
            end = min(len(text), idx + len(surface) + width // 2)
            span = text[start:end].strip()
            return ("…" if start > 0 else "") + span + ("…" if end < len(text) else "")
    return text[:width].strip() + ("…" if len(text) > width else "")


# --- 候補生成 ---------------------------------------------------------------------


def _make_candidate(
    *,
    kind: str,
    status: str,
    canonical: Optional[str],
    profile_item: Dict[str, str],
    source: str,
    span: str,
    confidence: str,
    locator: Optional[Dict[str, Any]] = None,
    message: str,
) -> Dict[str, Any]:
    """根拠(evidence)必須の候補 dict を組み立てる。根拠3要素を必ず埋める。"""
    profile_label = profile_item.get("raw") or profile_item.get("canonical") or ""
    return {
        "kind": kind,
        "status": status,
        "canonical": canonical,
        "profile_item": profile_item,
        "evidence": {
            # 根拠の3要素（受け入れ条件）。
            "source": source,               # menu_json | notice_text
            "span": span,                   # 該当文書箇所
            "profile_item": profile_label,  # 対応プロファイル項目
            "confidence": confidence,       # 信頼度
            "locator": locator or {},       # 位置情報（献立の日付 等）
        },
        "message": message,
    }


def _allergen_menu_candidates(
    allergen_pairs: List[Dict[str, str]], menu_json: Optional[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """献立 ``menu_json`` の原材料を第一根拠に、アレルゲン該当候補を生成（confidence=high）。"""
    out: List[Dict[str, Any]] = []
    if not allergen_pairs or not isinstance(menu_json, dict):
        return out
    by_canonical = {p["canonical"]: p for p in allergen_pairs}
    for day in menu_json.get("days") or []:
        if not isinstance(day, dict):
            continue
        date = day.get("date")
        for item in _menu_day_items(day):
            for canonical in cn.scan_allergens(item):
                pair = by_canonical.get(canonical)
                if pair is None:
                    continue
                date_label = f"（{date}）" if date else ""
                out.append(
                    _make_candidate(
                        kind=KIND_ALLERGEN,
                        status=STATUS_ATTENTION,
                        canonical=canonical,
                        profile_item=pair,
                        source="menu_json",
                        span=f"{date_label}{item}".strip(),
                        confidence=CONF_HIGH,
                        locator={"date": date, "item": item},
                        message=(
                            f"献立{date_label}の「{item}」がアレルゲン『{pair['raw']}』"
                            f"（{canonical}）に該当する可能性があります。要確認。"
                        ),
                    )
                )
    return out


def _allergen_text_candidates(
    allergen_pairs: List[Dict[str, str]], notice_text: Optional[str]
) -> List[Dict[str, Any]]:
    """おたより本文テキストからのアレルゲン言及を補助根拠に候補化（confidence=medium）。"""
    out: List[Dict[str, Any]] = []
    if not allergen_pairs or not notice_text:
        return out
    by_canonical = {p["canonical"]: p for p in allergen_pairs}
    for canonical in cn.scan_allergens(notice_text):
        pair = by_canonical.get(canonical)
        if pair is None:
            continue
        span = _snippet(notice_text, cn._ALLERGEN_ALIASES.get(canonical, ()))
        out.append(
            _make_candidate(
                kind=KIND_ALLERGEN,
                status=STATUS_ATTENTION,
                canonical=canonical,
                profile_item=pair,
                source="notice_text",
                span=span,
                confidence=CONF_MEDIUM,
                message=(
                    f"おたより本文にアレルゲン『{pair['raw']}』（{canonical}）に関する記載があります。"
                    f"要確認。"
                ),
            )
        )
    return out


def _care_category_candidates(
    category_pairs: List[Dict[str, str]], notice_text: Optional[str]
) -> List[Dict[str, Any]]:
    """配慮カテゴリ × 本文の決定論一致で候補化（両者辞書確定なので confidence=high）。"""
    out: List[Dict[str, Any]] = []
    if not category_pairs or not notice_text:
        return out
    found = set(cn.scan_care_categories(notice_text))
    by_canonical = {p["canonical"]: p for p in category_pairs}
    for canonical in cn.scan_care_categories(notice_text):
        if canonical not in by_canonical:
            continue
        pair = by_canonical[canonical]
        span = _snippet(notice_text, cn._CARE_CATEGORY_KEYWORDS.get(canonical, ()))
        out.append(
            _make_candidate(
                kind=KIND_CARE_CATEGORY,
                status=STATUS_ATTENTION,
                canonical=canonical,
                profile_item=pair,
                source="notice_text",
                span=span,
                confidence=CONF_HIGH,
                message=(
                    f"おたよりに配慮カテゴリ『{pair['raw']}』（{canonical}）に該当する予定の記載が"
                    f"あります。要確認。"
                ),
            )
        )
    return out


def _abstain_candidates(
    profile: Any,
    allergen_pairs: List[Dict[str, str]],
    category_pairs: List[Dict[str, str]],
    notice_text: Optional[str],
    menu_json: Optional[Dict[str, Any]],
    attention: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """情報不足・曖昧なケースを「情報不足のため要確認」＝棄権候補として明示する。"""
    out: List[Dict[str, Any]] = []
    has_menu = isinstance(menu_json, dict) and bool(menu_json.get("days"))

    # 棄権1: 食に関する予定があるのに献立の原材料情報が無い → アレルゲン該当を断定できない。
    if allergen_pairs and notice_text and not has_menu:
        food_hit = next((k for k in _FOOD_EVENT_KEYWORDS if k in notice_text), None)
        if food_hit is not None:
            labels = "・".join(p["raw"] for p in allergen_pairs)
            out.append(
                _make_candidate(
                    kind=KIND_ALLERGEN,
                    status=STATUS_ABSTAIN,
                    canonical=None,
                    profile_item={"raw": labels, "canonical": ""},
                    source="notice_text",
                    span=_snippet(notice_text, (food_hit,)),
                    confidence=CONF_LOW,
                    message=(
                        f"食に関する予定（「{food_hit}」）の記載がありますが、献立の原材料情報が"
                        f"無いため、アレルゲン（{labels}）該当を断定できません。情報不足のため要確認。"
                    ),
                )
            )

    # 棄権2: 自由記述の配慮事項があり、本文に配慮カテゴリの記載はあるが、それが構造化カテゴリに
    #        含まれない（＝辞書で断定できない）→ 曖昧として棄権。
    free_text = str(_pget(profile, "free_text", "") or "").strip()
    if free_text and notice_text:
        structured = {p["canonical"] for p in category_pairs}
        for canonical in cn.scan_care_categories(notice_text):
            if canonical in structured:
                continue
            out.append(
                _make_candidate(
                    kind=KIND_CARE_CATEGORY,
                    status=STATUS_ABSTAIN,
                    canonical=canonical,
                    profile_item={"raw": free_text[:40], "canonical": ""},
                    source="notice_text",
                    span=_snippet(notice_text, cn._CARE_CATEGORY_KEYWORDS.get(canonical, ())),
                    confidence=CONF_LOW,
                    message=(
                        f"おたよりに配慮に関わりうる記載（{canonical}）がありますが、構造化された配慮"
                        f"カテゴリに無く、自由記述との関連を断定できません。情報不足のため要確認。"
                    ),
                )
            )
            break  # 曖昧棄権は1件で十分（ノイズ抑制）。
    return out


# --- LLM クロスチェック（文脈確認のみ・断定しない・best-effort） -------------------


def _llm_crosscheck(
    profile: Any,
    notice_text: Optional[str],
    menu_json: Optional[Dict[str, Any]],
    candidates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """LLM で文脈確認する（断定しない）。返り値は「追加の棄権候補」または既存候補への注記。

    契約:
    - 決定論が出した Attention は **絶対に消さない/格下げしない**（呼び出し側でマージ）。
    - LLM は (a) 既存候補 index への ``note`` か、(b) 辞書が取りこぼした曖昧項目を
      ``status="abstain"`` の要確認として提案するだけ。ハードな断定はしない。
    - オフライン/SDK 差異/失敗は静かに ``[]``（決定論のみで動作）。
    """
    if not ai_client.gemini_available():
        return []
    try:
        allergens = [p["raw"] for p in _profile_allergen_pairs(profile)]
        categories = [p["raw"] for p in _profile_category_pairs(profile)]
        free_text = str(_pget(profile, "free_text", "") or "").strip()
        det_lines = [
            f"{i}: [{c['kind']}/{c['status']}] {c['message']}"
            for i, c in enumerate(candidates[:_LLM_MAX_CANDIDATES])
        ]
        menu_summary = ""
        if isinstance(menu_json, dict):
            days = menu_json.get("days") or []
            menu_summary = "; ".join(
                f"{d.get('date')}:{'/'.join(_menu_day_items(d)[:8])}"
                for d in days[:10]
                if isinstance(d, dict)
            )
        prompt = (
            "あなたは保育園のおたよりと、子どもの個別配慮プロファイルを突き合わせる確認アシスタントです。"
            "決定論辞書が既に一次照合を済ませています。あなたの役割は文脈の確認のみで、"
            "**断定・診断・安全宣言はしません**。辞書が取りこぼした可能性がある曖昧な該当だけを、"
            "『情報不足のため要確認』として控えめに指摘してください。既存候補を否定しないでください。\n\n"
            f"# プロファイル\nアレルゲン: {allergens}\n配慮カテゴリ: {categories}\n自由記述: {free_text}\n\n"
            f"# おたより本文\n{(notice_text or '')[:2000]}\n\n"
            f"# 献立(要約)\n{menu_summary}\n\n"
            f"# 既存の決定論候補\n" + ("\n".join(det_lines) or "(なし)") + "\n\n"
            "# 出力(JSONのみ)\n"
            '{"notes":[{"index":<既存候補の番号>,"note":"<補足>"}],'
            '"abstain":[{"kind":"allergen|care_category","reason":"<なぜ曖昧か>","span":"<本文の該当箇所>"}]}'
        )
        client = ai_client.get_genai_client()
        model = ai_client.get_model_name()
        cfg = ai_client.default_generate_config()

        def _gen():
            if cfg is not None:
                return client.models.generate_content(model=model, contents=prompt, config=cfg)
            return client.models.generate_content(model=model, contents=prompt)

        response = ai_client.with_retry(_gen)
        text = (getattr(response, "text", "") or "").strip()
        data = _extract_json(text)
    except Exception as e:  # noqa: BLE001 - LLM は best-effort。失敗しても決定論で動く。
        logger.warning("care matching LLM cross-check failed (ignored): %s", type(e).__name__)
        return []

    # (a) 既存候補への注記（非破壊。既存の attention は消さない）。
    for note in data.get("notes") or []:
        try:
            idx = int(note.get("index"))
            text_note = str(note.get("note") or "").strip()
        except (TypeError, ValueError):
            continue
        if text_note and 0 <= idx < len(candidates):
            candidates[idx].setdefault("llm_notes", []).append(text_note[:300])

    # (b) LLM 由来の追加「棄権（要確認）」候補（断定しない）。
    extra: List[Dict[str, Any]] = []
    for ab in data.get("abstain") or []:
        kind = ab.get("kind")
        if kind not in (KIND_ALLERGEN, KIND_CARE_CATEGORY):
            continue
        reason = str(ab.get("reason") or "").strip()
        span = str(ab.get("span") or "").strip()[:120]
        if not reason:
            continue
        extra.append(
            _make_candidate(
                kind=kind,
                status=STATUS_ABSTAIN,
                canonical=None,
                profile_item={"raw": "(LLM 文脈確認)", "canonical": ""},
                source="llm",
                span=span or reason[:40],
                confidence=CONF_LOW,
                message=f"（LLM 文脈確認）{reason} 情報不足のため要確認。",
            )
        )
    return extra


def _extract_json(text: str) -> Dict[str, Any]:
    """LLM 応答から最初の JSON オブジェクトを取り出してパースする。失敗時は例外。"""
    if not text:
        raise ValueError("empty LLM response")
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no JSON object in LLM response")
    obj = json.loads(text[start : end + 1])
    if not isinstance(obj, dict):
        raise ValueError("LLM response is not a JSON object")
    return obj


# --- 公開 API ---------------------------------------------------------------------


def _dedupe(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """(kind, status, canonical, source, span) が同一の候補を1つに畳む（順序保持）。"""
    out: List[Dict[str, Any]] = []
    seen = set()
    for c in candidates:
        ev = c.get("evidence", {})
        key = (c.get("kind"), c.get("status"), c.get("canonical"), ev.get("source"), ev.get("span"))
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def match_notice(
    profile: Any,
    *,
    notice_text: Optional[str] = None,
    menu_json: Optional[Dict[str, Any]] = None,
    use_llm: bool = True,
) -> Dict[str, Any]:
    """おたより（本文・献立）× 個別配慮プロファイルを照合し、根拠付き要確認候補を返す。

    返り値::

        {
          "candidates": [ {kind, status, canonical, profile_item, evidence{...}, message}, ... ],
          "attention_count": int,   # status=attention の件数
          "abstain_count": int,     # status=abstain（情報不足のため要確認）の件数
          "has_profile_data": bool, # プロファイルに突き合わせ対象データがあったか
        }

    - 決定論辞書での一次照合を必ず行い、``menu_json`` の原材料を第一根拠に使う。
    - ``use_llm`` かつ AI クライアント利用可能時のみ LLM で文脈確認する（断定はしない・
      既存 attention は非破壊）。オフライン/失敗時は決定論のみで動作する（同入力→同出力）。
    - すべての候補は ``evidence`` に「該当文書箇所 / 対応プロファイル項目 / 信頼度」を必ず持つ。
    """
    allergen_pairs = _profile_allergen_pairs(profile)
    category_pairs = _profile_category_pairs(profile)
    free_text = str(_pget(profile, "free_text", "") or "").strip()
    has_profile_data = bool(allergen_pairs or category_pairs or free_text)

    candidates: List[Dict[str, Any]] = []
    # 1) 決定論一次照合（献立を第一根拠に）。
    candidates += _allergen_menu_candidates(allergen_pairs, menu_json)
    candidates += _allergen_text_candidates(allergen_pairs, notice_text)
    candidates += _care_category_candidates(category_pairs, notice_text)
    # 2) 情報不足・曖昧 → 棄権（明示的に要確認）。
    candidates += _abstain_candidates(
        profile, allergen_pairs, category_pairs, notice_text, menu_json, candidates
    )

    candidates = _dedupe(candidates)

    # 3) LLM クロスチェック（文脈確認のみ・断定しない・best-effort）。
    if use_llm and has_profile_data:
        try:
            extra = _llm_crosscheck(profile, notice_text, menu_json, candidates)
            candidates = _dedupe(candidates + extra)
        except Exception as e:  # noqa: BLE001 - 二重の安全網。決定論結果は保持。
            logger.warning("care matching LLM stage error (ignored): %s", type(e).__name__)

    attention_count = sum(1 for c in candidates if c["status"] == STATUS_ATTENTION)
    abstain_count = sum(1 for c in candidates if c["status"] == STATUS_ABSTAIN)
    return {
        "candidates": candidates,
        "attention_count": attention_count,
        "abstain_count": abstain_count,
        "has_profile_data": has_profile_data,
    }
