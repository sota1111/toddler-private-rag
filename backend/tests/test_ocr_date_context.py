"""OCR日付誤読の発行月コンテキスト補正のテスト (SOT-1567)。

提案1(整合チェック) / 提案3(混同文字マップ) / 提案4(M/D取りこぼし) の純粋関数と、
発行月コンテキストでの締切補正(提案1+2 の決定的経路)を検証する。テスト環境では Gemini 非利用
なので提案2の LLM 経路は決定的に「原文維持」になる（never-throw / graceful-fallback）。
"""

import datetime

from app import extraction, submission_agent


# --- 提案4: M/D(年なしスラッシュ)取りこぼし ---------------------------------------


def test_normalize_date_md_uses_current_year_by_default():
    iso = extraction.normalize_date("7/31")
    assert iso is not None
    assert iso.endswith("-07-31")
    assert iso.startswith(str(extraction.clock.today().year))


def test_normalize_date_md_uses_reference_year():
    assert extraction.normalize_date("7/31", reference_year=2026) == "2026-07-31"


def test_normalize_date_md_invalid_is_none():
    assert extraction.normalize_date("13/40", reference_year=2026) is None


def test_normalize_date_existing_formats_still_work():
    assert extraction.normalize_date("2026/07/31") == "2026-07-31"
    assert extraction.normalize_date("7月31日", reference_year=2026) == "2026-07-31"
    assert extraction.normalize_date("2026-07-31") == "2026-07-31"


def test_detect_deadline_iso_picks_up_md():
    # 年なし M/D が締切候補として拾えること（発行年で補完）。
    text = "提出は 7/31 までにお願いします。"
    iso = submission_agent._detect_deadline_iso(
        text, datetime.date(2026, 7, 1)
    )
    assert iso == "2026-07-31"


def test_build_extraction_detects_md():
    from app import ocr

    doc = ocr.build_extraction("しめきりは 7/31 です")
    assert "7/31" in doc.detected_dates


def test_build_extraction_md_does_not_double_capture_full_date():
    from app import ocr

    doc = ocr.build_extraction("2026/7/31 が締切です")
    # フル日付 YYYY/M/D を M/D として二重に拾わない。
    assert "2026/7/31" in doc.detected_dates
    assert "26/7" not in doc.detected_dates


# --- 提案3: 日付フィールド限定の混同文字マップ ------------------------------------


def test_normalize_date_field_confusions_maps_lookalikes():
    # O/〇→0, l/｜→1, Z→2, B→8, 全角→半角, 全角スラッシュ→半角
    assert extraction.normalize_date_field_confusions("7／3l") == "7/31"
    assert extraction.normalize_date_field_confusions("２０２６/７/３１") == "2026/7/31"
    assert extraction.normalize_date_field_confusions("Z月") == "2月"


def test_normalize_date_field_confusions_preserves_kanji_separators():
    assert extraction.normalize_date_field_confusions("7月31日") == "7月31日"


def test_confusion_then_normalize_recovers_date():
    fixed = extraction.normalize_date_field_confusions("７／3l")
    assert extraction.normalize_date(fixed, reference_year=2026) == "2026-07-31"


# --- 提案1: 発行月コンテキストの整合チェック --------------------------------------


def test_consistency_flags_past_deadline_with_suggestion():
    # 発行=7月, OCR「1/31」→ 過去締切として検出され、7↔1 の決定的補正候補(7/31)を提示。
    deadline = extraction.normalize_date("1/31", reference_year=2026)
    finding = extraction.check_deadline_consistency(
        deadline, datetime.date(2026, 7, 5)
    )
    assert finding.suspicious is True
    assert finding.suggestion == "2026-07-31"


def test_consistency_normal_deadline_not_flagged():
    # 発行月内〜近未来の締切は素通し（誤補正しない）。
    finding = extraction.check_deadline_consistency(
        "2026-07-31", datetime.date(2026, 7, 5)
    )
    assert finding.suspicious is False
    assert finding.suggestion is None


def test_consistency_large_month_gap_flagged_without_suggestion():
    # 締切月と発行月の差が大きすぎる（未来方向）→ 疑わしいが決定的候補は無い。
    finding = extraction.check_deadline_consistency(
        "2027-03-31", datetime.date(2026, 7, 5)
    )
    assert finding.suspicious is True
    assert finding.suggestion is None


def test_consistency_missing_context_is_not_suspicious():
    assert extraction.check_deadline_consistency(None, datetime.date(2026, 7, 5)).suspicious is False
    assert extraction.check_deadline_consistency("2026-07-31", None).suspicious is False
    assert extraction.check_deadline_consistency("not-a-date", datetime.date(2026, 7, 5)).suspicious is False


def test_suggestion_only_for_single_digit_confusion_pairs():
    # 12月↔2月 は桁数違い＝字形混同でないので決定的候補は出さない（憶測しない）。
    finding = extraction.check_deadline_consistency(
        "2026-02-28", datetime.date(2026, 12, 1)
    )
    assert finding.suspicious is True  # 過去締切ではある
    assert finding.suggestion is None


# --- 提案1+2 統合: 発行月コンテキストでの締切補正（決定的経路） -----------------------


def test_reconcile_corrects_july_notice_misread_as_january():
    # シナリオ: 発行=7月・本文の締切が「1/31」に化けている → 補正候補 7/31 を採用。
    text = "7月号のおたより。提出締切は 1/31 です。"
    iso = submission_agent._detect_deadline_iso(text, datetime.date(2026, 7, 5))
    assert iso == "2026-07-31"


def test_reconcile_keeps_normal_deadline():
    text = "提出締切は 7/31 です。"
    iso = submission_agent._detect_deadline_iso(text, datetime.date(2026, 7, 5))
    assert iso == "2026-07-31"


def test_reconcile_without_issue_date_is_unchanged():
    # 発行日が無ければ従来どおり（補正しない）。
    text = "提出締切は 1/31 です。"
    iso = submission_agent._detect_deadline_iso(text)
    assert iso.endswith("-01-31")


def test_llm_correction_returns_empty_offline():
    # Gemini 非利用時は LLM 補正は原文維持（never-throw）。
    assert submission_agent._llm_correct_deadline(
        "本文", "2026-01-31", datetime.date(2026, 7, 5)
    ) == ""
