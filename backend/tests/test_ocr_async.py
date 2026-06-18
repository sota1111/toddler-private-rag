import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import ocr, models, database
from app.database import Base, get_db
from app.routers.auth import get_current_user
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Setup test DB
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
def setup_db(monkeypatch):
    Base.metadata.create_all(bind=engine)
    # Patch SessionLocal so process_ocr uses the same in-memory DB
    monkeypatch.setattr(database, "SessionLocal", TestingSessionLocal)
    
    # Dependency overrides
    monkeypatch.setitem(app.dependency_overrides, get_db, override_get_db)
    monkeypatch.setitem(app.dependency_overrides, get_current_user, override_get_current_user)
    
    yield
    Base.metadata.drop_all(bind=engine)

client = TestClient(app)

def test_upload_attachment_ocr_async(monkeypatch):
    # 1. Mock OCR to return deterministic text
    mock_text = "EXTRACTED OCR TEXT"
    monkeypatch.setattr(ocr, "extract_text", lambda *args, **kwargs: mock_text)

    # 2. Create NurseryInfo
    response = client.post(
        "/api/info/",
        json={"title": "Test", "info_type": "行事", "content": "Test"}
    )
    assert response.status_code == 200
    info_id = response.json()["id"]

    # 3. Upload file
    response = client.post(
        f"/api/info/{info_id}/attachments",
        files={"file": ("test.png", b"fake image", "image/png")}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ocr_status"] == "pending"
    att_id = data["id"]

    # 4. In TestClient, background tasks run after the response is returned.
    # We can now check the database to see if OCR was processed.
    db = TestingSessionLocal()
    att = db.query(models.Attachment).filter(models.Attachment.id == att_id).first()
    assert att.ocr_status == "done"
    assert att.ocr_text == mock_text
    db.close()

def test_upload_attachment_ocr_failed(monkeypatch):
    # 1. Mock OCR to raise exception
    def mock_extract_failed(*args, **kwargs):
        raise Exception("OCR Error")
    monkeypatch.setattr(ocr, "extract_text", mock_extract_failed)

    # 2. Create NurseryInfo
    response = client.post(
        "/api/info/",
        json={"title": "Test", "info_type": "行事", "content": "Test"}
    )
    assert response.status_code == 200
    info_id = response.json()["id"]

    # 3. Upload file
    response = client.post(
        f"/api/info/{info_id}/attachments",
        files={"file": ("test.png", b"fake image", "image/png")}
    )
    assert response.status_code == 200
    att_id = response.json()["id"]

    # 4. Check status is failed
    db = TestingSessionLocal()
    att = db.query(models.Attachment).filter(models.Attachment.id == att_id).first()
    assert att.ocr_status == "failed"
    assert att.ocr_text is None
    db.close()
