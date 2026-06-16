import os
import uuid
from pathlib import Path

# Base directory for the backend (where main.py resides)
BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "data" / "uploads"

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
