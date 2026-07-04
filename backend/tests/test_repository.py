import pytest
import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.repository import (
    _tags_str_to_array, _tags_array_to_str, _to_date, _from_date,
    _matches_query, FirestoreNurseryInfo, FirestoreAttachment,
    get_database_type, get_info_repository, get_attachment_repository,
    SqliteInfoRepository, SqliteAttachmentRepository
)
from app import schemas

# Test pure functions for Firestore transformation
def test_tags_conversion():
    assert _tags_str_to_array("tag1, tag2") == ["tag1", "tag2"]
    assert _tags_str_to_array(None) == []
    assert _tags_str_to_array("") == []
    
    assert _tags_array_to_str(["tag1", "tag2"]) == "tag1,tag2"
    assert _tags_array_to_str([]) is None
    assert _tags_array_to_str(None) is None

def test_date_conversion():
    d = datetime.date(2023, 10, 27)
    assert _from_date(d) == "2023-10-27"
    assert _to_date("2023-10-27") == d
    assert _from_date(None) is None
    assert _to_date(None) is None
    assert _to_date("invalid") is None

def test_matches_query():
    info = FirestoreNurseryInfo(
        id="1", title="Title A", info_type="Type X", content="Content here",
        date=None, event_date=None, due_date=None, items=None,
        status="未対応", priority="普通", tags="tag1,tag2", memo=None,
        created_at=datetime.datetime.now(), updated_at=datetime.datetime.now(),
        attachments=[
            FirestoreAttachment(
                id="a1", info_id="1", stored_filename="f1.png",
                original_filename="o1.png", mime_type="image/png",
                file_size=100, storage_backend="local",
                object_key=None, ocr_text="Found this word",
                ocr_status="done",
                created_at=datetime.datetime.now()
            )
        ]
    )
    
    # Matches
    assert _matches_query(info, q="title", tag=None)
    assert _matches_query(info, q="content", tag=None)
    assert _matches_query(info, q="tag1", tag=None)
    assert _matches_query(info, q="found", tag=None) # OCR search
    assert _matches_query(info, q=None, tag="tag1")
    
    # Non-matches
    assert not _matches_query(info, q="other", tag=None)
    assert not _matches_query(info, q=None, tag="tag3")

# Test Factory
def test_get_database_type(monkeypatch):
    monkeypatch.setenv("DATABASE_TYPE", "firestore")
    assert get_database_type() == "firestore"
    
    monkeypatch.setenv("DATABASE_TYPE", "sqlite")
    assert get_database_type() == "sqlite"
    
    monkeypatch.delenv("DATABASE_TYPE", raising=False)
    assert get_database_type() == "sqlite"

def test_repository_factory(monkeypatch):
    # We mock get_db dependency for the factory test
    class MockSession:
        pass
    
    monkeypatch.setenv("DATABASE_TYPE", "sqlite")
    info_repo = get_info_repository(MockSession())
    assert isinstance(info_repo, SqliteInfoRepository)
    
    att_repo = get_attachment_repository(MockSession())
    assert isinstance(att_repo, SqliteAttachmentRepository)

# Test SQLite implementation (Basic CRUD)
@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()

def test_sqlite_info_crud(db_session):
    repo = SqliteInfoRepository(db_session)
    
    # Create
    info_data = schemas.NurseryInfoCreate(
        title="Test Info",
        info_type="資料",
        content="Test Content",
        tags="tag1,tag2"
    )
    created = repo.create(info_data)
    assert created.id is not None
    assert created.title == "Test Info"
    
    # Get
    fetched = repo.get(created.id)
    assert fetched.title == "Test Info"
    
    # List
    results = repo.list(q="Test")
    assert len(results) == 1
    
    # Update
    update_data = schemas.NurseryInfoUpdate(status="完了")
    updated = repo.update(created.id, update_data)
    assert updated.status == "完了"
    
    # Delete
    assert repo.delete(created.id)
    assert repo.get(created.id) is None
