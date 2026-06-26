import os
import uuid
import logging
from pathlib import Path
from abc import ABC, abstractmethod
import tempfile
from typing import Optional

logger = logging.getLogger(__name__)

# Base directory for the backend (where main.py resides)
BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "data" / "uploads"

# Module-level functions for backward compatibility
def ensure_upload_dir():
    os.makedirs(UPLOAD_DIR, exist_ok=True)

def generate_stored_filename(original_filename: str) -> str:
    ext = os.path.splitext(original_filename)[1]
    return f"{uuid.uuid4().hex}{ext}"

def get_file_path(stored_filename: str) -> Path:
    return UPLOAD_DIR / stored_filename

def delete_file(stored_filename: str):
    path = get_file_path(stored_filename)
    if path.exists():
        os.remove(path)

class StorageBackend(ABC):
    @abstractmethod
    def save(self, object_key: str, content: bytes, content_type: str) -> None:
        pass

    @abstractmethod
    def delete(self, object_key: str) -> None:
        pass

    @abstractmethod
    def local_path_for_ocr(self, object_key: str, content: bytes) -> Path:
        """Returns a local path where the file content can be read for OCR."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        pass

class LocalStorage(StorageBackend):
    def save(self, object_key: str, content: bytes, content_type: str) -> None:
        # Note: We use the module-level functions to allow runtime overrides (like in tests)
        ensure_upload_dir()
        path = get_file_path(object_key)
        with open(path, "wb") as f:
            f.write(content)

    def delete(self, object_key: str) -> None:
        delete_file(object_key)

    def local_path_for_ocr(self, object_key: str, content: bytes) -> Path:
        return get_file_path(object_key)

    @property
    def name(self) -> str:
        return "local"

class GCSStorage(StorageBackend):
    def __init__(self):
        self.bucket_name = os.getenv("GCS_BUCKET_NAME")
        self.project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from google.cloud import storage as gcs
            self._client = gcs.Client(project=self.project_id)
        return self._client

    def save(self, object_key: str, content: bytes, content_type: str) -> None:
        bucket = self.client.bucket(self.bucket_name)
        blob = bucket.blob(object_key)
        blob.upload_from_string(content, content_type=content_type)

    def delete(self, object_key: str) -> None:
        try:
            bucket = self.client.bucket(self.bucket_name)
            blob = bucket.blob(object_key)
            blob.delete()
        except Exception:
            # Ignore if file doesn't exist or other errors during delete
            pass

    def local_path_for_ocr(self, object_key: str, content: bytes) -> Path:
        # For GCS, we create a temporary file for OCR
        fd, path = tempfile.mkstemp()
        with os.fdopen(fd, 'wb') as tmp:
            tmp.write(content)
        return Path(path)

    def read(self, object_key: str) -> bytes:
        bucket = self.client.bucket(self.bucket_name)
        blob = bucket.blob(object_key)
        return blob.download_as_bytes()

    def generate_signed_url(self, object_key: str, content_type: Optional[str] = None) -> str:
        from datetime import timedelta
        bucket = self.client.bucket(self.bucket_name)
        blob = bucket.blob(object_key)
        
        url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(minutes=15),
            method="GET",
            response_type=content_type
        )
        return url

    @property
    def name(self) -> str:
        return "gcs"

def get_storage() -> StorageBackend:
    backend_type = os.getenv("STORAGE_BACKEND", "local").lower()
    if backend_type == "gcs":
        return GCSStorage()
    return LocalStorage()

def build_object_key(stored_filename: str) -> str:
    backend_type = os.getenv("STORAGE_BACKEND", "local").lower()
    if backend_type == "gcs":
        return f"uploads/{stored_filename}"
    return stored_filename
