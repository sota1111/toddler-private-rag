"""ダッシュボードビューのテスト (SOT-1085 / SOT-1093)。

- /info/today: 本日が date/event_date/due_date のいずれかに該当する情報を返す
- /info/pending: 全カテゴリ横断で status=="未対応" を返す（提出物に限定しない）
"""

import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.routers.auth import get_current_user
from app import database

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
    today = datetime.date.today().isoformat()
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
