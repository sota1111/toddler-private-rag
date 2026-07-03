"""能動リマインドのテスト (SOT-1080 / 提案5-A)。

- /info/reminders: 締切/行事/持ち物から緊急度付きリマインドを導出
- overdue/today/soon/upcoming の分類、対応済み締切の除外、horizon フィルタ
- /info/reminders/digest: 通知向けダイジェスト
- reminders.build_reminders の純粋ロジック単体テスト
"""

import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.routers.auth import get_current_user
from app import database, reminders, clock

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


def _iso(days: int) -> str:
    # サーバ実装(clock.today, JST基準)と同じ基準で相対日付を作る。
    # 素の datetime.date.today()(UTC基準)を使うと UTC/JST の日付境界をまたぐ時間帯で
    # サーバの「今日」とズレ、urgency 分類がフレークする (SOT-1493)。
    return (clock.today() + datetime.timedelta(days=days)).isoformat()


def _by_title(items, title):
    return next((r for r in items if r["title"] == title), None)


def test_deadline_urgency_buckets():
    _create(title="due-today", info_type="提出物", due_date=_iso(0))
    _create(title="due-soon", info_type="提出物", due_date=_iso(2))
    _create(title="due-upcoming", info_type="提出物", due_date=_iso(5))
    _create(title="due-overdue", info_type="提出物", due_date=_iso(-1))

    resp = client.get("/api/info/reminders")
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]

    assert _by_title(items, "due-today")["urgency"] == "today"
    assert _by_title(items, "due-soon")["urgency"] == "soon"
    assert _by_title(items, "due-upcoming")["urgency"] == "upcoming"
    assert _by_title(items, "due-overdue")["urgency"] == "overdue"


def test_done_deadline_is_excluded():
    _create(title="done-due", info_type="提出物", due_date=_iso(-1), status="対応済み")
    _create(title="open-due", info_type="提出物", due_date=_iso(-1), status="未対応")

    items = client.get("/api/info/reminders").json()["items"]
    assert _by_title(items, "done-due") is None
    assert _by_title(items, "open-due") is not None


def test_horizon_filter():
    _create(title="far-due", info_type="提出物", due_date=_iso(30))

    default_items = client.get("/api/info/reminders").json()["items"]
    assert _by_title(default_items, "far-due") is None

    wide_items = client.get("/api/info/reminders", params={"horizon_days": 60}).json()["items"]
    assert _by_title(wide_items, "far-due") is not None


def test_event_reminder_and_past_event_excluded():
    _create(title="event-soon", info_type="行事", event_date=_iso(1))
    _create(title="event-past", info_type="行事", event_date=_iso(-2))

    items = client.get("/api/info/reminders").json()["items"]
    soon = _by_title(items, "event-soon")
    assert soon is not None and soon["urgency"] == "soon" and soon["kind"] == "event"
    assert _by_title(items, "event-past") is None


def test_belongings_day_before():
    _create(title="pool-day", info_type="持ち物", event_date=_iso(1), items="水着\nタオル")
    items = client.get("/api/info/reminders").json()["items"]
    belongings = [r for r in items if r["kind"] == "belongings"]
    assert any("水着" in r["message"] for r in belongings)


def test_counts_summary():
    _create(title="due-today", info_type="提出物", due_date=_iso(0))
    _create(title="due-overdue", info_type="提出物", due_date=_iso(-1))
    counts = client.get("/api/info/reminders").json()["counts"]
    assert counts["overdue"] == 1
    assert counts["today"] == 1
    assert counts["total"] >= 2


def test_digest_endpoint_non_empty():
    _create(title="due-today", info_type="提出物", due_date=_iso(0))
    resp = client.get("/api/info/reminders/digest")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total"] >= 1
    assert isinstance(data["digest"], str) and data["digest"].strip()


def test_digest_empty_state():
    resp = client.get("/api/info/reminders/digest")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0
    assert resp.json()["digest"].strip()  # friendly "no reminders" line


# --- pure logic unit tests (no HTTP) ---

def test_build_reminders_sorting_and_buckets():
    today = datetime.date(2026, 6, 22)

    def info(**kw):
        base = dict(id=1, title="x", info_type="提出物", status="未対応",
                    priority="普通", due_date=None, event_date=None, date=None, items=None)
        base.update(kw)
        return SimpleNamespace(**base)

    infos = [
        info(id=1, title="upcoming", due_date=today + datetime.timedelta(days=5)),
        info(id=2, title="overdue", due_date=today - datetime.timedelta(days=1)),
        info(id=3, title="today", due_date=today),
    ]
    out = reminders.build_reminders(infos, today=today, horizon_days=7)
    # overdue first, then today, then upcoming
    assert [r["title"] for r in out] == ["overdue", "today", "upcoming"]


def test_build_reminders_excludes_done_and_far():
    today = datetime.date(2026, 6, 22)
    infos = [
        SimpleNamespace(id=1, title="done", info_type="提出物", status="対応済み",
                        priority="普通", due_date=today, event_date=None, date=None, items=None),
        SimpleNamespace(id=2, title="far", info_type="提出物", status="未対応",
                        priority="普通", due_date=today + datetime.timedelta(days=30),
                        event_date=None, date=None, items=None),
    ]
    out = reminders.build_reminders(infos, today=today, horizon_days=7)
    assert out == []
