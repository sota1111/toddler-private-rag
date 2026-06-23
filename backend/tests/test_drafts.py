"""仮登録(draft) / 本登録(finalize) のテスト (SOT-1113)。

- POST /info/ に registration_state="draft" で作成すると drafts 一覧にのみ出る
- 通常一覧 (/info/, /info/today 等) には draft が混ざらない
- POST /info/{id}/finalize で draft が registered になり通常一覧に出る
- registration_state 省略時は registered 扱い（後方互換）
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


def test_draft_appears_only_in_drafts_list():
    draft = _create(title="draft-1", registration_state="draft")
    assert draft["registration_state"] == "draft"

    draft_titles = {i["title"] for i in client.get("/api/info/drafts").json()}
    assert "draft-1" in draft_titles

    list_titles = {i["title"] for i in client.get("/api/info/").json()}
    assert "draft-1" not in list_titles


def test_default_create_is_registered():
    _create(title="registered-default")
    item = client.get("/api/info/").json()
    titles = {i["title"] for i in item}
    assert "registered-default" in titles
    assert all(i["registration_state"] == "registered" for i in item)
    assert client.get("/api/info/drafts").json() == []


def test_draft_excluded_from_today():
    today = datetime.date.today().isoformat()
    _create(title="draft-today", registration_state="draft", due_date=today)
    _create(title="reg-today", due_date=today)

    today_titles = {i["title"] for i in client.get("/api/info/today").json()}
    assert "reg-today" in today_titles
    assert "draft-today" not in today_titles


def test_finalize_moves_draft_to_registered():
    draft = _create(title="to-finalize", registration_state="draft")
    info_id = draft["id"]

    resp = client.post(f"/api/info/{info_id}/finalize")
    assert resp.status_code == 200, resp.text
    assert resp.json()["registration_state"] == "registered"

    # drafts から消える
    assert "to-finalize" not in {i["title"] for i in client.get("/api/info/drafts").json()}
    # 通常一覧に出る
    assert "to-finalize" in {i["title"] for i in client.get("/api/info/").json()}


def test_finalize_404_for_missing():
    resp = client.post("/api/info/999999/finalize")
    assert resp.status_code == 404
