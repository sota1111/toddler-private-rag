"""アプリ全体で「今日の日付」を一貫したタイムゾーンで取得するための共通ヘルパ (SOT-1297)。

掲示板（今日/明日/今週/来週の予定）や質問（RAG/Ask）は「今日」を基準に動く。
本番 Cloud Run のコンテナ時刻は UTC のため、素の ``datetime.date.today()`` を使うと
JST 00:00〜09:00 の間はサーバが「前日」と判定し、日付が1日ズレる。

このモジュールの ``today()`` / ``now_jst()`` を唯一の取得経路にすることで、
アプリの「今日」を常に JST(Asia/Tokyo, 既定) に固定する。
タイムゾーンは環境変数 ``APP_TIMEZONE`` で上書きできる。
"""

import datetime
import os

# JST 固定オフセット (+09:00)。tzdata 不在環境でも JST を保証するフォールバックに使う。
_JST_FALLBACK = datetime.timezone(datetime.timedelta(hours=9))


def _app_tz() -> datetime.tzinfo:
    """``APP_TIMEZONE``(既定 Asia/Tokyo) の tzinfo を返す。

    ``zoneinfo`` が利用できない / tzdata が無い環境では JST(+09:00) 固定にフォールバックする。
    """
    name = os.getenv("APP_TIMEZONE", "Asia/Tokyo").strip() or "Asia/Tokyo"
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:
        return _JST_FALLBACK


def now_jst() -> datetime.datetime:
    """アプリのタイムゾーン(既定 JST)での現在時刻(aware datetime)。"""
    return datetime.datetime.now(_app_tz())


def today() -> datetime.date:
    """アプリのタイムゾーン(既定 JST)での「今日」の日付。"""
    return now_jst().date()
