import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.main import app
from tests._images import PNG_BYTES
from app.database import Base, get_db
from app import models, database
from pathlib import Path
import os
import shutil

# Test database setup (in-memory for consistency and speed)
SQLALCHEMY_DATABASE_URL = "sqlite://"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture
def db(monkeypatch):
    Base.metadata.create_all(bind=engine)
    # Patch SessionLocal so process_ocr uses the same in-memory DB
    monkeypatch.setattr(database, "SessionLocal", TestingSessionLocal)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)

@pytest.fixture
def client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass
    
    from app.routers.auth import get_current_user
    
    # Store original overrides
    original_overrides = app.dependency_overrides.copy()
    
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: "test_user"
    
    yield TestClient(app)
    
    # Restore original overrides
    app.dependency_overrides = original_overrides

@pytest.fixture(autouse=True)
def setup_teardown_uploads(tmp_path):
    import app.storage
    original_dir = app.storage.UPLOAD_DIR
    test_upload_dir = tmp_path / "ocr_uploads"
    test_upload_dir.mkdir(parents=True, exist_ok=True)
    app.storage.UPLOAD_DIR = test_upload_dir
    yield
    app.storage.UPLOAD_DIR = original_dir

def test_upload_attachment_graceful_ocr_failure(client, db):
    # Create NurseryInfo
    info_resp = client.post("/api/info/", json={
        "title": "Test Info",
        "info_type": "お知らせ",
        "content": "Test Content"
    })
    assert info_resp.status_code == 200
    info_id = info_resp.json()["id"]

    # Upload a tiny dummy file that is not OCRable
    dummy_file = Path("dummy.png")
    dummy_file.write_bytes(PNG_BYTES)
    
    try:
        with open(dummy_file, "rb") as f:
            resp = client.post(
                f"/api/info/{info_id}/attachments",
                files={"file": ("dummy.png", f, "image/png")}
            )
    finally:
        if dummy_file.exists():
            dummy_file.unlink()
    
    assert resp.status_code == 200
    data = resp.json()
    assert data["original_filename"] == "dummy.png"
    
    # Verify ocr_text is stored (likely "" for this dummy file)
    att = db.query(models.Attachment).filter(models.Attachment.id == data["id"]).first()
    assert att is not None
    assert isinstance(att.ocr_text, str)

def test_search_by_ocr_text(client, db):
    # Create NurseryInfo
    info_resp = client.post("/api/info/", json={
        "title": "Search Target",
        "info_type": "お知らせ",
        "content": "Regular content"
    })
    assert info_resp.status_code == 200
    info_id = info_resp.json()["id"]

    # Manually add attachment with specific ocr_text
    unique_keyword = "SECRET_KEYWORD_123"
    db_attachment = models.Attachment(
        info_id=info_id,
        stored_filename="fake.png",
        original_filename="fake.png",
        mime_type="image/png",
        file_size=100,
        ocr_text=f"Some text with {unique_keyword} inside it"
    )
    db.add(db_attachment)
    db.commit()

    # Search for the keyword
    search_resp = client.get(f"/api/info/?q={unique_keyword}")
    assert search_resp.status_code == 200
    results = search_resp.json()
    assert len(results) == 1
    assert results[0]["id"] == info_id
    assert results[0]["title"] == "Search Target"

    # Search for non-existent keyword
    search_resp = client.get("/api/info/?q=NON_EXISTENT")
    assert search_resp.status_code == 200
    assert len(search_resp.json()) == 0

def test_search_regression_existing_fields(client, db):
    # Create NurseryInfo
    client.post("/api/info/", json={
        "title": "Title Match",
        "info_type": "お知らせ",
        "content": "content",
        "tags": "tag1"
    })
    
    # Search by title
    resp = client.get("/api/info/?q=Title")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    
    # Search by tag
    resp = client.get("/api/info/?q=tag1")
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    # Search by content
    resp = client.get("/api/info/?q=content")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
