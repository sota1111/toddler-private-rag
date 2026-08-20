"""SOT-2733: おたより × 個別配慮プロファイル 照合エンジン v1 の単体テスト。

検証観点（受け入れ条件対応）:
- プロファイルと関連するおたより記載を「要確認候補」として検出できる（陽性）。
- 関連しない記載では候補を出さない（陰性）。
- 全候補に根拠（該当文書箇所・対応プロファイル項目・信頼度）が付与される。
- 情報不足・曖昧時は断定せず「情報不足のため要確認（棄権）」になる。
- 決定論的（同入力→同出力）で、LLM はオフライン時に無視される（best-effort）。
"""

import pytest

from app import care_matching as cm
from app import care_normalization as cn


# --- テスト用のプロファイル簡易ダブル（CareProfile 互換の dict でも動く） ----------


class _Profile:
    def __init__(self, allergens=None, care_categories=None, free_text=None, severity_note=None):
        self.allergens = allergens or []
        self.care_categories = care_categories or []
        self.free_text = free_text
        self.severity_note = severity_note


def _menu(day_date, *, lunch=None, red=None, yellow=None, green=None, other=None):
    return {
        "month": day_date[:7],
        "days": [
            {
                "date": day_date,
                "lunch": lunch or [],
                "main_ingredients": {
                    "red": red or [],
                    "yellow": yellow or [],
                    "green": green or [],
                    "other": other or [],
                },
            }
        ],
    }


def _all_have_evidence(result):
    """全候補が根拠3要素（該当文書箇所・対応プロファイル項目・信頼度）を持つことを検証。"""
    assert result["candidates"], "候補が空"
    for c in result["candidates"]:
        ev = c["evidence"]
        assert ev.get("span"), f"span 欠落: {c}"
        assert ev.get("profile_item"), f"profile_item 欠落: {c}"
        assert ev.get("confidence") in (cm.CONF_HIGH, cm.CONF_MEDIUM, cm.CONF_LOW), c
        assert ev.get("source") in ("menu_json", "notice_text", "llm"), c


# =========================== 陽性（Attention 検出） ===============================


def test_allergen_in_menu_ingredient_is_detected_with_high_confidence():
    """献立の主要食材にアレルゲン → 第一根拠(menu_json)・confidence=high で検出。"""
    profile = _Profile(allergens=["たまご"])  # 正規形 egg
    menu = _menu("2026-09-01", red=["鶏卵", "豆腐"], lunch=["親子丼"])
    result = cm.match_notice(profile, notice_text="9月の献立表", menu_json=menu, use_llm=False)

    egg = [c for c in result["candidates"] if c["canonical"] == "egg"]
    assert egg, "卵アレルゲンが検出されない"
    c = egg[0]
    assert c["kind"] == cm.KIND_ALLERGEN
    assert c["status"] == cm.STATUS_ATTENTION
    assert c["evidence"]["source"] == "menu_json"
    assert c["evidence"]["confidence"] == cm.CONF_HIGH
    assert c["evidence"]["locator"]["date"] == "2026-09-01"
    assert result["attention_count"] >= 1
    _all_have_evidence(result)


def test_allergen_in_composite_menu_item_via_substring_scan():
    """辞書に完全一致しない品目「厚焼き玉子」でも部分一致で卵を拾える（安全側）。"""
    profile = _Profile(allergens=["卵"])
    menu = _menu("2026-09-02", lunch=["厚焼き玉子", "みそ汁"])
    result = cm.match_notice(profile, menu_json=menu, use_llm=False)
    assert any(c["canonical"] == "egg" for c in result["candidates"])


def test_allergen_mentioned_in_notice_text_is_medium_confidence():
    """本文テキストでのアレルゲン言及は補助根拠(confidence=medium)。"""
    profile = _Profile(allergens=["牛乳"])  # milk
    text = "来週のクッキング保育では牛乳を使ったプリンを作ります。"
    result = cm.match_notice(profile, notice_text=text, menu_json=None, use_llm=False)
    milk = [c for c in result["candidates"] if c["canonical"] == "milk" and c["status"] == cm.STATUS_ATTENTION]
    assert milk, "本文中の牛乳が検出されない"
    assert milk[0]["evidence"]["source"] == "notice_text"
    assert milk[0]["evidence"]["confidence"] == cm.CONF_MEDIUM


def test_care_category_in_notice_is_detected():
    """配慮カテゴリ（動物接触）× 本文の決定論一致で要確認候補。"""
    profile = _Profile(care_categories=["動物接触"])  # animal_contact
    text = "9/18に犬とのふれあい体験を予定しています。"
    result = cm.match_notice(profile, notice_text=text, use_llm=False)
    hits = [c for c in result["candidates"] if c["canonical"] == "animal_contact"]
    assert hits and hits[0]["status"] == cm.STATUS_ATTENTION
    assert hits[0]["kind"] == cm.KIND_CARE_CATEGORY
    assert hits[0]["evidence"]["confidence"] == cm.CONF_HIGH
    _all_have_evidence(result)


# =========================== 陰性（誤検出しない） ================================


def test_no_candidate_when_nothing_matches():
    """関連しない献立/本文では候補を出さない（陰性）。"""
    profile = _Profile(allergens=["そば"], care_categories=["大音量"])
    menu = _menu("2026-09-03", lunch=["カレーライス"], green=["にんじん", "ピーマン"])
    result = cm.match_notice(profile, notice_text="今日は良い天気でした。", menu_json=menu, use_llm=False)
    assert result["candidates"] == []
    assert result["attention_count"] == 0
    assert result["abstain_count"] == 0
    assert result["has_profile_data"] is True


def test_empty_profile_yields_no_candidates_and_no_data_flag():
    """プロファイルに突き合わせ対象が無ければ has_profile_data=False・候補なし。"""
    result = cm.match_notice(_Profile(), notice_text="給食で卵を使います", menu_json=None, use_llm=False)
    assert result["candidates"] == []
    assert result["has_profile_data"] is False


def test_unknown_allergen_term_is_not_matched():
    """辞書に無いアレルゲン表記は正規化されず、突き合わせ対象にならない。"""
    profile = _Profile(allergens=["未知の食材X"])
    menu = _menu("2026-09-04", red=["鶏卵"])
    result = cm.match_notice(profile, menu_json=menu, use_llm=False)
    assert result["candidates"] == []
    assert result["has_profile_data"] is False


# =========================== 棄権（情報不足のため要確認） =========================


def test_abstain_when_food_event_but_no_menu():
    """食に関する予定があるのに献立の原材料情報が無い → 断定せず棄権（要確認）。"""
    profile = _Profile(allergens=["卵", "牛乳"])
    text = "来週は試食会があります。"
    result = cm.match_notice(profile, notice_text=text, menu_json=None, use_llm=False)
    abstains = [c for c in result["candidates"] if c["status"] == cm.STATUS_ABSTAIN]
    assert abstains, "情報不足の棄権が立たない"
    c = abstains[0]
    assert c["kind"] == cm.KIND_ALLERGEN
    assert c["evidence"]["confidence"] == cm.CONF_LOW
    assert "情報不足" in c["message"] and "要確認" in c["message"]
    assert result["abstain_count"] >= 1
    _all_have_evidence(result)


def test_no_abstain_when_menu_present_even_if_food_event():
    """献立情報があるなら（該当が無くても）食予定だけでの棄権は立てない。"""
    profile = _Profile(allergens=["卵"])
    menu = _menu("2026-09-05", lunch=["カレー"], green=["にんじん"])
    result = cm.match_notice(profile, notice_text="試食会があります", menu_json=menu, use_llm=False)
    assert all(c["status"] != cm.STATUS_ABSTAIN for c in result["candidates"])


def test_abstain_for_ambiguous_free_text_concern():
    """自由記述の配慮があり、本文に構造化外の配慮カテゴリ記載 → 曖昧として棄権。"""
    profile = _Profile(free_text="大きな音が苦手です")  # 構造化 care_categories は空
    text = "運動会ではピストルの号砲を鳴らします。"  # loud_noise を含む
    result = cm.match_notice(profile, notice_text=text, use_llm=False)
    abstains = [c for c in result["candidates"] if c["status"] == cm.STATUS_ABSTAIN]
    assert abstains, "自由記述に基づく曖昧棄権が立たない"
    assert abstains[0]["canonical"] == "loud_noise"
    assert "情報不足" in abstains[0]["message"]


def test_structured_category_takes_attention_not_abstain():
    """同じカテゴリが構造化プロファイルにあれば棄権でなく Attention になる。"""
    profile = _Profile(care_categories=["大音量"], free_text="花火が苦手")
    text = "運動会でピストルの号砲があります。"
    result = cm.match_notice(profile, notice_text=text, use_llm=False)
    loud = [c for c in result["candidates"] if c["canonical"] == "loud_noise"]
    assert loud and any(c["status"] == cm.STATUS_ATTENTION for c in loud)
    # 構造化で attention 済みなので、同カテゴリの棄権は重複して立てない。
    assert not any(
        c["canonical"] == "loud_noise" and c["status"] == cm.STATUS_ABSTAIN
        for c in result["candidates"]
    )


# =========================== 根拠の必須性・決定論 ===============================


def test_every_candidate_has_evidence():
    """全候補に根拠3要素が付く（受け入れ条件）。"""
    profile = _Profile(allergens=["卵"], care_categories=["動物接触"])
    menu = _menu("2026-09-06", red=["鶏卵"])
    text = "犬とのふれあい体験と、牛乳を使ったおやつがあります。"
    result = cm.match_notice(profile, notice_text=text, menu_json=menu, use_llm=False)
    _all_have_evidence(result)


def test_deterministic_same_input_same_output():
    """同じ入力に対して常に同じ候補集合（LLM 無効）。"""
    profile = _Profile(allergens=["卵"], care_categories=["動物接触"])
    menu = _menu("2026-09-07", red=["鶏卵"], lunch=["厚焼き玉子"])
    text = "犬とのふれあい体験があります。"
    r1 = cm.match_notice(profile, notice_text=text, menu_json=menu, use_llm=False)
    r2 = cm.match_notice(profile, notice_text=text, menu_json=menu, use_llm=False)
    assert r1 == r2


def test_dict_profile_is_supported():
    """CareProfile オブジェクトでなく dict でも同じく動く。"""
    profile = {"allergens": ["卵"], "care_categories": [], "free_text": None}
    menu = _menu("2026-09-08", red=["鶏卵"])
    result = cm.match_notice(profile, menu_json=menu, use_llm=False)
    assert any(c["canonical"] == "egg" for c in result["candidates"])


# =========================== LLM クロスチェック（best-effort） ====================


def test_llm_stage_skipped_when_unavailable(monkeypatch):
    """AI クライアント利用不可なら LLM は呼ばれず、決定論結果のみ返る。"""
    monkeypatch.setattr(cm.ai_client, "gemini_available", lambda: False)
    called = {"n": 0}

    def _fail(*a, **k):  # 呼ばれてはいけない
        called["n"] += 1
        raise AssertionError("LLM should not be called when unavailable")

    monkeypatch.setattr(cm.ai_client, "get_genai_client", _fail)
    profile = _Profile(allergens=["卵"])
    menu = _menu("2026-09-09", red=["鶏卵"])
    result = cm.match_notice(profile, menu_json=menu, use_llm=True)
    assert any(c["canonical"] == "egg" for c in result["candidates"])
    assert called["n"] == 0


def test_llm_crosscheck_notes_and_extra_abstain_are_merged(monkeypatch):
    """LLM は既存候補へ note を付け、追加の棄権候補を足せる（既存 attention は非破壊）。"""
    def _fake_crosscheck(profile, notice_text, menu_json, candidates):
        candidates[0].setdefault("llm_notes", []).append("文脈上も該当の可能性")
        return [
            cm._make_candidate(
                kind=cm.KIND_ALLERGEN,
                status=cm.STATUS_ABSTAIN,
                canonical=None,
                profile_item={"raw": "(LLM)", "canonical": ""},
                source="llm",
                span="オムレツ",
                confidence=cm.CONF_LOW,
                message="（LLM 文脈確認）オムレツは卵を含む可能性。情報不足のため要確認。",
            )
        ]

    monkeypatch.setattr(cm, "_llm_crosscheck", _fake_crosscheck)
    profile = _Profile(allergens=["卵"])
    menu = _menu("2026-09-10", red=["鶏卵"])
    result = cm.match_notice(profile, menu_json=menu, use_llm=True)

    # 既存 attention は保持され note が付く。
    egg_att = [c for c in result["candidates"] if c["canonical"] == "egg" and c["status"] == cm.STATUS_ATTENTION]
    assert egg_att and egg_att[0].get("llm_notes")
    # LLM 由来の棄権が追加される。
    assert any(c["evidence"]["source"] == "llm" and c["status"] == cm.STATUS_ABSTAIN for c in result["candidates"])


def test_llm_crosscheck_failure_degrades_gracefully(monkeypatch):
    """LLM 段が例外でも決定論結果は保持される（best-effort）。"""
    def _boom(*a, **k):
        raise RuntimeError("llm down")

    monkeypatch.setattr(cm, "_llm_crosscheck", _boom)
    profile = _Profile(allergens=["卵"])
    menu = _menu("2026-09-11", red=["鶏卵"])
    result = cm.match_notice(profile, menu_json=menu, use_llm=True)
    assert any(c["canonical"] == "egg" for c in result["candidates"])


# =========================== 決定論スキャン補助（SOT-2730 追加分） ================


@pytest.mark.parametrize(
    "text,expected",
    [
        ("本日のおやつは厚焼き玉子", ["egg"]),
        ("牛乳と小麦のパン", ["milk", "wheat"]),
        ("果物の盛り合わせ", []),
        ("", []),
    ],
)
def test_scan_allergens(text, expected):
    assert cn.scan_allergens(text) == expected
