"""仮登録(draft) / 本登録(finalize) のテスト (SOT-1113)。

- POST /info/ に registration_state="draft" で作成すると drafts 一覧にのみ出る
- 通常一覧 (/info/, /info/today 等) には draft が混ざらない
- POST /info/{id}/finalize で draft が registered になり通常一覧に出る
- registration_state 省略時は registered 扱い（後方互換）
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.routers.auth import get_current_user
from app import database, clock

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
    # /api/info/today はサーバの clock.today()(JST基準) で判定するため、
    # テストも同じ基準で「今日」を作る。素の date.today()(UTC) だと
    # UTC/JST 境界時間帯でフレークする (SOT-1493)。
    today = clock.today().isoformat()
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


def test_create_draft_with_empty_string_dates(monkeypatch):
    """SOT-1197: 自動登録の save-first ペイロード（空文字の日付）で 422 にならない。

    フロント AutoRegisterPage は date/event_date/due_date を空文字 "" で送る。
    空文字は「未設定」として None に正規化され、作成が成功すること。
    """
    body = {
        "title": "",
        "info_type": "資料",
        "content": "",
        "date": "",
        "event_date": "",
        "due_date": "",
        "items": "",
        "status": "未対応",
        "priority": "普通",
        "tags": "",
        "memo": "",
        "registration_state": "draft",
    }
    resp = client.post("/api/info/", json=body)
    assert resp.status_code == 200, resp.text
    created = resp.json()
    assert created["date"] is None
    assert created["event_date"] is None
    assert created["due_date"] is None
    assert created["registration_state"] == "draft"

    # PUT 更新（enrichment 経路）でも空文字日付が許容される
    upd = client.put(f"/api/info/{created['id']}", json={"date": "", "event_date": "2026-07-01"})
    assert upd.status_code == 200, upd.text
    assert upd.json()["date"] is None
    assert upd.json()["event_date"] == "2026-07-01"
