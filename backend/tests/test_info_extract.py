import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.routers.auth import get_current_user
from app import storage, database
from app.routers import info as info_router

# Test database setup (mirror test_attachments.py)
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

    original_upload_dir = storage.UPLOAD_DIR
    storage.UPLOAD_DIR = tmp_path / "uploads"
    (tmp_path / "uploads").mkdir(parents=True, exist_ok=True)

    yield

    Base.metadata.drop_all(bind=engine)
    storage.UPLOAD_DIR = original_upload_dir


client = TestClient(app)

REQUIRED_KEYS = {
    "title", "info_type", "content", "items", "date",
    "raw_text", "detected_dates", "detected_items",
}
INFO_TYPES = ["資料", "掲示", "行事", "持ち物", "提出物", "お知らせ", "給食", "休園変更"]


def test_extract_returns_valid_draft(monkeypatch):
    # OCR エンジンに依存しないよう extract_text をスタブ化
    monkeypatch.setattr(info_router.ocr, "extract_text", lambda path, ct: "おしらせ\n本文です")
    response = client.post(
        "/api/info/extract",
        files={"file": ("photo.png", b"fake image bytes", "image/png")},
    )
    assert response.status_code == 200
    data = response.json()
    assert REQUIRED_KEYS.issubset(data.keys())
    assert isinstance(data["title"], str) and data["title"]
    assert data["info_type"] in INFO_TYPES
    assert isinstance(data["content"], str)
    assert isinstance(data["detected_dates"], list)
    assert isinstance(data["detected_items"], list)


def test_extract_parses_date_and_items(monkeypatch):
    text = "運動会のお知らせ\n2026-05-01\n持ち物\n・体操着\n・水筒"
    monkeypatch.setattr(info_router.ocr, "extract_text", lambda path, ct: text)
    response = client.post(
        "/api/info/extract",
        files={"file": ("photo.jpg", b"x", "image/jpeg")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["date"] == "2026-05-01"
    assert "2026-05-01" in data["detected_dates"]
    assert data["items"] is not None
    assert "・体操着" in data["items"]
    # 持ち物が検出されたので info_type は "持ち物"
    assert data["info_type"] == "持ち物"


def test_extract_rejects_unsupported_content_type():
    response = client.post(
        "/api/info/extract",
        files={"file": ("note.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400


def test_extract_rejects_oversize_file(monkeypatch):
    monkeypatch.setattr(info_router.ocr, "extract_text", lambda path, ct: "")
    big = b"0" * (10 * 1024 * 1024 + 1)
    response = client.post(
        "/api/info/extract",
        files={"file": ("big.png", big, "image/png")},
    )
    assert response.status_code == 413


def test_extract_content_is_plain_without_category_section(monkeypatch):
    # SOT-1329: 文字起こし後のカテゴリ分類(【提出物】等の見出し付き本文)は廃止する。
    # content は分類せずプレーンな文字起こし本文のままにする。
    text = "運動会のお知らせ\n\n\n持ち物\n・水筒\n・タオル\n注意: 車での来園は禁止です。"
    monkeypatch.setattr(info_router.ocr, "extract_text", lambda path, ct: text)
    response = client.post(
        "/api/info/extract",
        files={"file": ("photo.png", b"x", "image/png")},
    )
    assert response.status_code == 200
    data = response.json()
    # content にカテゴリ見出し(【...】)は付かない
    assert "【" not in data["content"]
    assert "】" not in data["content"]
    # 本文の中身はプレーンに保持されている
    assert "持ち物" in data["content"]
    assert "水筒" in data["content"]
    # raw_text は生の文字起こしを保持している
    assert "持ち物" in data["raw_text"]


def test_extract_empty_ocr_returns_fallback(monkeypatch):
    monkeypatch.setattr(info_router.ocr, "extract_text", lambda path, ct: "")
    response = client.post(
        "/api/info/extract",
        files={"file": ("blank.png", b"x", "image/png")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "写真から登録"
    assert data["content"] == ""
    assert data["date"] is None
    assert data["items"] is None
    assert data["detected_dates"] == []
    assert data["detected_items"] == []
