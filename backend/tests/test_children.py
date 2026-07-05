import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.routers.auth import get_current_user
from app import database

# SOT-1368: 子供(option A)の登録・一覧・削除と、child_id 付き info 作成のテスト。
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


def test_create_list_delete_child():
    # 作成
    resp = client.post("/api/children", json={"name": "たろう"})
    assert resp.status_code == 200
    child = resp.json()
    assert child["name"] == "たろう"
    child_id = child["id"]

    # 2人目
    client.post("/api/children", json={"name": "はなこ"})

    # 一覧（作成順）
    listed = client.get("/api/children").json()
    assert [c["name"] for c in listed] == ["たろう", "はなこ"]

    # 削除
    assert client.delete(f"/api/children/{child_id}").status_code == 200
    listed = client.get("/api/children").json()
    assert [c["name"] for c in listed] == ["はなこ"]


def test_create_child_with_group_name_roundtrips():
    # SOT-1552: 名前と一緒に組/クラスを登録でき、一覧・作成レスポンスで返る。
    resp = client.post(
        "/api/children", json={"name": "たろう", "group_name": "ひまわり組"}
    )
    assert resp.status_code == 200
    assert resp.json()["group_name"] == "ひまわり組"

    listed = client.get("/api/children").json()
    assert listed[0]["group_name"] == "ひまわり組"


def test_create_child_without_group_name_is_backward_compatible():
    # SOT-1552: 組/クラス未指定でも従来どおり登録でき、group_name は None。
    resp = client.post("/api/children", json={"name": "はなこ"})
    assert resp.status_code == 200
    assert resp.json()["group_name"] is None


def test_create_child_blank_group_name_normalized_to_none():
    # SOT-1552: 空白のみの組/クラスは未設定(None)に正規化する。
    resp = client.post(
        "/api/children", json={"name": "じろう", "group_name": "   "}
    )
    assert resp.status_code == 200
    assert resp.json()["group_name"] is None


def test_delete_missing_child_returns_404():
    assert client.delete("/api/children/99999").status_code == 404


def test_create_child_blank_name_rejected():
    assert client.post("/api/children", json={"name": "  "}).status_code == 422


def test_create_info_with_child_id_roundtrips():
    child_id = client.post("/api/children", json={"name": "たろう"}).json()["id"]
    resp = client.post(
        "/api/info/",
        json={"title": "T", "info_type": "行事", "content": "c", "child_id": str(child_id)},
    )
    assert resp.status_code == 200
    info = resp.json()
    assert info["child_id"] == str(child_id)

    # 取得でも child_id が返る
    fetched = client.get(f"/api/info/{info['id']}").json()
    assert fetched["child_id"] == str(child_id)


def test_create_info_without_child_id_is_backward_compatible():
    resp = client.post(
        "/api/info/",
        json={"title": "T", "info_type": "行事", "content": "c"},
    )
    assert resp.status_code == 200
    assert resp.json()["child_id"] is None
