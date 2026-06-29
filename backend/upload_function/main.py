"""SOT-1359: gen2 Cloud Function for photo upload (replaces the SOT-1322 Cloud Run upload service).

This is a self-contained, slim functions-framework HTTP function. It deliberately does NOT import
``backend/app`` (which transitively pulls heavy OCR/AI deps) so the function stays small and
cold-starts fast. It reproduces the exact public contract of the old ``routers/upload.py``:

  POST /api/info/{info_id}/attachments
    - multipart form field ``file`` (required)
    - optional query ``language`` (default "ja")
    - auth via ``auth_token`` cookie (HMAC of the app name with AUTH_SECRET)
    - persists the blob to GCS, creates a pending Attachment doc in Firestore, then best-effort
      dispatches OCR/enrich to the heavy AI worker, and returns the attachment JSON.

The heavy OCR/enrich work still runs on the existing backend ("AI worker"), triggered over HTTP.
"""
import contextlib
import datetime
import hashlib
import hmac
import logging
import os
import re
import time
import uuid

import functions_framework
from flask import Response, jsonify, request

logger = logging.getLogger(__name__)


# --- Timing (SOT-1374) ---
# 軽量アップロード関数は backend/app(重依存)を読み込まない設計のため、共有 timing.py は使えない。
# 同じ `[timing] stage=<name> elapsed_ms=<float> <k=v ...>` 形式をインラインで再現する。
def _fmt_timing_fields(fields: dict) -> str:
    if not fields:
        return ""
    return " " + " ".join(f"{k}={v}" for k, v in fields.items() if v is not None)


@contextlib.contextmanager
def _time_block(stage: str, **fields):
    start = time.perf_counter()
    status = "ok"
    try:
        yield fields
    except Exception:
        status = "error"
        raise
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        merged = {**fields, "status": status} if status == "error" else fields
        logger.info(
            "[timing] stage=%s elapsed_ms=%.1f%s",
            stage,
            elapsed_ms,
            _fmt_timing_fields(merged),
        )

# --- Constants (mirrors backend/app) ---
_APP_NAME = "toddler-private-rag"
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
_PATH_RE = re.compile(r"^/api/info/([^/]+)/attachments/?$")

# --- Lazy singletons (cold-start friendly) ---
_storage_client = None
_firestore_client = None


def _get_storage_client():
    global _storage_client
    if _storage_client is None:
        from google.cloud import storage as gcs

        _storage_client = gcs.Client(project=os.getenv("GOOGLE_CLOUD_PROJECT"))
    return _storage_client


def _get_firestore_client():
    global _firestore_client
    if _firestore_client is None:
        from google.cloud import firestore

        _firestore_client = firestore.Client(
            project=os.getenv("GOOGLE_CLOUD_PROJECT"),
            database=os.getenv("FIRESTORE_DATABASE", "(default)"),
        )
    return _firestore_client


# --- Auth (mirrors routers/auth.py) ---
def _compute_token(secret: str) -> str:
    return hmac.new(
        secret.encode(), f"{_APP_NAME}-auth".encode(), hashlib.sha256
    ).hexdigest()


def _is_authenticated(auth_token) -> bool:
    auth_secret = os.getenv("AUTH_SECRET")
    if not auth_secret or not auth_token:
        return False
    return hmac.compare_digest(auth_token, _compute_token(auth_secret))


# --- CORS ---
def _allowed_origins() -> list:
    return [
        o.strip()
        for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
        if o.strip()
    ]


def _cors_headers() -> dict:
    origin = request.headers.get("Origin", "")
    headers = {
        "Access-Control-Allow-Credentials": "true",
        "Vary": "Origin",
    }
    if origin in _allowed_origins():
        headers["Access-Control-Allow-Origin"] = origin
    return headers


def _json(payload, status: int):
    resp = jsonify(payload)
    resp.status_code = status
    for k, v in _cors_headers().items():
        resp.headers[k] = v
    return resp


# --- Storage / persistence (mirrors storage.py + repository.py Firestore path) ---
def _generate_stored_filename(original_filename: str) -> str:
    ext = os.path.splitext(original_filename or "")[1]
    return f"{uuid.uuid4().hex}{ext}"


def _save_to_gcs(object_key: str, content: bytes, content_type: str) -> None:
    bucket_name = os.getenv("GCS_BUCKET_NAME")
    bucket = _get_storage_client().bucket(bucket_name)
    blob = bucket.blob(object_key)
    blob.upload_from_string(content, content_type=content_type)


def _info_exists(info_id: str) -> bool:
    return (
        _get_firestore_client()
        .collection("nursery_info")
        .document(str(info_id))
        .get()
        .exists
    )


def _create_attachment(*, info_id, stored_filename, original_filename, mime_type,
                       file_size, object_key) -> dict:
    now = datetime.datetime.now(datetime.timezone.utc)
    doc_data = {
        "info_id": str(info_id),
        "stored_filename": stored_filename,
        "original_filename": original_filename,
        "mime_type": mime_type,
        "file_size": file_size,
        "storage_backend": "gcs",
        "object_key": object_key,
        "ocr_text": None,
        "ocr_status": "pending",
        "created_at": now,
    }
    _, doc_ref = _get_firestore_client().collection("attachments").add(doc_data)
    return {"id": doc_ref.id, "created_at": now, **doc_data}


# --- AI worker dispatch (mirrors worker_client.py) ---
def _dispatch_ocr(att_id, info_id, language: str) -> bool:
    base = os.getenv("AI_WORKER_URL", "").rstrip("/")
    if not base:
        logger.warning("AI_WORKER_URL not set; skipping worker dispatch for attachment %s", att_id)
        return False
    url = f"{base}/internal/process-ocr"
    headers = {}
    token = os.getenv("WORKER_INVOKE_TOKEN")
    if token:
        headers["X-Worker-Token"] = token
    payload = {"att_id": att_id, "info_id": info_id, "language": language}
    try:
        import requests

        resp = requests.post(url, json=payload, headers=headers, timeout=15.0)
        if resp.status_code >= 400:
            logger.error("worker dispatch failed (%s): %s", resp.status_code, resp.text[:200])
            return False
        return True
    except Exception as e:  # network/timeout — never block the upload response
        logger.error("worker dispatch error for attachment %s: %s", att_id, e)
        return False


@functions_framework.http
def upload_attachment(req):
    """HTTP entry point. ``req`` is the Flask request (functions-framework injects it)."""
    # CORS preflight
    if req.method == "OPTIONS":
        resp = Response(status=204)
        for k, v in _cors_headers().items():
            resp.headers[k] = v
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return resp

    if req.method != "POST":
        return _json({"detail": "Method not allowed"}, 405)

    # Extract info_id from the path
    m = _PATH_RE.match(req.path or "")
    if not m:
        return _json({"detail": "Not found"}, 404)
    info_id = m.group(1)

    # Auth: auth_token cookie HMAC
    if not _is_authenticated(req.cookies.get("auth_token")):
        return _json({"detail": "Not authenticated"}, 401)

    # File
    file = req.files.get("file")
    if file is None:
        return _json({"detail": "Missing file"}, 400)
    language = req.args.get("language", "ja")

    content_type = file.mimetype or ""
    if content_type != "application/pdf" and not content_type.startswith("image/"):
        return _json({"detail": "Unsupported file type"}, 400)

    # SOT-1374: 画像アップロード(受信→GCS書込→Firestore)の所要時間を計測する。
    with _time_block("upload_total", info_id=info_id):
        with _time_block("upload_read"):
            content = file.read()
        file_size = len(content)
        if file_size > MAX_FILE_SIZE:
            return _json(
                {"detail": f"File too large. Maximum size is {MAX_FILE_SIZE / (1024 * 1024)}MB"},
                413,
            )

        try:
            if not _info_exists(info_id):
                return _json({"detail": "NurseryInfo not found"}, 404)

            stored_filename = _generate_stored_filename(file.filename)
            object_key = f"uploads/{stored_filename}"
            with _time_block("upload_gcs", bytes=file_size):
                _save_to_gcs(object_key, content, content_type)

            att = _create_attachment(
                info_id=info_id,
                stored_filename=stored_filename,
                original_filename=file.filename,
                mime_type=content_type,
                file_size=file_size,
                object_key=object_key,
            )
        except Exception as e:
            logger.exception("upload failed: %s", e)
            return _json({"detail": "Upload failed"}, 500)

        # Best-effort OCR dispatch; never blocks the response.
        _dispatch_ocr(att["id"], info_id, language)

        return _json(
            {
                "id": att["id"],
                "info_id": att["info_id"],
                "original_filename": att["original_filename"],
                "mime_type": att["mime_type"],
                "file_size": att["file_size"],
                "ocr_status": att["ocr_status"],
                "created_at": att["created_at"].isoformat(),
            },
            200,
        )
