import pytest
import os
import shutil
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from tests._images import PNG_BYTES
from app.database import Base, get_db
from app.routers.auth import get_current_user
from app import storage, models, database

# SOT-1356: 設定画面の全データ削除 (DELETE /api/info) のテスト。
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
def setup_and_teardown(tmp_path, monkeypatch):
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(database, "SessionLocal", TestingSessionLocal)
    monkeypatch.setitem(app.dependency_overrides, get_db, override_get_db)
    monkeypatch.setitem(app.dependency_overrides, get_current_user, override_get_current_user)

    test_upload_dir = tmp_path / "uploads"
    os.makedirs(test_upload_dir, exist_ok=True)
    original_upload_dir = storage.UPLOAD_DIR
    storage.UPLOAD_DIR = test_upload_dir

    yield

    Base.metadata.drop_all(bind=engine)
    if test_upload_dir.exists():
        shutil.rmtree(test_upload_dir)
    storage.UPLOAD_DIR = original_upload_dir


client = TestClient(app)


def _create_info_with_attachment():
    info_id = client.post(
        "/api/info/",
        json={"title": "T", "info_type": "行事", "content": "c"},
    ).json()["id"]
    att_id = client.post(
        f"/api/info/{info_id}/attachments",
        files={"file": ("photo.png", PNG_BYTES, "image/png")},
    ).json()["id"]
    return info_id, att_id


def test_delete_all_removes_tasks_and_photos(monkeypatch):
    # 2件の info + それぞれ写真を作成
    _create_info_with_attachment()
    info_id2, _ = _create_info_with_attachment()

    deleted_keys = []
    real_storage = storage.get_storage()
    monkeypatch.setattr(real_storage, "delete", lambda key: deleted_keys.append(key))
    monkeypatch.setattr(storage, "get_storage", lambda: real_storage)

    resp = client.delete("/api/info")
    assert resp.status_code == 200
    body = resp.json()
    assert body["deleted"] == 2

    # DB から全 info + 全 attachment が消えている
    db = TestingSessionLocal()
    assert db.query(models.NurseryInfo).count() == 0
    assert db.query(models.Attachment).count() == 0
    db.close()

    # ストレージ blob 削除が写真の数だけ呼ばれている
    assert len(deleted_keys) == 2

    # 個別取得も 404
    assert client.get(f"/api/info/{info_id2}").status_code == 404


def test_delete_all_when_empty_returns_zero():
    resp = client.delete("/api/info")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 0
