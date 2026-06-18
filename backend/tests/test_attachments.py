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
