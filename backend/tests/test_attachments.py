import pytest
import os
import shutil
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from pathlib import Path

from app.main import app
from app.database import Base, get_db
from app.routers.auth import get_current_user
from app import storage, models, database

# Test database setup
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
    # Setup
    Base.metadata.create_all(bind=engine)
    # Patch SessionLocal so process_ocr uses the same in-memory DB
    monkeypatch.setattr(database, "SessionLocal", TestingSessionLocal)
    
    # Dependency overrides
    monkeypatch.setitem(app.dependency_overrides, get_db, override_get_db)
    monkeypatch.setitem(app.dependency_overrides, get_current_user, override_get_current_user)
    
    test_upload_dir = tmp_path / "uploads"
    os.makedirs(test_upload_dir, exist_ok=True)
    
    # Override storage directory
    original_upload_dir = storage.UPLOAD_DIR
    storage.UPLOAD_DIR = test_upload_dir
    
    yield
    
    # Teardown
    Base.metadata.drop_all(bind=engine)
    if test_upload_dir.exists():
        shutil.rmtree(test_upload_dir)
    storage.UPLOAD_DIR = original_upload_dir

client = TestClient(app)

def test_upload_and_get_attachment():
    # 1. Create a NurseryInfo
    response = client.post(
        "/api/info/",
        json={
            "title": "Test Info",
            "info_type": "行事",
            "content": "Test content"
        }
    )
    assert response.status_code == 200
    info_id = response.json()["id"]

    # 2. Upload a file
    file_content = b"fake image content"
    response = client.post(
        f"/api/info/{info_id}/attachments",
        files={"file": ("test.png", file_content, "image/png")}
    )
    assert response.status_code == 200
    att_data = response.json()
    assert att_data["original_filename"] == "test.png"
    assert att_data["mime_type"] == "image/png"
    assert "stored_filename" not in att_data
    assert "ocr_text" not in att_data
    att_id = att_data["id"]

    # 3. Get info and check attachments
    response = client.get(f"/api/info/{info_id}")
    assert response.status_code == 200
    assert len(response.json()["attachments"]) == 1
    assert response.json()["attachments"][0]["id"] == att_id

    # 4. Download file
    response = client.get(f"/api/attachments/{att_id}/file")
    assert response.status_code == 200
    assert response.content == file_content
    assert response.headers["content-type"] == "image/png"
    # SOT-1275: served inline so clicking an image opens (not downloads) in the browser
    assert response.headers["content-disposition"].startswith("inline")

def test_get_attachment_file_gcs_streams_inline(monkeypatch):
    """SOT-1282: GCS-backed attachments must be streamed inline by the backend.

    On Cloud Run the default compute service-account credentials have no private
    key, so generating a V4 signed URL raises and the endpoint 500s -> broken
    image. The GCS branch must instead download the bytes and serve them inline.
    """
    # 1. Create info + upload an image (stored locally by default in tests)
    info_id = client.post(
        "/api/info/",
        json={"title": "T", "info_type": "行事", "content": "c"},
    ).json()["id"]
    img_bytes = b"\xff\xd8\xff fake-jpeg-bytes \xff\xd9"
    att_id = client.post(
        f"/api/info/{info_id}/attachments",
        files={"file": ("photo.jpg", img_bytes, "image/jpeg")},
    ).json()["id"]

    # 2. Mark the stored attachment as GCS-backed
    db = TestingSessionLocal()
    att = db.query(models.Attachment).filter(models.Attachment.id == att_id).first()
    att.storage_backend = "gcs"
    att.object_key = "uploads/photo.jpg"
    db.commit()
    db.close()

    # 3. Fake GCS storage that returns bytes without touching real GCS / signing
    fake = storage.GCSStorage()
    monkeypatch.setattr(fake, "read", lambda object_key: img_bytes)
    monkeypatch.setattr(storage, "get_storage", lambda: fake)

    resp = client.get(f"/api/attachments/{att_id}/file")
    assert resp.status_code == 200
    assert resp.content == img_bytes
    assert resp.headers["content-type"] == "image/jpeg"
    assert resp.headers["content-disposition"].startswith("inline")


def test_upload_unsupported_type():
    # 1. Create a NurseryInfo
    response = client.post(
        "/api/info/",
        json={"title": "Test", "info_type": "行事", "content": "Test"}
    )
    info_id = response.json()["id"]

    # 2. Upload text file
    response = client.post(
        f"/api/info/{info_id}/attachments",
        files={"file": ("test.txt", b"hello", "text/plain")}
    )
    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]

def test_upload_oversized_file():
    # 1. Create a NurseryInfo
    response = client.post(
        "/api/info/",
        json={"title": "Test", "info_type": "行事", "content": "Test"}
    )
    info_id = response.json()["id"]

    # 2. Upload large file (11MB)
    large_content = b"a" * (11 * 1024 * 1024)
    response = client.post(
        f"/api/info/{info_id}/attachments",
        files={"file": ("large.png", large_content, "image/png")}
    )
    assert response.status_code == 413

def test_upload_allows_any_image_content_type():
    response = client.post(
        "/api/info/",
        json={"title": "Test", "info_type": "行事", "content": "Test"}
    )
    info_id = response.json()["id"]

    response = client.post(
        f"/api/info/{info_id}/attachments",
        files={"file": ("test.webp", b"image", "image/webp")}
    )
    assert response.status_code == 200

def test_delete_attachment():
    # 1. Create info and upload
    response = client.post("/api/info/", json={"title": "T", "info_type": "行事", "content": "C"})
    info_id = response.json()["id"]
    response = client.post(
        f"/api/info/{info_id}/attachments",
        files={"file": ("test.png", b"data", "image/png")}
    )
    att_id = response.json()["id"]
    stored_filename = models.Attachment.stored_filename
    
    # Check file exists
    db = next(override_get_db())
    att = db.query(models.Attachment).filter(models.Attachment.id == att_id).first()
    file_path = storage.get_file_path(att.stored_filename)
    assert file_path.exists()

    # 2. Delete attachment
    response = client.delete(f"/api/attachments/{att_id}")
    assert response.status_code == 200
    
    # 3. Verify deleted
    assert not file_path.exists()
    response = client.get(f"/api/attachments/{att_id}/file")
    assert response.status_code == 404

def test_delete_info_removes_attachments():
    # 1. Create info and upload
    response = client.post("/api/info/", json={"title": "T", "info_type": "行事", "content": "C"})
    info_id = response.json()["id"]
    response = client.post(
        f"/api/info/{info_id}/attachments",
        files={"file": ("test.png", b"data", "image/png")}
    )
    att_id = response.json()["id"]
    db = next(override_get_db())
    att = db.query(models.Attachment).filter(models.Attachment.id == att_id).first()
    file_path = storage.get_file_path(att.stored_filename)
    
    # 2. Delete info
    response = client.delete(f"/api/info/{info_id}")
    assert response.status_code == 200
    
    # 3. Verify attachment and file are gone
    assert not file_path.exists()
    db = next(override_get_db())
    assert db.query(models.Attachment).filter(models.Attachment.id == att_id).first() is None

def test_create_info_without_file():
    response = client.post(
        "/api/info/",
        json={
            "title": "Test Info",
            "info_type": "行事",
            "content": "Test content"
        }
    )
    assert response.status_code == 200
    assert response.json()["attachments"] == []


def test_list_include_attachments_param():
    """SOT-1240: include_attachments=false でタイトル一覧の添付取得(N+1)をスキップする。"""
    # 本登録 info + 添付を用意
    info_id = client.post(
        "/api/info/", json={"title": "with-att", "info_type": "行事", "content": "C"}
    ).json()["id"]
    client.post(
        f"/api/info/{info_id}/attachments",
        files={"file": ("test.png", b"data", "image/png")},
    )

    # 仮登録(draft) は一覧に出ない（軽量モードでも除外維持）
    client.post(
        "/api/info/",
        json={"title": "draft-x", "info_type": "行事", "content": "C",
              "registration_state": "draft"},
    )

    # 既定（include_attachments 省略）: 添付が従来どおり返る
    default_items = client.get("/api/info/").json()
    target = next(i for i in default_items if i["id"] == info_id)
    assert len(target["attachments"]) == 1
    assert "draft-x" not in {i["title"] for i in default_items}

    # 軽量モード: 同じ本登録データが返るが添付は空配列
    light_items = client.get("/api/info/", params={"include_attachments": "false"}).json()
    light_target = next(i for i in light_items if i["id"] == info_id)
    assert light_target["title"] == "with-att"
    assert light_target["attachments"] == []
    assert "draft-x" not in {i["title"] for i in light_items}


# --- SOT-1325: 文字起こし(OCR原文)を設定言語で表示するための翻訳・エンドポイント ---

def test_translate_text_fallbacks(monkeypatch):
    from app import extraction, ai_client

    # 空テキストはそのまま空を返す（LLM を呼ばない）
    assert extraction.translate_text("", "en") == ""
    assert extraction.translate_text("   ", "ja") == "   "

    # LLM 不可のときは原文をそのまま返す（決して例外を投げない）
    monkeypatch.setattr(ai_client, "gemini_available", lambda: False)
    assert extraction.translate_text("今月の給食は和食中心です。", "en") == "今月の給食は和食中心です。"


def test_get_attachment_transcription(monkeypatch):
    from app import extraction

    # 翻訳はモック化して内容を決定的にする（言語のみ変換のイメージ）
    monkeypatch.setattr(
        extraction, "translate_text", lambda text, language: f"[{language}] {text}"
    )

    info_id = client.post(
        "/api/info/",
        json={"title": "T", "info_type": "行事", "content": "c"},
    ).json()["id"]
    att_id = client.post(
        f"/api/info/{info_id}/attachments",
        files={"file": ("photo.png", b"img", "image/png")},
    ).json()["id"]

    # OCR 原文を直接保存（process_ocr 相当）
    db = TestingSessionLocal()
    att = db.query(models.Attachment).filter(models.Attachment.id == att_id).first()
    att.ocr_text = "今月の給食は和食中心です。"
    att.ocr_status = "done"
    db.commit()
    db.close()

    resp = client.get(f"/api/attachments/{att_id}/transcription", params={"language": "en"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"] == "[en] 今月の給食は和食中心です。"
    assert body["ocr_status"] == "done"
    assert body["language"] == "en"

    # 不正な言語は ja にフォールバックする
    resp_bad = client.get(f"/api/attachments/{att_id}/transcription", params={"language": "fr"})
    assert resp_bad.json()["language"] == "ja"


def test_transcription_translation_is_cached(monkeypatch):
    """SOT-1330: 同一(添付, 言語)への複数回アクセスでも翻訳は一度きり（読み込みの度に翻訳しない）。"""
    from app import extraction

    calls = {"n": 0}

    def fake_translate(text, language):
        calls["n"] += 1
        return f"[{language}] {text}"

    monkeypatch.setattr(extraction, "translate_text", fake_translate)

    info_id = client.post(
        "/api/info/",
        json={"title": "T", "info_type": "行事", "content": "c"},
    ).json()["id"]
    att_id = client.post(
        f"/api/info/{info_id}/attachments",
        files={"file": ("photo.png", b"img", "image/png")},
    ).json()["id"]

    db = TestingSessionLocal()
    att = db.query(models.Attachment).filter(models.Attachment.id == att_id).first()
    att.ocr_text = "今月の給食は和食中心です。"
    att.ocr_status = "done"
    db.commit()
    db.close()

    r1 = client.get(f"/api/attachments/{att_id}/transcription", params={"language": "en"})
    r2 = client.get(f"/api/attachments/{att_id}/transcription", params={"language": "en"})
    assert r1.json()["text"] == "[en] 今月の給食は和食中心です。"
    assert r2.json()["text"] == "[en] 今月の給食は和食中心です。"
    # 2回目はキャッシュ再利用 → 翻訳呼び出しは1回のみ
    assert calls["n"] == 1


def test_get_attachment_transcription_empty_when_no_ocr():
    info_id = client.post(
        "/api/info/",
        json={"title": "T", "info_type": "行事", "content": "c"},
    ).json()["id"]
    att_id = client.post(
        f"/api/info/{info_id}/attachments",
        files={"file": ("photo.png", b"img", "image/png")},
    ).json()["id"]

    resp = client.get(f"/api/attachments/{att_id}/transcription")
    assert resp.status_code == 200
    assert resp.json()["text"] == ""


def test_get_attachment_transcription_404():
    resp = client.get("/api/attachments/999999/transcription")
    assert resp.status_code == 404
