import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.routers.auth import get_current_user
from app import database

# SOT-1500: アーカイブ機能のテスト。
# - PUT /api/info/{id} で is_archived=true にするとアクティブ一覧(GET /api/info/)から消える
# - GET /api/info/archived はアーカイブ済みのみを返す
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


def override_get_current_user():
    return "test_user"


@pytest.fixture(autouse=True)
def setup_and_teardown(monkeypatch):
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(database, "SessionLocal", TestingSessionLocal)
    monkeypatch.setitem(app.dependency_overrides, get_db, override_get_db)
    monkeypatch.setitem(app.dependency_overrides, get_current_user, override_get_current_user)
    yield
    Base.metadata.drop_all(bind=engine)


client = TestClient(app)


def _create(title: str) -> int:
    return client.post(
        "/api/info/",
        json={"title": title, "info_type": "行事", "content": "c"},
    ).json()["id"]


def test_new_info_is_not_archived_by_default():
    _create("A")
    # 既定では is_archived=false でアクティブ一覧に出る
    titles = [r["title"] for r in client.get("/api/info/").json()]
    assert "A" in titles
    # アーカイブ一覧は空
    assert client.get("/api/info/archived").json() == []


def test_archiving_moves_item_out_of_active_list_into_archive():
    keep_id = _create("keep")
    arch_id = _create("archived")

    # 1件をアーカイブする
    resp = client.put(f"/api/info/{arch_id}", json={"is_archived": True})
    assert resp.status_code == 200
    assert resp.json()["is_archived"] is True

    # アクティブ一覧にはアーカイブ済みが出ない
    active_titles = [r["title"] for r in client.get("/api/info/").json()]
    assert "keep" in active_titles
    assert "archived" not in active_titles

    # アーカイブ一覧にはアーカイブ済みのみ出る
    archived = client.get("/api/info/archived").json()
    archived_titles = [r["title"] for r in archived]
    assert archived_titles == ["archived"]
    assert all(r["is_archived"] for r in archived)

    # 個別取得はアーカイブ済みでも 200（詳細画面は引き続き開ける）
    assert client.get(f"/api/info/{arch_id}").status_code == 200
    # keep はアーカイブされていない
    assert client.get(f"/api/info/{keep_id}").json()["is_archived"] is False


def test_unarchive_returns_item_to_active_list():
    info_id = _create("toggle")
    client.put(f"/api/info/{info_id}", json={"is_archived": True})
    assert "toggle" not in [r["title"] for r in client.get("/api/info/").json()]

    # is_archived=false に戻すとアクティブ一覧へ復帰し、アーカイブ一覧から消える
    client.put(f"/api/info/{info_id}", json={"is_archived": False})
    assert "toggle" in [r["title"] for r in client.get("/api/info/").json()]
    assert client.get("/api/info/archived").json() == []
