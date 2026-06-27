"""SOT-1297: clock ヘルパが「今日」を JST(Asia/Tokyo) 基準で返すことを検証する。

本番 Cloud Run はコンテナ時刻が UTC のため、素の ``date.today()`` だと JST 00:00〜09:00 の
間に1日ズレる。``clock.today()`` がその境界でも JST 日付を返すことを確認する。
"""

import datetime
import types

from app import clock


def test_now_jst_is_tz_aware_and_jst_offset():
    now = clock.now_jst()
    assert now.tzinfo is not None
    # 既定タイムゾーンは Asia/Tokyo = UTC+9
    assert now.utcoffset() == datetime.timedelta(hours=9)


def test_today_matches_now_jst_date():
    assert clock.today() == clock.now_jst().date()


def test_today_uses_jst_across_utc_midnight_boundary(monkeypatch):
    """UTC では前日でも JST では翌日になる時刻で、JST 日付が返ることを確認する。"""

    # UTC 2026-06-26 23:30 == JST 2026-06-27 08:30
    fixed_utc = datetime.datetime(2026, 6, 26, 23, 30, tzinfo=datetime.timezone.utc)

    class _FixedDateTime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_utc.astimezone(tz) if tz is not None else fixed_utc

    # clock モジュール内の ``datetime`` 参照のみ差し替える（共有モジュールは汚さない）。
    fake_datetime_module = types.SimpleNamespace(
        datetime=_FixedDateTime,
        timezone=datetime.timezone,
        timedelta=datetime.timedelta,
        date=datetime.date,
    )
    monkeypatch.setattr(clock, "datetime", fake_datetime_module)

    assert clock.today() == datetime.date(2026, 6, 27)
