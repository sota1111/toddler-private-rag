"""SOT-1431: マルチテナント owner 分離のテスト。

各ユーザーは自分のデータのみ閲覧/取得/削除でき、他ユーザーのデータには一切アクセスできない。
「全データ削除」は押したユーザー自身のデータだけを消す。
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from tests._images import PNG_BYTES
from app.database import Base, get_db
from app.routers.auth import get_current_user
from app import storage, models, database

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
def setup_and_teardown(tmp_path, monkeypatch):
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(database, "SessionLocal", TestingSessionLocal)
    monkeypatch.setitem(app.dependency_overrides, get_db, override_get_db)
    monkeypatch.setitem(app.dependency_overrides, get_current_user, override_get_current_user)

    test_upload_dir = tmp_path / "uploads"
    test_upload_dir.mkdir(parents=True, exist_ok=True)
    original_upload_dir = storage.UPLOAD_DIR
    storage.UPLOAD_DIR = test_upload_dir

    _current_owner["id"] = "ownerA"
    yield

    Base.metadata.drop_all(bind=engine)
    storage.UPLOAD_DIR = original_upload_dir


client = TestClient(app)


def _as(owner: str):
    _current_owner["id"] = owner


def _create_info(title: str) -> str:
    return client.post(
        "/api/info/",
        json={"title": title, "info_type": "行事", "content": "c"},
    ).json()["id"]


def test_user_cannot_list_or_get_other_users_info():
    _as("ownerA")
    a_id = _create_info("A only")

    # ownerB は ownerA のデータを一覧に見られない
    _as("ownerB")
    listed = client.get("/api/info/").json()
    assert all(str(item["id"]) != str(a_id) for item in listed)

    # ownerB は ID 直指定でも 404
    assert client.get(f"/api/info/{a_id}").status_code == 404

    # ownerA 自身は見られる
    _as("ownerA")
    assert client.get(f"/api/info/{a_id}").status_code == 200
    assert any(str(item["id"]) == str(a_id) for item in client.get("/api/info/").json())


def test_user_cannot_update_or_delete_other_users_info():
    _as("ownerA")
    a_id = _create_info("A only")

    _as("ownerB")
    # 他 owner の更新/削除は 404
    assert client.put(f"/api/info/{a_id}", json={"title": "hacked"}).status_code == 404
    assert client.delete(f"/api/info/{a_id}").status_code == 404

    # ownerA のデータは無傷
    _as("ownerA")
    assert client.get(f"/api/info/{a_id}").json()["title"] == "A only"


def test_delete_all_is_scoped_to_caller():
    _as("ownerA")
    _create_info("A1")
    _create_info("A2")
    _as("ownerB")
    b_id = _create_info("B1")

    # ownerB が全データ削除 → 自分の1件のみ削除
    resp = client.delete("/api/info")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 1

    # ownerA のデータは残っている
    _as("ownerA")
    assert len(client.get("/api/info/").json()) == 2

    # ownerB のデータは消えている
    _as("ownerB")
    assert client.get(f"/api/info/{b_id}").status_code == 404
    assert len(client.get("/api/info/").json()) == 0


def test_attachment_file_access_is_owner_scoped():
    _as("ownerA")
    a_id = _create_info("A with photo")
    att_id = client.post(
        f"/api/info/{a_id}/attachments",
        files={"file": ("photo.png", PNG_BYTES, "image/png")},
    ).json()["id"]

    # ownerB は他 owner の添付ファイル/文字起こし/削除に触れない
    _as("ownerB")
    assert client.get(f"/api/attachments/{att_id}/file").status_code == 404
    assert client.get(f"/api/attachments/{att_id}/transcription").status_code == 404
    assert client.delete(f"/api/attachments/{att_id}").status_code == 404

    # ownerA 自身はアクセスできる
    _as("ownerA")
    assert client.get(f"/api/attachments/{att_id}/file").status_code == 200


def test_children_are_owner_scoped():
    _as("ownerA")
    client.post("/api/children", json={"name": "たろう"})

    _as("ownerB")
    assert client.get("/api/children").json() == []
    client.post("/api/children", json={"name": "はなこ"})
    b_children = client.get("/api/children").json()
    assert [c["name"] for c in b_children] == ["はなこ"]

    _as("ownerA")
    a_children = client.get("/api/children").json()
    assert [c["name"] for c in a_children] == ["たろう"]
    # ownerB は ownerA の子供を削除できない
    _as("ownerB")
    assert client.delete(f"/api/children/{a_children[0]['id']}").status_code == 404


def test_legacy_null_owner_rows_belong_to_default_user():
    """owner 未設定(NULL)の既存データは既定 owner(主ユーザー)のものとして扱われる。"""
    from app.identity import DEFAULT_OWNER_ID

    db = TestingSessionLocal()
    try:
        db.add(models.NurseryInfo(title="legacy", info_type="行事", content="c", owner_id=None))
        db.commit()
    finally:
        db.close()

    # 既定 owner なら NULL 行が見える
    _as(DEFAULT_OWNER_ID)
    titles = [i["title"] for i in client.get("/api/info/").json()]
    assert "legacy" in titles

    # 別 owner には見えない
    _as("ownerB")
    titles = [i["title"] for i in client.get("/api/info/").json()]
    assert "legacy" not in titles
