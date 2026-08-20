"""個別配慮照合 (care-matching) eval-gate (SOT-2735).

プロダクトの中核価値 —「この子に関係する要確認をちゃんと拾い（発見率）、無関係でうるさく
せず（無関係抑制）、根拠を必ず添え（根拠正当性）、決して断定・安全宣言をしない（安全棄権/
断定ゼロ）」— を、SOT-2733 の照合エンジン ``app.care_matching.match_notice`` に対する
**閾値ゲート**として回帰計測する。既存 OCR/RAG/Agent の eval-gate と同じ枠組みで、閾値割れ
→ CI（``evaluation-gate`` ジョブ）失敗 → 本番デプロイもブロック（SOT-1469 A1）に統合する。

golden（``CARE_MATCHING_EVAL_CASES``）は Expected Experience 型の5類型
（献立×アレルゲン / 行事×配慮 / 無関係文書 / 情報不足文書 / 相反情報）を網羅する。

計測する5指標とゲート:

    発見率(Attention Recall)   ≥ 0.90   期待される要確認のうち attention として検出できた割合
    誤警告(Precision)          ≥ 0.70   出した attention のうち期待どおりだった割合（過検出の逆）
    根拠正当性(Evidence)       = 1.00 必須  全候補が根拠3要素（該当箇所/対応項目/信頼度）を持つ
    安全棄権(断定ゼロ)          = 0 件 必須  定型「要確認」以外の断定・安全宣言を1件も出さない
    無関係抑制(Suppression)     ≥ 0.90   出してはいけない項目を attention に出さなかった割合

加えて **情報不足文書では黙って通さず棄権（abstain）を明示** することを必須ゲートにする。

決定論のみ（``use_llm=False``）で評価するため、CI ではネットワーク不要・オフライン安定
（同入力 → 同出力）。LLM クロスチェックは best-effort の付加であり、この下限品質は決定論
辞書層だけで満たすことを保証する。
"""

import pytest

from app import care_matching as cm
from tests.eval.dataset import CARE_MATCHING_EVAL_CASES

# --- Thresholds (閾値割れ→CI失敗→本番デプロイもブロック) -----------------------------
MIN_ATTENTION_RECALL = 0.90     # 発見率: 拾うべき要確認を取りこぼさない
MIN_PRECISION = 0.70            # 誤警告の逆: 過検出を抑える
MIN_IRRELEVANT_SUPPRESSION = 0.90  # 無関係抑制: 関係ない項目でうるさくしない
REQUIRED_EVIDENCE_VALIDITY = 1.0   # 根拠正当性: 全候補が根拠3要素を持つ（必須）
# 断定ゼロ: 定型「要確認」以外の断定・安全宣言は 0 件（必須）。

# 断定・安全宣言と見なす語（候補メッセージに現れてはならない）。照合エンジンは人間の確認へ
# 導く「要確認」だけを出す契約なので、これらの語は安全側原則の逸脱（＝断定）を意味する。
FORBIDDEN_ASSERTIONS = (
    "問題ありません", "問題はありません", "問題ない",
    "安全です", "安心してください", "心配ありません", "心配いりません",
    "食べられます", "食べても大丈夫", "大丈夫です",
    "該当しません", "含まれていません", "アレルギーはありません",
)
# 非断定であることの積極マーカー（各候補メッセージに必ず含める）。
ATTENTION_MARKER = "要確認"

# アーカイブ的な安定キー参照（可読性のため）。
ATTENTION = cm.STATUS_ATTENTION
ABSTAIN = cm.STATUS_ABSTAIN


def _run(case: dict) -> dict:
    """1 golden ケースを決定論のみ（LLM 無効）で照合エンジンに通す。"""
    return cm.match_notice(
        case["profile"],
        notice_text=case.get("notice_text"),
        menu_json=case.get("menu_json"),
        use_llm=False,
    )


def _attention_keys(result: dict) -> set:
    """result から status=attention の (kind, canonical) 集合を作る。"""
    return {
        (c["kind"], c["canonical"])
        for c in result["candidates"]
        if c["status"] == ATTENTION and c["canonical"] is not None
    }


def _candidate_texts(candidate: dict):
    """候補が人間に見せる全テキスト（message + LLM 注記）を列挙する。"""
    yield candidate.get("message", "")
    for note in candidate.get("llm_notes", []) or []:
        yield note


def _is_assertive(candidate: dict) -> bool:
    """候補が「断定・安全宣言」に該当するか（要確認マーカー欠落 or 禁止語を含む）。"""
    texts = list(_candidate_texts(candidate))
    if not any(ATTENTION_MARKER in t for t in texts):
        return True
    return any(phrase in t for phrase in FORBIDDEN_ASSERTIONS for t in texts)


def _evidence_valid(candidate: dict) -> bool:
    """候補が根拠3要素（該当箇所/対応プロファイル項目/信頼度）＋出所を備えるか。"""
    ev = candidate.get("evidence") or {}
    return bool(
        ev.get("span")
        and ev.get("profile_item")
        and ev.get("confidence") in (cm.CONF_HIGH, cm.CONF_MEDIUM, cm.CONF_LOW)
        and ev.get("source") in ("menu_json", "notice_text", "llm")
    )


# =========================== 前提: golden の健全性 ===============================


def test_golden_dataset_covers_all_archetypes():
    """Expected Experience 型5類型がすべて golden に含まれている。"""
    archetypes = {c["archetype"] for c in CARE_MATCHING_EVAL_CASES}
    assert archetypes == {
        "menu_allergen", "event_care", "irrelevant", "info_insufficient", "conflict",
    }, f"golden archetypes incomplete: {archetypes}"


# =========================== 根拠正当性（=1.0 必須） =============================


@pytest.mark.parametrize("case", CARE_MATCHING_EVAL_CASES, ids=lambda c: c["id"])
def test_every_candidate_has_valid_evidence(case):
    """全候補が根拠3要素を必ず持つ（根拠正当性は必須ゲート = 1.0）。"""
    result = _run(case)
    for c in result["candidates"]:
        assert _evidence_valid(c), f"{case['id']}: 根拠不備の候補: {c}"


# =========================== 安全棄権（断定ゼロ 必須） ==========================


@pytest.mark.parametrize("case", CARE_MATCHING_EVAL_CASES, ids=lambda c: c["id"])
def test_no_candidate_makes_an_assertion(case):
    """どの候補も断定・安全宣言をせず「要確認」に留める（断定ゼロは必須ゲート）。"""
    result = _run(case)
    offenders = [c for c in result["candidates"] if _is_assertive(c)]
    assert not offenders, f"{case['id']}: 断定的な候補が出た: {offenders}"


@pytest.mark.parametrize(
    "case",
    [c for c in CARE_MATCHING_EVAL_CASES if c.get("expect_abstain")],
    ids=lambda c: c["id"],
)
def test_info_insufficient_documents_abstain(case):
    """情報不足文書は黙って通さず、棄権（情報不足のため要確認）を明示する。"""
    result = _run(case)
    abstains = [c for c in result["candidates"] if c["status"] == ABSTAIN]
    assert abstains, f"{case['id']}: 情報不足なのに棄権(abstain)が出ていない"
    # 棄権であっても attention 相当の断定はしない（過検出で断定に化けない）。
    assert _attention_keys(result) == set(), (
        f"{case['id']}: 情報不足文書で attention を断定してしまった"
    )


# =========================== 集約ゲート（5指標） ================================


def test_care_matching_eval_scores():
    """全 golden 集約の 発見率/誤警告/根拠正当性/断定ゼロ/無関係抑制 を下限ゲート。"""
    recall_total = recall_hit = 0
    precision_total = precision_hit = 0
    suppress_total = suppress_hit = 0
    evidence_total = evidence_valid = 0
    assertive_count = 0
    abstain_expected = abstain_got = 0

    for case in CARE_MATCHING_EVAL_CASES:
        result = _run(case)
        attention_keys = _attention_keys(result)

        # 発見率(Recall): 期待 attention を取りこぼさない。
        for expected in case.get("expected_attention", []):
            recall_total += 1
            if tuple(expected) in attention_keys:
                recall_hit += 1

        # 誤警告(Precision): 出した attention のうち期待どおりの割合。
        expected_set = {tuple(e) for e in case.get("expected_attention", [])}
        for c in result["candidates"]:
            if c["status"] != ATTENTION or c["canonical"] is None:
                continue
            precision_total += 1
            if (c["kind"], c["canonical"]) in expected_set:
                precision_hit += 1

        # 無関係抑制: 出してはいけない項目を attention に出さなかった割合。
        for suppressed in case.get("expected_suppressed", []):
            suppress_total += 1
            if tuple(suppressed) not in attention_keys:
                suppress_hit += 1

        # 根拠正当性 / 断定ゼロ。
        for c in result["candidates"]:
            evidence_total += 1
            if _evidence_valid(c):
                evidence_valid += 1
            if _is_assertive(c):
                assertive_count += 1

        # 安全棄権（情報不足→棄権）。
        if case.get("expect_abstain"):
            abstain_expected += 1
            if any(c["status"] == ABSTAIN for c in result["candidates"]):
                abstain_got += 1

    recall = recall_hit / recall_total if recall_total else 1.0
    precision = precision_hit / precision_total if precision_total else 1.0
    suppression = suppress_hit / suppress_total if suppress_total else 1.0
    evidence_validity = evidence_valid / evidence_total if evidence_total else 1.0

    print("\n=== care-matching eval-gate (SOT-2735) ===")
    print(f"発見率  Attention Recall : {recall:.2f} ({recall_hit}/{recall_total})")
    print(f"誤警告  Precision        : {precision:.2f} ({precision_hit}/{precision_total})")
    print(f"根拠正当性 Evidence      : {evidence_validity:.2f} ({evidence_valid}/{evidence_total})")
    print(f"断定ゼロ Assertions      : {assertive_count} (must be 0)")
    print(f"無関係抑制 Suppression   : {suppression:.2f} ({suppress_hit}/{suppress_total})")
    print(f"安全棄権 Abstain         : {abstain_got}/{abstain_expected}")

    # 分母が痩せて指標が形骸化しないことを保証（golden の最低ボリューム）。
    assert recall_total >= 8, "発見率の golden 陽性が少なすぎる"
    assert suppress_total >= 4, "無関係抑制の golden 分母が少なすぎる"
    assert evidence_total >= 8, "候補総数が少なすぎる（根拠正当性が形骸化）"

    assert recall >= MIN_ATTENTION_RECALL, f"発見率 {recall:.2f} < {MIN_ATTENTION_RECALL}"
    assert precision >= MIN_PRECISION, f"Precision {precision:.2f} < {MIN_PRECISION}"
    assert evidence_validity >= REQUIRED_EVIDENCE_VALIDITY, (
        f"根拠正当性 {evidence_validity:.2f} < {REQUIRED_EVIDENCE_VALIDITY}（必須）"
    )
    assert assertive_count == 0, f"断定ゼロ違反: 断定的候補が {assertive_count} 件（必須0）"
    assert suppression >= MIN_IRRELEVANT_SUPPRESSION, (
        f"無関係抑制 {suppression:.2f} < {MIN_IRRELEVANT_SUPPRESSION}"
    )
    assert abstain_got == abstain_expected, (
        f"安全棄権: 情報不足文書 {abstain_expected} 件中 {abstain_got} 件しか棄権していない"
    )
