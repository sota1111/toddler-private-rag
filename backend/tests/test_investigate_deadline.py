"""締切調査エンドポイントのテスト (SOT-1406)。

POST /info/{id}/investigate-deadline は、調査対象テキストにタスクのタイトルを含める。
手動追加タスク（書類名がタイトルに入り、本文が空/簡素）でも書類抽出が走るようにするため。
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.routers.auth import get_current_user
from app import database, submission_agent
from app.repository import SqliteInfoRepository

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


def test_investigate_includes_title_in_safe_text(monkeypatch):
    """タイトルに書類名があり本文が空でも、調査対象テキストにタイトルが含まれる。"""
    captured = {}

    def fake_drafts(safe_text, detected_dates=None, **kwargs):
        captured["safe_text"] = safe_text
        return []

    monkeypatch.setattr(submission_agent, "build_submission_task_drafts", fake_drafts)

    # 手動追加タスク: 書類名はタイトルに入り、本文は最小限。
    info = _create(title="就労証明書の提出", content="メモ")

    resp = client.post(f"/api/info/{info['id']}/investigate-deadline")
    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] == 0

    # SOT-1406: タイトルが調査対象テキストの先頭に含まれていること。
    assert "就労証明書の提出" in captured["safe_text"]
    assert captured["safe_text"].startswith("就労証明書の提出")


def test_investigate_excludes_attachment_ocr(monkeypatch):
    """SOT-1406 再オープン: 添付写真のOCR原文は調査対象テキストに含めない。"""
    captured = {}

    def fake_drafts(safe_text, detected_dates=None, **kwargs):
        captured["safe_text"] = safe_text
        return []

    monkeypatch.setattr(submission_agent, "build_submission_task_drafts", fake_drafts)

    # 添付写真のOCRが存在しても調査対象には混ざらないことを検証する。
    class _FakeAttachment:
        ocr_text = "添付写真のOCR原文 2026-12-31 提出書類"

    monkeypatch.setattr(
        SqliteInfoRepository,
        "list_attachments_for_info",
        lambda self, id: [_FakeAttachment()],
    )

    info = _create(title="就労証明書の提出", content="メモ")

    resp = client.post(f"/api/info/{info['id']}/investigate-deadline")
    assert resp.status_code == 200, resp.text

    # 添付OCRは除外、タイトル/本文は含まれること。
    assert "添付写真のOCR原文" not in captured["safe_text"]
    assert "就労証明書の提出" in captured["safe_text"]
    assert "メモ" in captured["safe_text"]
