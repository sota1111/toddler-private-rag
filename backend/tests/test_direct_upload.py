"""SOT-1377: GCS direct upload (session 発行 EP + finalize イベント + 冪等 OCR) のテスト。

ライブ GCP（署名 URL / CORS / Pub/Sub）は本環境で検証できないため、ここでは
session 発行 EP の契約・バリデーション、object_key 逆引き、OCR 起動の冪等性(CAS)、
finalize push の token 検証 / 孤児スキップ / 重複配送吸収をユニットで検証する。
"""
import datetime
import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.routers.auth import get_current_user
from app import storage, database
from app.routers import worker as worker_router

SQLALCHEMY_DATABASE_URL = "sqlite://"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


class FakeGCS:
    """direct upload 用の最小スタブ。署名 URL は固定値、read は OCR をモックするため未使用。"""

    name = "gcs"

    def generate_upload_signed_url(self, object_key, content_type, expires_minutes=15):
        return {
            "url": f"https://storage.example.com/{object_key}?X-Goog-Signature=fake",
            "expires_at": datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(minutes=expires_minutes),
        }

    def read(self, object_key):
        return b"fake-bytes"

    def local_path_for_ocr(self, object_key, content):
        fd, path = tempfile.mkstemp()
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        return Path(path)


@pytest.fixture(autouse=True)
def setup_and_teardown(monkeypatch):
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(database, "SessionLocal", TestingSessionLocal)
    monkeypatch.setitem(app.dependency_overrides, get_db, override_get_db)
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: "test_user")
    monkeypatch.setattr(storage, "get_storage", lambda: FakeGCS())
    yield
    Base.metadata.drop_all(bind=engine)


client = TestClient(app)


def _create_info():
    resp = client.post(
        "/api/info/",
        json={"title": "T", "info_type": "資料", "content": "c", "registration_state": "processing"},
    )
    assert resp.status_code == 200
    return resp.json()["id"]


def test_create_upload_session_returns_signed_url():
    info_id = _create_info()
    resp = client.post(
        f"/api/info/{info_id}/upload/session",
        json={"filename": "photo.jpg", "content_type": "image/jpeg", "file_size": 1234, "language": "en"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["upload_url"].startswith("https://storage.example.com/")
    assert body["object_key"]
    assert body["method"] == "PUT"
    assert body["upload_id"]

    # pending の Attachment が language 付きで作成されている
    from app.repository import SqliteAttachmentRepository

    db = TestingSessionLocal()
    try:
        repo = SqliteAttachmentRepository(db)
        att = repo.get(body["upload_id"])
        assert att is not None
        assert att.ocr_status == "pending"
        assert att.language == "en"
        assert att.object_key == body["object_key"]
    finally:
        db.close()


def test_upload_session_rejects_unsupported_type():
    info_id = _create_info()
    resp = client.post(
        f"/api/info/{info_id}/upload/session",
        json={"filename": "x.txt", "content_type": "text/plain"},
    )
    assert resp.status_code == 400


def test_upload_session_rejects_too_large():
    info_id = _create_info()
    resp = client.post(
        f"/api/info/{info_id}/upload/session",
        json={"filename": "big.jpg", "content_type": "image/jpeg", "file_size": 11 * 1024 * 1024},
    )
    assert resp.status_code == 413


def test_upload_session_missing_info_404():
    resp = client.post(
        "/api/info/999999/upload/session",
        json={"filename": "p.jpg", "content_type": "image/jpeg"},
    )
    assert resp.status_code == 404


def test_begin_ocr_if_pending_is_cas():
    from app.repository import SqliteAttachmentRepository

    info_id = _create_info()
    db = TestingSessionLocal()
    try:
        repo = SqliteAttachmentRepository(db)
        att = repo.create(
            info_id=info_id,
            stored_filename="f.jpg",
            original_filename="f.jpg",
            mime_type="image/jpeg",
            file_size=1,
            storage_backend="gcs",
            object_key="uploads/f.jpg",
            ocr_text=None,
            ocr_status="pending",
            language="ja",
        )
        # 逆引き
        assert repo.get_by_object_key("uploads/f.jpg").id == att.id
        # 最初の遷移だけ成功する
        assert repo.begin_ocr_if_pending(att.id) is True
        assert repo.begin_ocr_if_pending(att.id) is False
        assert repo.get(att.id).ocr_status == "processing"
    finally:
        db.close()


def test_finalize_rejects_bad_token(monkeypatch):
    monkeypatch.setenv("WORKER_INVOKE_TOKEN", "secret")
    resp = client.post(
        "/internal/gcs-finalize?token=wrong",
        json={"message": {"attributes": {"objectId": "uploads/x.jpg", "eventType": "OBJECT_FINALIZE"}}},
    )
    assert resp.status_code == 403


def test_finalize_orphan_ignored(monkeypatch):
    monkeypatch.setenv("WORKER_INVOKE_TOKEN", "secret")
    resp = client.post(
        "/internal/gcs-finalize?token=secret",
        json={"message": {"attributes": {"objectId": "uploads/none.jpg", "eventType": "OBJECT_FINALIZE"}}},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


def test_finalize_triggers_ocr_once(monkeypatch):
    monkeypatch.setenv("WORKER_INVOKE_TOKEN", "secret")
    calls = []
    monkeypatch.setattr(worker_router, "process_ocr", lambda *a, **k: calls.append(a))

    from app.repository import SqliteAttachmentRepository

    info_id = _create_info()
    db = TestingSessionLocal()
    try:
        repo = SqliteAttachmentRepository(db)
        att = repo.create(
            info_id=info_id,
            stored_filename="g.jpg",
            original_filename="g.jpg",
            mime_type="image/jpeg",
            file_size=1,
            storage_backend="gcs",
            object_key="uploads/g.jpg",
            ocr_text=None,
            ocr_status="pending",
            language="ja",
        )
        att_id = att.id
    finally:
        db.close()

    envelope = {"message": {"attributes": {"objectId": "uploads/g.jpg", "eventType": "OBJECT_FINALIZE"}}}
    r1 = client.post("/internal/gcs-finalize?token=secret", json=envelope)
    assert r1.status_code == 200
    assert r1.json()["status"] == "accepted"
    # 重複配送: CAS で吸収され OCR は再起動しない
    r2 = client.post("/internal/gcs-finalize?token=secret", json=envelope)
    assert r2.status_code == 200
    assert r2.json()["status"] == "skipped"

    assert len(calls) == 1
    assert calls[0][0] == att_id
