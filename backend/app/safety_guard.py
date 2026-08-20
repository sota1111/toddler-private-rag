"""SOT-2736: 健康・安全に関する断定禁止ガードと責任境界・鮮度/相反情報の安全UX。

このモジュールは、健康・医療・アレルギー情報を扱う出力に「誤った安心」を与えないための
横断的な安全レイヤを一箇所に集約する。役割は3つ:

1. **断定禁止ガード** (:func:`apply_output_guard`)
   LLM 回答等の出力から「安全」「食べられる」「問題ない」「アレルギーはありません」等の
   *安全を保証する断定* を取り除き、「確認が必要な可能性があります（要確認）」へ中和する。
   リスク非対称（見落とし>誤検出／recall 優先）を守るため、**安全側の断定も等しく禁止**する。
   ガードは常に「断定→要確認」方向にのみ作用し、危険側の指摘を弱めることはない。

2. **責任境界・免責** (:data:`RESPONSIBILITY_DISCLAIMER`)
   サービス=発見・想起の支援 / 最終判断=保護者 / 専門判断=医療者・園 という責任境界を
   単一の文言として定義し、UI と API の双方が同じ文言を参照できるようにする。

3. **古い情報の警告** (:func:`profile_freshness_warning`)
   個別配慮プロファイルの最終更新から一定期間を超えたら「情報が古い可能性・見直しを」提示する。

既存の照合エンジン (SOT-2733 ``care_matching`` / SOT-2734 ``care_attention``) は *生成側* で
既に断定を避けているが、本モジュールは LLM 自由生成など経路を問わず効く *防御的な出力ガード* を
担う。二重に安全側へ倒すことで、経路追加時の取りこぼしを防ぐ。
"""

from __future__ import annotations

import datetime
import re
from typing import List, Optional, Pattern, Tuple

__all__ = [
    "RESPONSIBILITY_DISCLAIMER",
    "STALE_THRESHOLD_DAYS",
    "HEDGE_PHRASE",
    "apply_output_guard",
    "contains_banned_assertion",
    "profile_freshness_warning",
]

# 責任境界・免責の唯一の文言（UI/API 共通で参照する）。
RESPONSIBILITY_DISCLAIMER = (
    "このサービスは、園からのお便り等の情報の発見・想起を支援するものです。"
    "健康・アレルギー・安全に関する最終的な判断は保護者ご自身が、"
    "専門的な判断は医療者・園にご確認ください。表示内容は必ず原本・専門家でご確認ください。"
)

# プロファイルが「古い可能性あり」と判定する既定しきい値（日数）。
STALE_THRESHOLD_DAYS = 180

# 断定を中和したあとに残す許容表現（唯一の言い換え先）。
HEDGE_PHRASE = "確認が必要な可能性があります（要確認）"

# 断定禁止パターン。より具体的（長い）ものを先に置き、部分一致で語尾だけ残さないようにする。
# いずれも「安全を保証する断定」を丸ごと拾い、:data:`HEDGE_PHRASE` へ置換する。
_BANNED_PATTERNS: List[Pattern[str]] = [
    # 「食べても大丈夫／食べても問題ない／食べられます」等の可食断定。
    re.compile(
        r"食べ(?:ても(?:大丈夫|問題(?:は)?(?:ない|ありません)|平気|よい|良い|オーケー|OK)"
        r"|られます|られる|て(?:も)?安全(?:です)?)"
    ),
    # アレルゲン/アレルギーの不在断定（安全側の断定＝false reassurance）。
    re.compile(
        r"(?:アレルゲン|アレルギー(?:反応|物質)?)(?:は|も)?"
        r"(?:含まれていません|含まれない|ありません|ない(?:です)?|心配(?:は)?(?:ありません|ない|不要(?:です)?))"
    ),
    # 「安全です／安全だ」等の安全断定。断定の述語を必須にし、「安全に関する」等の
    # 中立語（安全対策・安全性の確認 等）を過剰に中和しないようにする。
    re.compile(r"(?:食べても)?安全(?:です|だ|である|でしょう|と言えます|と思われます|といえます)"),
    # 「問題ありません／問題ない」。
    re.compile(r"問題(?:は)?(?:ありません|ない(?:です)?|なさそうです)"),
    # 「心配ありません／心配いりません／心配無用」。
    re.compile(r"心配(?:は)?(?:ありません|いりません|ない(?:です)?|無用(?:です)?|不要(?:です)?)"),
    # 「大丈夫です／大丈夫だ」。述語必須（「大丈夫か確認」等を壊さない）。
    re.compile(r"大丈夫(?:です|だ|でしょう|かと思います)"),
]


def contains_banned_assertion(text: Optional[str]) -> bool:
    """``text`` に安全を保証する断定表現が含まれるかを返す（テスト/診断用）。"""
    if not text:
        return False
    return any(p.search(text) for p in _BANNED_PATTERNS)


def _collapse_repeats(text: str) -> str:
    """置換で連続してしまった同一ヘッジや二重句点を1つに畳む。"""
    # 「要確認）要確認）」のような連続を1つに。
    pattern = re.escape(HEDGE_PHRASE)
    text = re.sub(rf"(?:{pattern})(?:\s*(?:、|。)?\s*(?:{pattern}))+", HEDGE_PHRASE, text)
    # 二重句点を正規化。
    text = re.sub(r"。\s*。+", "。", text)
    return text


def apply_output_guard(text: Optional[str]) -> str:
    """出力から安全断定を取り除き ``HEDGE_PHRASE`` へ中和した文字列を返す。

    - 危険側（該当する可能性がある等）の記述は一切弱めない。安全断定のみを中和する。
    - 冪等: 既に中和済みの文字列を渡しても結果は変わらない。
    - ``None``/空文字はそのまま空文字を返す。
    """
    if not text:
        return text or ""
    guarded = text
    for pattern in _BANNED_PATTERNS:
        guarded = pattern.sub(HEDGE_PHRASE, guarded)
    return _collapse_repeats(guarded)


def _as_naive_utc(dt: datetime.datetime) -> datetime.datetime:
    """比較のため tz-aware を UTC naive に、naive はそのまま返す。"""
    if dt.tzinfo is not None:
        return dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return dt


def profile_freshness_warning(
    updated_at: Optional[datetime.datetime],
    *,
    now: Optional[datetime.datetime] = None,
    threshold_days: int = STALE_THRESHOLD_DAYS,
) -> Optional[str]:
    """個別配慮プロファイルが古い可能性があれば警告文を、無ければ ``None`` を返す。

    - ``updated_at`` が ``None``（判定不能）なら ``None``。
    - 経過日数が ``threshold_days`` を超えたときのみ警告する（境界含めては警告しない）。
    - tz-aware/naive が混在してもクラッシュしないよう UTC naive に正規化して比較する。
    """
    if updated_at is None:
        return None
    if now is None:
        from . import clock

        now = clock.now_jst()
    base = _as_naive_utc(now)
    updated = _as_naive_utc(updated_at)
    elapsed_days = (base - updated).days
    if elapsed_days <= threshold_days:
        return None
    return (
        f"この個別配慮情報は最終更新から約{elapsed_days}日が経過しています。"
        "内容が古くなっている可能性があるため、最新の状態か見直し・確認をおすすめします。"
    )
