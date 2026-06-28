"""AI-worker dispatch wiring + worker endpoint tests.

SOT-1359: the lightweight upload Cloud Run service was replaced by a gen2 Cloud Function
(`backend/upload_function/`, tested separately in test_upload_function.py). This file retains the
tests for the still-present pieces: `worker_client.dispatch_ocr` and the `/internal/process-ocr`
worker endpoint on the main backend.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import database, worker_client
from app.database import Base, get_db
from app.routers.auth import get_current_user
from app.main import app as main_app
from app.routers import worker as worker_router
from app import models

# In-memory test DB shared across the apps and the standalone repo helpers.
engine = create_engine(
    "sqlite://",
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


def override_get_current_user():
    return "test_user"


@pytest.fixture(autouse=True)
def setup_db(monkeypatch):
    Base.metadata.create_all(bind=engine)
    # standalone repos (used by the worker endpoint) open database.SessionLocal directly.
    monkeypatch.setattr(database, "SessionLocal", TestingSessionLocal)
    monkeypatch.setitem(main_app.dependency_overrides, get_db, override_get_db)
    monkeypatch.setitem(main_app.dependency_overrides, get_current_user, override_get_current_user)
    yield
    Base.metadata.drop_all(bind=engine)


def _create_info() -> int:
    db = TestingSessionLocal()
    try:
        info = models.NurseryInfo(title="Test", info_type="行事", content="Test")
        db.add(info)
        db.commit()
        db.refresh(info)
        return info.id
    finally:
        db.close()


def _create_attachment(info_id: int) -> int:
    db = TestingSessionLocal()
    try:
        att = models.Attachment(
            info_id=info_id,
            stored_filename="x.png",
            original_filename="x.png",
            mime_type="image/png",
            file_size=3,
            storage_backend="local",
            object_key="x.png",
            ocr_status="pending",
        )
        db.add(att)
        db.commit()
        db.refresh(att)
        return att.id
    finally:
        db.close()


# ---- worker_client.dispatch_ocr ----

def test_dispatch_noop_when_url_unset(monkeypatch):
    monkeypatch.delenv("AI_WORKER_URL", raising=False)
    assert worker_client.dispatch_ocr(1, 2, "ja") is False


def test_dispatch_posts_with_token(monkeypatch):
    monkeypatch.setenv("AI_WORKER_URL", "https://worker.example.com")
    monkeypatch.setenv("WORKER_INVOKE_TOKEN", "secret-token")
    captured = {}

    class _Resp:
        status_code = 202
        text = ""

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return _Resp()

    monkeypatch.setattr(worker_client.httpx, "post", fake_post)
    assert worker_client.dispatch_ocr(7, 3, "en") is True
    assert captured["url"] == "https://worker.example.com/internal/process-ocr"
    assert captured["json"] == {"att_id": 7, "info_id": 3, "language": "en"}
    assert captured["headers"]["X-Worker-Token"] == "secret-token"


# ---- 3. worker endpoint /internal/process-ocr ----

def test_worker_endpoint_rejects_bad_token(monkeypatch):
    monkeypatch.setenv("WORKER_INVOKE_TOKEN", "expected")
    client = TestClient(main_app)
    resp = client.post("/internal/process-ocr", json={"att_id": 1})
    assert resp.status_code == 403


def test_worker_endpoint_accepts_and_schedules(monkeypatch):
    monkeypatch.delenv("WORKER_INVOKE_TOKEN", raising=False)
    info_id = _create_info()
    att_id = _create_attachment(info_id)

    scheduled = []
    monkeypatch.setattr(
        worker_router, "process_ocr",
        lambda *args, **kwargs: scheduled.append(args),
    )

    class _Backend:
        name = "local"

        def read(self, object_key):
            return b"img"

        def local_path_for_ocr(self, object_key, content):
            return "/tmp/x.png"

    monkeypatch.setattr(worker_router.storage, "get_storage", lambda: _Backend())

    client = TestClient(main_app)
    resp = client.post(
        "/internal/process-ocr",
        json={"att_id": att_id, "info_id": info_id, "language": "ja"},
    )
    assert resp.status_code == 202, resp.text
    assert resp.json()["att_id"] == att_id
    # background task runs after the response in TestClient
    assert len(scheduled) == 1
    assert scheduled[0][0] == att_id


def test_worker_endpoint_unknown_attachment_404(monkeypatch):
    monkeypatch.delenv("WORKER_INVOKE_TOKEN", raising=False)
    client = TestClient(main_app)
    resp = client.post("/internal/process-ocr", json={"att_id": 424242})
    assert resp.status_code == 404
