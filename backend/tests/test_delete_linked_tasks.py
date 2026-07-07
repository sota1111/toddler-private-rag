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

# SOT-1595: 写真削除時に「関連タスクも削除」を選んだとき、その写真(source_info_id)を基に
# 生成された関連タスク(draft/registered/archived)も併せて削除されることを検証する。
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


def _create_photo() -> str:
    """写真(添付ありレコード)を1件作り、その info id を返す。"""
    info_id = client.post(
        "/api/info/",
        json={"title": "写真", "info_type": "行事", "content": "c"},
    ).json()["id"]
    client.post(
        f"/api/info/{info_id}/attachments",
        files={"file": ("photo.png", PNG_BYTES, "image/png")},
    )
    return str(info_id)


def _create_task(source_info_id=None, registration_state="registered", is_archived=False) -> str:
    payload = {
        "title": "タスク",
        "info_type": "行事",
        "content": "c",
        "registration_state": registration_state,
        "is_archived": is_archived,
    }
    if source_info_id is not None:
        payload["source_info_id"] = str(source_info_id)
    return str(client.post("/api/info/", json=payload).json()["id"])


def _count_infos() -> int:
    db = TestingSessionLocal()
    try:
        return db.query(models.NurseryInfo).count()
    finally:
        db.close()


def test_linked_task_count_counts_draft_registered_and_archived():
    photo_id = _create_photo()
    _create_task(source_info_id=photo_id, registration_state="registered")
    _create_task(source_info_id=photo_id, registration_state="draft")
    _create_task(source_info_id=photo_id, registration_state="registered", is_archived=True)
    # 別写真由来の無関係タスクはカウントされない
    other_photo = _create_photo()
    _create_task(source_info_id=other_photo, registration_state="registered")
    # source_info_id 無しの手動タスクもカウントされない
    _create_task(source_info_id=None)

    resp = client.get(f"/api/info/{photo_id}/linked-task-count")
    assert resp.status_code == 200
    assert resp.json()["count"] == 3


def test_delete_without_option_keeps_linked_tasks():
    photo_id = _create_photo()
    linked_id = _create_task(source_info_id=photo_id)

    resp = client.delete(f"/api/info/{photo_id}")
    assert resp.status_code == 200
    assert resp.json()["deleted_linked_tasks"] == 0

    # 写真は消え、関連タスクは残っている（後方互換）
    assert client.get(f"/api/info/{photo_id}").status_code == 404
    assert client.get(f"/api/info/{linked_id}").status_code == 200


def test_delete_with_option_removes_photo_and_linked_tasks_only():
    photo_id = _create_photo()
    linked1 = _create_task(source_info_id=photo_id, registration_state="registered")
    linked2 = _create_task(source_info_id=photo_id, registration_state="draft")
    linked3 = _create_task(source_info_id=photo_id, registration_state="registered", is_archived=True)
    # 無関係タスク（別写真由来 / 手動）は残るべき
    other_photo = _create_photo()
    unrelated_linked = _create_task(source_info_id=other_photo)
    manual = _create_task(source_info_id=None)

    resp = client.delete(f"/api/info/{photo_id}", params={"delete_linked_tasks": True})
    assert resp.status_code == 200
    assert resp.json()["deleted_linked_tasks"] == 3

    # 写真と紐づくタスクは全て消えている
    assert client.get(f"/api/info/{photo_id}").status_code == 404
    for tid in (linked1, linked2, linked3):
        assert client.get(f"/api/info/{tid}").status_code == 404

    # 無関係な写真・タスクは残っている
    assert client.get(f"/api/info/{other_photo}").status_code == 200
    assert client.get(f"/api/info/{unrelated_linked}").status_code == 200
    assert client.get(f"/api/info/{manual}").status_code == 200
