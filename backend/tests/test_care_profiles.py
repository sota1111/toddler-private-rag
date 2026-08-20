"""SOT-2729: 子どもごとの個別配慮プロファイル(care_profile) の CRUD・owner 分離・
additive migration 非破壊性のテスト。
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.routers.auth import get_current_user
from app import database, models

SQLALCHEMY_DATABASE_URL = "sqlite://"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 現在のリクエスト owner を差し替えるための可変ホルダ。
_current_owner = {"id": "ownerA"}


def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


def override_get_current_user():
    return _current_owner["id"]


@pytest.fixture(autouse=True)
def setup_and_teardown(monkeypatch):
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(database, "SessionLocal", TestingSessionLocal)
    monkeypatch.setitem(app.dependency_overrides, get_db, override_get_db)
    monkeypatch.setitem(app.dependency_overrides, get_current_user, override_get_current_user)
    _current_owner["id"] = "ownerA"
    yield
    Base.metadata.drop_all(bind=engine)


client = TestClient(app)


def _as(owner: str):
    _current_owner["id"] = owner


def _make_child(name: str = "たろう") -> str:
    return str(client.post("/api/children", json={"name": name}).json()["id"])


# --- CRUD ---

def test_create_get_update_delete_care_profile():
    child_id = _make_child()

    # 作成: 型付き属性 + 自由記述 + 重症度メモ
    resp = client.post(
        "/api/care-profiles",
        json={
            "child_id": child_id,
            "allergens": ["卵", "乳"],
            "care_categories": ["食物アレルギー"],
            "free_text": "エピペン携帯",
            "severity_note": "アナフィラキシー既往あり",
        },
    )
    assert resp.status_code == 200
    profile = resp.json()
    assert profile["child_id"] == child_id
    assert profile["allergens"] == ["卵", "乳"]
    assert profile["care_categories"] == ["食物アレルギー"]
    assert profile["free_text"] == "エピペン携帯"
    assert profile["severity_note"] == "アナフィラキシー既往あり"
    assert profile["updated_at"] is not None
    pid = profile["id"]

    # 取得(単体)
    fetched = client.get(f"/api/care-profiles/{pid}")
    assert fetched.status_code == 200
    assert fetched.json()["allergens"] == ["卵", "乳"]

    # 更新(部分更新: allergens のみ差し替え、他は現状維持)
    updated = client.put(
        f"/api/care-profiles/{pid}",
        json={"allergens": ["小麦"]},
    )
    assert updated.status_code == 200
    assert updated.json()["allergens"] == ["小麦"]
    assert updated.json()["care_categories"] == ["食物アレルギー"]  # 未指定=維持
    assert updated.json()["free_text"] == "エピペン携帯"  # 未指定=維持

    # 削除
    assert client.delete(f"/api/care-profiles/{pid}").status_code == 200
    assert client.get(f"/api/care-profiles/{pid}").status_code == 404


def test_create_with_minimal_fields_defaults_empty_lists():
    child_id = _make_child()
    resp = client.post("/api/care-profiles", json={"child_id": child_id})
    assert resp.status_code == 200
    body = resp.json()
    assert body["allergens"] == []
    assert body["care_categories"] == []
    assert body["free_text"] is None
    assert body["severity_note"] is None


def test_list_filtered_by_child_id():
    c1 = _make_child("たろう")
    c2 = _make_child("はなこ")
    client.post("/api/care-profiles", json={"child_id": c1, "allergens": ["卵"]})
    client.post("/api/care-profiles", json={"child_id": c2, "allergens": ["そば"]})

    # 全件
    assert len(client.get("/api/care-profiles").json()) == 2
    # child_id で絞り込み
    only_c1 = client.get(f"/api/care-profiles?child_id={c1}").json()
    assert [p["child_id"] for p in only_c1] == [c1]
    assert only_c1[0]["allergens"] == ["卵"]


def test_create_blank_child_id_rejected():
    assert client.post("/api/care-profiles", json={"child_id": "   "}).status_code == 422
    # child_id 欠落は Pydantic 必須で 422
    assert client.post("/api/care-profiles", json={}).status_code == 422


def test_blank_text_normalized_to_none():
    child_id = _make_child()
    resp = client.post(
        "/api/care-profiles",
        json={"child_id": child_id, "free_text": "   ", "severity_note": ""},
    )
    assert resp.status_code == 200
    assert resp.json()["free_text"] is None
    assert resp.json()["severity_note"] is None


def test_update_missing_profile_returns_404():
    assert client.put("/api/care-profiles/99999", json={"allergens": []}).status_code == 404


def test_delete_missing_profile_returns_404():
    assert client.delete("/api/care-profiles/99999").status_code == 404


# --- owner 分離 ---

def test_care_profiles_are_owner_scoped():
    _as("ownerA")
    a_child = _make_child("たろう")
    a_pid = client.post(
        "/api/care-profiles", json={"child_id": a_child, "allergens": ["卵"]}
    ).json()["id"]

    # ownerB は ownerA のプロファイルを一覧・取得・更新・削除できない
    _as("ownerB")
    assert client.get("/api/care-profiles").json() == []
    assert client.get(f"/api/care-profiles/{a_pid}").status_code == 404
    assert client.put(f"/api/care-profiles/{a_pid}", json={"allergens": ["乳"]}).status_code == 404
    assert client.delete(f"/api/care-profiles/{a_pid}").status_code == 404

    # ownerA 自身のプロファイルは無傷
    _as("ownerA")
    assert client.get(f"/api/care-profiles/{a_pid}").json()["allergens"] == ["卵"]


# --- additive migration 非破壊性 ---

def test_existing_child_rows_survive_care_profile_table(monkeypatch):
    """care_profile 追加後も既存 Child 行が読める(additive/非破壊)ことを確認する。"""
    from app.migrations import ensure_sqlite_schema

    # 既存 Child 行を直接投入
    db = TestingSessionLocal()
    try:
        db.add(models.Child(name="既存の子", owner_id="ownerA"))
        db.commit()
    finally:
        db.close()

    # マイグレーション(冪等)を流しても既存行は破壊されない
    ensure_sqlite_schema(engine)

    _as("ownerA")
    children = client.get("/api/children").json()
    assert any(c["name"] == "既存の子" for c in children)


# --- SOT-2736: 鮮度警告(古い情報の見直し提示) ---

def test_fresh_profile_has_no_stale_warning():
    child_id = _make_child()
    resp = client.post("/api/care-profiles", json={"child_id": child_id})
    assert resp.status_code == 200
    # 作成直後は古くないので警告 None。
    assert resp.json().get("stale_warning") is None


def test_stale_profile_returns_warning():
    import datetime
    from app import safety_guard

    child_id = _make_child()
    pid = client.post("/api/care-profiles", json={"child_id": child_id}).json()["id"]

    # updated_at を閾値超の過去へ直接書き換えて「古い」状態を作る。
    db = TestingSessionLocal()
    try:
        row = db.query(models.CareProfile).filter(models.CareProfile.id == int(pid)).one()
        row.updated_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
            days=safety_guard.STALE_THRESHOLD_DAYS + 30
        )
        db.commit()
    finally:
        db.close()

    fetched = client.get(f"/api/care-profiles/{pid}")
    assert fetched.status_code == 200
    warning = fetched.json().get("stale_warning")
    assert warning is not None
    assert "見直し" in warning or "古" in warning

    # 一覧でも同様に警告が載る。
    listed = client.get("/api/care-profiles", params={"child_id": child_id})
    assert listed.status_code == 200
    assert any(p.get("stale_warning") for p in listed.json())
