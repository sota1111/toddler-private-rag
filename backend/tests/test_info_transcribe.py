"""SOT-1593: /info/transcribe の検証。

確認フェーズで PDF/画像の中身を登録前に確認するための、文字起こし(OCR原文)のみを
返す軽量エンドポイント。/info/extract と違い enrich(LLM生成)は行わず、埋め込みテキスト
優先→OCR フォールバック (ocr.extract_text) の結果をそのまま(PII 伏せて)返す。
"""
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

# Test database setup (mirror test_info_extract.py)
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


def test_transcribe_returns_ocr_text_for_image(monkeypatch):
    monkeypatch.setattr(info_router.ocr, "extract_text", lambda path, ct: "おしらせ\n本文です")
    response = client.post(
        "/api/info/transcribe",
        files={"file": ("photo.png", b"fake image bytes", "image/png")},
    )
    assert response.status_code == 200
    data = response.json()
    assert set(data.keys()) == {"text"}
    assert data["text"] == "おしらせ\n本文です"


def test_transcribe_accepts_pdf_and_passes_pdf_content_type(monkeypatch):
    seen = {}

    def stub(path, ct):
        seen["ct"] = ct
        return "運動会のお知らせ\n2026-05-01\n持ち物"

    monkeypatch.setattr(info_router.ocr, "extract_text", stub)
    response = client.post(
        "/api/info/transcribe",
        files={"file": ("otayori.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert response.status_code == 200
    # PDF は application/pdf 経路として OCR に渡る（埋め込みテキスト→OCR は ocr 側で判断）
    assert seen["ct"] == "application/pdf"
    assert "運動会のお知らせ" in response.json()["text"]


def test_transcribe_empty_ocr_returns_empty_text(monkeypatch):
    monkeypatch.setattr(info_router.ocr, "extract_text", lambda path, ct: "")
    response = client.post(
        "/api/info/transcribe",
        files={"file": ("blank.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert response.status_code == 200
    assert response.json()["text"] == ""


def test_transcribe_ocr_failure_returns_empty_text(monkeypatch):
    def boom(path, ct):
        raise RuntimeError("ocr engine exploded")

    monkeypatch.setattr(info_router.ocr, "extract_text", boom)
    response = client.post(
        "/api/info/transcribe",
        files={"file": ("otayori.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    # 確認表示用途なので OCR 失敗でも 200 + 空文字（登録自体は妨げない）
    assert response.status_code == 200
    assert response.json()["text"] == ""


def test_transcribe_rejects_unsupported_content_type():
    response = client.post(
        "/api/info/transcribe",
        files={"file": ("note.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400


def test_transcribe_rejects_oversize_file(monkeypatch):
    monkeypatch.setattr(info_router.ocr, "extract_text", lambda path, ct: "")
    big = b"0" * (10 * 1024 * 1024 + 1)
    response = client.post(
        "/api/info/transcribe",
        files={"file": ("big.pdf", big, "application/pdf")},
    )
    assert response.status_code == 413
