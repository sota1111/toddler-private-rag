"""Agent E2E Regression gate (SOT-1568).

作品の主要価値であるエージェント本体 —「おたより文 → 公式手順の調査 → 締切逆算 →
日付付き準備タスク（やること）生成」— の**一気通貫の品質**を eval-gate として回帰計測する。

これまでエージェントのロジックは ``test_submission_agent.py`` のユニットテストで厚く
覆われていたが、**eval-gate 指標（閾値割れ→CI失敗→本番デプロイもブロック）としては未計測**
だった。本スイートは同一の一気通貫パイプライン
``extract_submission_documents -> build_submission_task_drafts`` を golden な
``AGENT_EVAL_CASES`` に通し、次の4品質を下限ゲート（初期 0.8）で回帰から守る:

    ① Agent E2E Regression — 一気通貫の名前付き必須チェックとして成立している。
    ② タスク生成           — 期待「やること」の coverage / precision（過検出ゼロ）。
    ③ 締切逆算             — 逆算日付の一致率（許容誤差 0 日。README 実例 7/30→7/9 を golden 化）。
    ⑤ 曖昧情報への対応     — 締切不明で日付を捏造しない / 手続き名のみで推定(要確認)導線 / 一般文で過検出しない。

外部 LLM（書類抽出）と Google Search grounding の2境界だけを**決定論的にスタブ**するため、
CI で安定（ネットワーク不要・オフライン）。スタブの下流にある逆算・辞書推論・過検出抑制などの
**実ロジックは本物**を検証している。
"""

import datetime
import json

import pytest

from app import submission_agent, ai_client
from tests.eval.dataset import AGENT_EVAL_CASES

# --- Thresholds (閾値割れ→CI失敗→本番デプロイもブロック) -----------------------------
# 既存 OCR/RAG ゲートと同方針で初期 0.8。実測に合わせて上方ラチェットする。
MIN_TASK_COVERAGE = 0.8       # ② 期待やることのうちタスク化された割合
MIN_TASK_PRECISION = 0.8      # ② 生成タスクのうち期待書類に対応する割合（過検出の逆数）
MIN_DEADLINE_MATCH_RATE = 0.8  # ③ 逆算日付の一致率（許容誤差 0 日）

# 推定（辞書/LLM推論）由来の書類に必ず出る「要確認」導線マーカー（_inferred_notice_line）。
INFERRED_NOTICE_MARKER = "推定（要確認）"
# 最終提出期限を本文へ書く行の接頭辞（締切不明時に捏造していないことの検証に使う）。
FINAL_DEADLINE_MARKER = "最終提出期限"


def _run_agent(case: dict, monkeypatch) -> list:
    """1 golden ケースを実エージェントに通し、生成された準備タスク draft を返す。

    LLM 抽出と grounding の2境界のみ決定論的にスタブする。``llm_docs`` が None の
    ケースは、LLM が何も返さない状況で **実辞書推論**（手続き名→標準書類）を通す。
    """
    monkeypatch.setattr(ai_client, "gemini_available", lambda: True)

    llm_docs = case.get("llm_docs")
    stub_docs = [] if llm_docs is None else list(llm_docs)
    monkeypatch.setattr(
        submission_agent,
        "_llm_extract_documents",
        lambda text, language, _docs=stub_docs: [dict(d) for d in _docs],
    )

    enrich_json = json.dumps(case["enrich"])
    monkeypatch.setattr(
        ai_client,
        "generate_grounded_with_sources",
        lambda prompt, **k: (enrich_json, []),
    )

    today = case.get("today")
    if today:
        fixed = datetime.date.fromisoformat(today)
        monkeypatch.setattr(submission_agent, "_today", lambda: fixed)

    return submission_agent.build_submission_task_drafts(
        case["letter"], language="ja", final_due_iso=case.get("final_due_iso")
    )


def _matches_doc(title: str, doc_names) -> bool:
    return any(name in title for name in doc_names)


# --- ① Agent E2E Regression + ⑤ 曖昧対応（ケース別の構造検証） ------------------------

@pytest.mark.parametrize("case", AGENT_EVAL_CASES, ids=lambda c: c["id"])
def test_agent_e2e_case(case, monkeypatch):
    """一気通貫でパイプラインが破綻せず、各ケースの安全性/曖昧対応要件を満たす。"""
    drafts = _run_agent(case, monkeypatch)

    # ⑤(c) 一般文 → 書類を湧かせない（過検出ゼロ）。
    if case.get("expect_empty"):
        assert drafts == [], f"{case['id']}: expected no tasks, got {len(drafts)}"
        return

    assert drafts, f"{case['id']}: expected generated tasks, got none"

    # すべての draft は提出物タスクの体裁（一気通貫が正しく走った証跡）。
    for d in drafts:
        assert d["info_type"] == "提出物"
        assert d["tags"] == submission_agent.SUBMISSION_TAG
        assert d["title"]

    # ② coverage: 期待やることがすべてタスク化されている。
    for name in case.get("expected_task_docs", []):
        assert any(_matches_doc(d["title"], [name]) for d in drafts), (
            f"{case['id']}: expected task for '{name}' not generated"
        )

    # ② precision: 禁止書類（過検出）が出ていない。
    for name in case.get("forbidden_task_docs", []):
        assert not any(_matches_doc(d["title"], [name]) for d in drafts), (
            f"{case['id']}: over-detected forbidden doc '{name}'"
        )

    # ③ 逆算: 指定があれば締切が完全一致（許容誤差 0 日）。
    expected_dates = case.get("expected_due_dates") or []
    if expected_dates:
        actual = [d["due_date"] for d in drafts]
        assert actual == expected_dates, (
            f"{case['id']}: deadline back-calc mismatch: {actual} != {expected_dates}"
        )
        for d in drafts:
            assert d["event_date"] == d["due_date"]

    # ⑤(b) 手続き名のみ → 推定書類に「推定（要確認）」導線が出る。
    if case.get("expect_inferred_notice"):
        assert any(d.get("inferred") for d in drafts), (
            f"{case['id']}: expected an inferred(要確認) task"
        )
        assert any(INFERRED_NOTICE_MARKER in d["content"] for d in drafts), (
            f"{case['id']}: inferred task missing the 要確認 notice line"
        )

    # ⑤(a) 締切不明 → 具体的な締切日を捏造せず前向きフォールバック。
    # SOT-1598: 期限が不明であること自体は「不明」と本文に明記する（明記は捏造ではない）。
    if case.get("expect_no_fabricated_deadline"):
        for d in drafts:
            content = d["content"]
            # 最終提出期限の具体日付を捏造していない。「最終提出期限: 不明（…）」は許容する。
            for line in content.splitlines():
                if FINAL_DEADLINE_MARKER in line:
                    assert "不明" in line, (
                        f"{case['id']}: fabricated a final deadline for a letter with no due date"
                    )
            # SOT-1598: 締切が不明なことが本文に明記されている。
            assert "不明" in content, (
                f"{case['id']}: missing the '締切不明' note for a letter with no due date"
            )
            # それでも本日起点の前向き締切は付く（やることが日付付きで登録される）。
            assert d["event_date"], f"{case['id']}: forward-fallback produced no date"


# --- ② タスク生成 coverage / precision（集約ゲート） --------------------------------

def test_agent_task_generation_scores(monkeypatch):
    """全ケース集約の coverage / precision を下限ゲート。"""
    expected_total = 0
    covered = 0
    drafts_total = 0
    drafts_matched = 0

    for case in AGENT_EVAL_CASES:
        drafts = _run_agent(case, monkeypatch)
        expected_names = case.get("expected_task_docs", [])

        for name in expected_names:
            expected_total += 1
            if any(_matches_doc(d["title"], [name]) for d in drafts):
                covered += 1

        for d in drafts:
            drafts_total += 1
            if expected_names and _matches_doc(d["title"], expected_names):
                drafts_matched += 1

    coverage = covered / expected_total if expected_total else 1.0
    precision = drafts_matched / drafts_total if drafts_total else 1.0

    print(f"\nTask Coverage: {coverage:.2f} ({covered}/{expected_total})")
    print(f"Task Precision: {precision:.2f} ({drafts_matched}/{drafts_total})")

    assert coverage >= MIN_TASK_COVERAGE
    assert precision >= MIN_TASK_PRECISION


# --- ③ 締切逆算 一致率（集約ゲート） ------------------------------------------------

def test_agent_deadline_backcalc_match_rate(monkeypatch):
    """逆算日付の一致率（許容誤差 0 日）を下限ゲート。"""
    total = 0
    matched = 0

    for case in AGENT_EVAL_CASES:
        expected_dates = case.get("expected_due_dates") or []
        if not expected_dates:
            continue
        drafts = _run_agent(case, monkeypatch)
        actual = [d["due_date"] for d in drafts]
        for i, exp in enumerate(expected_dates):
            total += 1
            if i < len(actual) and actual[i] == exp:
                matched += 1

    match_rate = matched / total if total else 1.0
    print(f"\nDeadline Back-calc Match Rate: {match_rate:.2f} ({matched}/{total})")
    assert total > 0, "expected at least one deadline back-calc golden case"
    assert match_rate >= MIN_DEADLINE_MATCH_RATE
