"""ダッシュボードビューのテスト (SOT-1085 / SOT-1093)。

- /info/today: 本日が date/event_date/due_date のいずれかに該当する情報を返す
- /info/pending: 全カテゴリ横断で status=="未対応" を返す（提出物に限定しない）
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.routers.auth import get_current_user
from app import database
from app import clock

SQLALCHEMY_DATABASE_URL = "sqlite://"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def setup_and_teardown(monkeypatch):
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(database, "SessionLocal", TestingSessionLocal)
    monkeypatch.setitem(app.dependency_overrides, get_db, override_get_db)
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: "test_user")
    yield
    Base.metadata.drop_all(bind=engine)


client = TestClient(app)


def _create(**kwargs):
    body = {"title": "t", "info_type": "お知らせ", "content": "c"}
    body.update(kwargs)
    resp = client.post("/api/info/", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_today_includes_due_event_and_date_today():
    today = clock.today().isoformat()
    _create(title="due-today", info_type="提出物", due_date=today)
    _create(title="event-today", info_type="行事", event_date=today)
    _create(title="date-today", info_type="持ち物", date=today)
    _create(title="not-today", info_type="お知らせ", date="2000-01-01")

    titles = {i["title"] for i in client.get("/api/info/today").json()}
    assert {"due-today", "event-today", "date-today"} <= titles
    assert "not-today" not in titles


def test_pending_spans_all_categories():
    _create(title="pending-doc", info_type="資料", status="未対応")
    _create(title="pending-submission", info_type="提出物", status="未対応")
    _create(title="done-item", info_type="提出物", status="対応済み")

    titles = {i["title"] for i in client.get("/api/info/pending").json()}
    assert {"pending-doc", "pending-submission"} <= titles
    assert "done-item" not in titles


def test_weekly_and_next_week_use_calendar_week_boundaries(monkeypatch):
    """SOT-1424: 今週/来週の予定はカレンダー週（月曜始まり）境界で集計する。

    本日起点のローリング窓だと、カレンダー上「来週」でも本日から7日以内の予定は
    「今週」枠に入り「来週」枠が空白になっていた。来週の予定が「来週」枠に出ること、
    今週末までの予定が「今週」枠に出ることを検証する。
    """
    import datetime as _dt

    # 固定日を水曜にして週境界を決定的にする。
    fixed_today = _dt.date(2026, 7, 1)  # Wednesday
    assert fixed_today.weekday() == 2
    monkeypatch.setattr(clock, "today", lambda: fixed_today)

    this_week_end = fixed_today + _dt.timedelta(days=(6 - fixed_today.weekday()))  # Sunday 2026-07-05
    next_monday = this_week_end + _dt.timedelta(days=1)                            # Monday 2026-07-06
    next_sunday = next_monday + _dt.timedelta(days=6)                              # Sunday 2026-07-12
    week_after_next = next_sunday + _dt.timedelta(days=1)                          # Monday 2026-07-13

    _create(title="this-week", info_type="行事", event_date=this_week_end.isoformat())
    # カレンダー上「来週」だが本日から5日後＝旧ローリング窓では「今週」に吸われていた予定。
    _create(title="next-week-mon", info_type="行事", event_date=next_monday.isoformat())
    _create(title="next-week-sun", info_type="行事", event_date=next_sunday.isoformat())
    _create(title="week-after-next", info_type="行事", event_date=week_after_next.isoformat())

    weekly_titles = {i["title"] for i in client.get("/api/info/weekly").json()}
    next_week_titles = {i["title"] for i in client.get("/api/info/next-week").json()}

    # 今週枠: 今週末までの行事のみ。来週以降は含まない。
    assert "this-week" in weekly_titles
    assert "next-week-mon" not in weekly_titles
    assert "next-week-sun" not in weekly_titles

    # 来週枠: 翌カレンダー週(月〜日)の行事が表示される（空白にならない）。
    assert {"next-week-mon", "next-week-sun"} <= next_week_titles
    assert "this-week" not in next_week_titles
    assert "week-after-next" not in next_week_titles
