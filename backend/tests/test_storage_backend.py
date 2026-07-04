import os
from pathlib import Path
from app import storage

def test_get_storage_default(monkeypatch):
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    backend = storage.get_storage()
    assert isinstance(backend, storage.LocalStorage)
    assert backend.name == "local"

def test_get_storage_local(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    backend = storage.get_storage()
    assert isinstance(backend, storage.LocalStorage)
    assert backend.name == "local"

def test_get_storage_gcs(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "gcs")
    backend = storage.get_storage()
    assert isinstance(backend, storage.GCSStorage)
    assert backend.name == "gcs"

def test_build_object_key_local(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    filename = "test.png"
    key = storage.build_object_key(filename)
    assert key == filename

def test_build_object_key_gcs(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "gcs")
    filename = "test.png"
    key = storage.build_object_key(filename)
    assert key == f"uploads/{filename}"

def test_local_storage_path(tmp_path):
    # Mock UPLOAD_DIR
    original_upload_dir = storage.UPLOAD_DIR
    storage.UPLOAD_DIR = tmp_path
    
    try:
        backend = storage.LocalStorage()
        key = "test.txt"
        content = b"hello"
        backend.save(key, content, "text/plain")
        
        path = backend.local_path_for_ocr(key, content)
        assert path == tmp_path / key
        assert path.exists()
        assert path.read_bytes() == content
        
        backend.delete(key)
        assert not path.exists()
    finally:
        storage.UPLOAD_DIR = original_upload_dir

def test_gcs_storage_ocr_path():
    # GCS local_path_for_ocr should create a temp file
    backend = storage.GCSStorage()
    content = b"gcs content"
    path = backend.local_path_for_ocr("ignored", content)
    
    assert isinstance(path, Path)
    assert path.exists()
    assert path.read_bytes() == content
    
    # Cleanup
    os.remove(path)
