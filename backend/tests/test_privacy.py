import pytest
import datetime
from app.privacy import redact_pii
from app import models, retention, repository, storage
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# --- PII Redaction Tests ---

def test_redact_pii_email():
    text = "My email is test@example.com. Please contact me."
    redacted = redact_pii(text)
    assert "test@example.com" not in redacted
    assert "[REDACTED_EMAIL]" in redacted

def test_redact_pii_phone():
    # Various Japanese phone formats
    cases = [
        "090-1234-5678",
        "03-1234-5678",
        "0120-123-456",
        "09012345678",
        "0312345678"
    ]
    for case in cases:
        redacted = redact_pii(f"Contact {case} now.")
        assert case not in redacted
        assert "[REDACTED_PHONE]" in redacted

def test_redact_pii_my_number():
    case1 = "1234-5678-9012"
    case2 = "123456789012"
    assert "[REDACTED_ID]" in redact_pii(case1)
    assert "[REDACTED_ID]" in redact_pii(case2)

def test_redact_pii_bank_account():
    case1 = "口座番号は1234567です。"
    case2 = "12345678" # Standalone 8 digits
    
    redacted1 = redact_pii(case1)
    assert "1234567" not in redacted1
    assert "[REDACTED_ACCOUNT]" in redacted1
    
    redacted2 = redact_pii(case2)
    assert "12345678" not in redacted2
    assert "[REDACTED_ACCOUNT]" in redacted2

def test_redact_pii_not_matching_dates():
    # Date should NOT be redacted as phone or bank account
    date_str = "2026-06-18"
    redacted = redact_pii(date_str)
    assert date_str in redacted
    assert "[REDACTED]" not in redacted

def test_redact_pii_empty():
    assert redact_pii("") == ""
    assert redact_pii(None) == ""

# --- Retention Policy Tests ---

# Setup test DB
SQLALCHEMY_DATABASE_URL = "sqlite://"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture
def test_db():
    models.Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    yield db
    db.close()
    models.Base.metadata.drop_all(bind=engine)

def test_purge_expired_attachments(test_db, monkeypatch):
    # 1. Setup repository and data
    repo = repository.SqliteAttachmentRepository(test_db)
    
    # Mock storage.get_storage().delete
    class MockStorage:
        def __init__(self):
            self.deleted_keys = []
        def delete(self, key):
            self.deleted_keys.append(key)
    
    mock_storage = MockStorage()
    monkeypatch.setattr(storage, "get_storage", lambda: mock_storage)
    
    # Mock get_retention_days to 30
    monkeypatch.setattr(retention, "get_retention_days", lambda: 30)
    
    # Current time
    now = datetime.datetime(2026, 6, 18, 12, 0, 0, tzinfo=datetime.timezone.utc)
    
    # Create NurseryInfo first
    info = models.NurseryInfo(title="Test", info_type="Test", content="Test")
    test_db.add(info)
    test_db.commit()
    
    # Create attachments
    # Old one (31 days ago)
    old_date = now - datetime.timedelta(days=31)
    old_att = models.Attachment(
        info_id=info.id,
        stored_filename="old.png",
        original_filename="old.png",
        mime_type="image/png",
        file_size=100,
        storage_backend="local",
        object_key="old.png",
        created_at=old_date
    )
    
    # New one (1 day ago)
    new_date = now - datetime.timedelta(days=1)
    new_att = models.Attachment(
        info_id=info.id,
        stored_filename="new.png",
        original_filename="new.png",
        mime_type="image/png",
        file_size=100,
        storage_backend="local",
        object_key="new.png",
        created_at=new_date
    )
    
    test_db.add_all([old_att, new_att])
    test_db.commit()
    
    # 2. Run purge
    count = retention.purge_expired_attachments(repo=repo, now=now)
    
    # 3. Verify
    assert count == 1
    assert "old.png" in mock_storage.deleted_keys
    assert "new.png" not in mock_storage.deleted_keys
    
    # Check DB
    remaining = test_db.query(models.Attachment).all()
    assert len(remaining) == 1
    assert remaining[0].stored_filename == "new.png"

def test_purge_retention_disabled(test_db, monkeypatch):
    repo = repository.SqliteAttachmentRepository(test_db)
    monkeypatch.setattr(retention, "get_retention_days", lambda: 0)
    
    now = datetime.datetime(2026, 6, 18, 12, 0, 0, tzinfo=datetime.timezone.utc)
    
    # Create old attachment
    info = models.NurseryInfo(title="Test", info_type="Test", content="Test")
    test_db.add(info)
    test_db.commit()
    
    old_att = models.Attachment(
        info_id=info.id,
        stored_filename="old.png",
        original_filename="old.png",
        mime_type="image/png",
        file_size=100,
        storage_backend="local",
        object_key="old.png",
        created_at=now - datetime.timedelta(days=100)
    )
    test_db.add(old_att)
    test_db.commit()
    
    count = retention.purge_expired_attachments(repo=repo, now=now)
    assert count == 0
    
    remaining = test_db.query(models.Attachment).all()
    assert len(remaining) == 1
