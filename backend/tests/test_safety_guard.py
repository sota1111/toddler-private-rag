"""SOT-2736: 断定禁止ガード・責任境界/免責・鮮度警告の単体テスト。

健康・安全に関する「誤った安心」を出力しないための出力ガードと、責任境界の免責文言、
プロファイルの鮮度警告を、DB を介さない純粋関数として検証する。
"""
import datetime

import pytest

from app import safety_guard


# --- 断定禁止ガード ---------------------------------------------------------

BANNED_SAMPLES = [
    "このメニューは安全です。",
    "お子さんが食べても大丈夫です。",
    "食べられます。",
    "アレルギーの心配はありません。",
    "アレルゲンは含まれていません。",
    "問題ありません。",
    "特に心配いりません。",
    "食べても問題ないです。",
]


@pytest.mark.parametrize("text", BANNED_SAMPLES)
def test_guard_neutralizes_safety_assertions(text):
    guarded = safety_guard.apply_output_guard(text)
    # 中和後は元の断定表現を検知しない（安全側の断定も等しく禁止）。
    assert not safety_guard.contains_banned_assertion(guarded), guarded
    # 許容表現へ言い換えられている。
    assert "要確認" in guarded


def test_guard_detects_banned_before_neutralization():
    assert safety_guard.contains_banned_assertion("これは安全です")
    assert safety_guard.contains_banned_assertion("食べられます")


def test_guard_preserves_risk_side_statements():
    # 危険側（該当する可能性がある等）の指摘は弱めない。
    text = "卵アレルゲンに該当する可能性があります。要確認。"
    guarded = safety_guard.apply_output_guard(text)
    assert "該当する可能性があります" in guarded
    assert "要確認" in guarded


def test_guard_is_idempotent():
    once = safety_guard.apply_output_guard("これは安全です。食べられます。")
    twice = safety_guard.apply_output_guard(once)
    assert once == twice
    assert not safety_guard.contains_banned_assertion(twice)


def test_guard_handles_empty_and_none():
    assert safety_guard.apply_output_guard("") == ""
    assert safety_guard.apply_output_guard(None) == ""


def test_guard_neutralizes_mixed_sentence():
    text = "遠足のおやつについては、この商品は安全ですので食べても大丈夫です。"
    guarded = safety_guard.apply_output_guard(text)
    assert not safety_guard.contains_banned_assertion(guarded)
    # 元の非断定部分（遠足のおやつ）は残る。
    assert "遠足のおやつ" in guarded


# --- 責任境界・免責 ---------------------------------------------------------

def test_disclaimer_states_responsibility_boundary():
    d = safety_guard.RESPONSIBILITY_DISCLAIMER
    assert "保護者" in d           # 最終判断=保護者
    assert ("医療" in d or "園" in d)  # 専門判断=医療者・園
    # 免責文言自体は安全断定を含まない。
    assert not safety_guard.contains_banned_assertion(d)


# --- 鮮度警告 ---------------------------------------------------------------

def test_freshness_warning_none_when_fresh():
    now = datetime.datetime(2026, 8, 20, 12, 0, 0)
    updated = now - datetime.timedelta(days=10)
    assert safety_guard.profile_freshness_warning(updated, now=now) is None


def test_freshness_warning_when_stale():
    now = datetime.datetime(2026, 8, 20, 12, 0, 0)
    updated = now - datetime.timedelta(days=safety_guard.STALE_THRESHOLD_DAYS + 5)
    warning = safety_guard.profile_freshness_warning(updated, now=now)
    assert warning is not None
    assert "古く" in warning or "古い" in warning


def test_freshness_warning_boundary_not_stale_at_threshold():
    now = datetime.datetime(2026, 8, 20, 12, 0, 0)
    updated = now - datetime.timedelta(days=safety_guard.STALE_THRESHOLD_DAYS)
    assert safety_guard.profile_freshness_warning(updated, now=now) is None


def test_freshness_warning_none_when_updated_at_missing():
    assert safety_guard.profile_freshness_warning(None) is None


def test_freshness_warning_handles_tz_aware_and_naive_mix():
    jst = datetime.timezone(datetime.timedelta(hours=9))
    now = datetime.datetime(2026, 8, 20, 12, 0, 0, tzinfo=jst)
    updated = datetime.datetime(2026, 1, 1, 0, 0, 0)  # naive, > threshold days ago
    # クラッシュせずに警告を返す。
    warning = safety_guard.profile_freshness_warning(updated, now=now)
    assert warning is not None
