import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models, retention, repository, storage

# --- Orphan attachment reconciliation tests (SOT-1366) ---

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


class MockGcsStorage:
    """GCS バックエンドを模した、孤児削除テスト用のストレージ。"""

    def __init__(self, blobs):
        # blobs: list of (object_key, created_at)
        self._blobs = list(blobs)
        self.deleted_keys = []

    @property
    def name(self):
        return "gcs"

    def list_blobs(self, prefix=""):
        for key, created in self._blobs:
            if key.startswith(prefix):
                yield key, created

    def delete(self, key):
        self.deleted_keys.append(key)


def _make_info_with_attachment(db, *, object_key, stored_filename="kept.png"):
    info = models.NurseryInfo(title="T", info_type="T", content="T")
    db.add(info)
    db.commit()
    att = models.Attachment(
        info_id=info.id,
        stored_filename=stored_filename,
        original_filename=stored_filename,
        mime_type="image/png",
        file_size=10,
        storage_backend="gcs",
        object_key=object_key,
        created_at=datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc),
    )
    db.add(att)
    db.commit()
    return att


def test_reconcile_deletes_only_old_orphans(test_db, monkeypatch):
    repo = repository.SqliteAttachmentRepository(test_db)
    now = datetime.datetime(2026, 6, 18, 12, 0, 0, tzinfo=datetime.timezone.utc)

    # Referenced (displayed) blob — must be kept.
    _make_info_with_attachment(test_db, object_key="uploads/kept.png")

    blobs = [
        ("uploads/kept.png", now - datetime.timedelta(days=30)),     # referenced -> keep
        ("uploads/orphan-old.png", now - datetime.timedelta(days=5)),  # orphan + old -> delete
        ("uploads/orphan-new.png", now - datetime.timedelta(hours=2)),  # orphan but too new -> keep
    ]
    mock = MockGcsStorage(blobs)
    monkeypatch.setattr(storage, "get_storage", lambda: mock)
    monkeypatch.setattr(retention, "get_orphan_grace_days", lambda: 1)

    count = retention.reconcile_orphan_attachments(repo=repo, now=now)

    assert count == 1
    assert mock.deleted_keys == ["uploads/orphan-old.png"]


def test_reconcile_disabled_when_grace_non_positive(test_db, monkeypatch):
    repo = repository.SqliteAttachmentRepository(test_db)
    now = datetime.datetime(2026, 6, 18, 12, 0, 0, tzinfo=datetime.timezone.utc)
    mock = MockGcsStorage([("uploads/orphan.png", now - datetime.timedelta(days=10))])
    monkeypatch.setattr(storage, "get_storage", lambda: mock)
    monkeypatch.setattr(retention, "get_orphan_grace_days", lambda: 0)

    count = retention.reconcile_orphan_attachments(repo=repo, now=now)

    assert count == 0
    assert mock.deleted_keys == []


def test_reconcile_skips_non_gcs_backend(test_db, monkeypatch):
    repo = repository.SqliteAttachmentRepository(test_db)
    now = datetime.datetime(2026, 6, 18, 12, 0, 0, tzinfo=datetime.timezone.utc)

    class MockLocal:
        name = "local"

        def list_blobs(self, prefix=""):
            raise AssertionError("list_blobs must not be called for local backend")

        def delete(self, key):
            raise AssertionError("delete must not be called for local backend")

    monkeypatch.setattr(storage, "get_storage", lambda: MockLocal())
    monkeypatch.setattr(retention, "get_orphan_grace_days", lambda: 1)

    count = retention.reconcile_orphan_attachments(repo=repo, now=now)

    assert count == 0


def test_reconcile_keeps_blob_referenced_by_stored_filename(test_db, monkeypatch):
    # 古いレコードで object_key が None、stored_filename だけのケースでも消さない。
    monkeypatch.setenv("STORAGE_BACKEND", "gcs")  # build_object_key が uploads/ を付与
    repo = repository.SqliteAttachmentRepository(test_db)
    now = datetime.datetime(2026, 6, 18, 12, 0, 0, tzinfo=datetime.timezone.utc)
    _make_info_with_attachment(test_db, object_key=None, stored_filename="legacy.png")

    blobs = [("uploads/legacy.png", now - datetime.timedelta(days=10))]
    mock = MockGcsStorage(blobs)
    monkeypatch.setattr(storage, "get_storage", lambda: mock)
    monkeypatch.setattr(retention, "get_orphan_grace_days", lambda: 1)

    count = retention.reconcile_orphan_attachments(repo=repo, now=now)

    assert count == 0
    assert mock.deleted_keys == []
