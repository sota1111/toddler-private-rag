"""SOT-1359: tests for the gen2 upload Cloud Function (backend/upload_function/main.py).

The function lives in a separate slim package with its own requirements (functions-framework).
These tests exercise the auth / path / validation branches that run BEFORE any GCP call, so they
need no GCS/Firestore access. They are skipped where functions-framework is not installed (e.g. the
backend CI image, which only installs backend/requirements.txt).
"""
import hashlib
import hmac
import os

import pytest

functions_framework = pytest.importorskip("functions_framework")

_FUNCTION_SOURCE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "upload_function", "main.py"
)
_APP_NAME = "toddler-private-rag"


def _client():
    app = functions_framework.create_app("upload_attachment", source=_FUNCTION_SOURCE)
    return app.test_client()


def _valid_token(secret: str) -> str:
    return hmac.new(secret.encode(), f"{_APP_NAME}-auth".encode(), hashlib.sha256).hexdigest()


def test_get_method_not_allowed():
    resp = _client().get("/api/info/1/attachments")
    assert resp.status_code == 405


def test_bad_path_404():
    resp = _client().post("/not/the/upload/path")
    assert resp.status_code == 404


def test_missing_cookie_401(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", "s3cr3t")
    resp = _client().post("/api/info/1/attachments")
    assert resp.status_code == 401


def test_invalid_cookie_401(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", "s3cr3t")
    client = _client()
    client.set_cookie("auth_token", "wrong-token")
    resp = client.post("/api/info/1/attachments")
    assert resp.status_code == 401


def test_authenticated_missing_file_400(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", "s3cr3t")
    client = _client()
    client.set_cookie("auth_token", _valid_token("s3cr3t"))
    resp = client.post("/api/info/1/attachments")
    assert resp.status_code == 400


def test_authenticated_unsupported_type_400(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", "s3cr3t")
    client = _client()
    client.set_cookie("auth_token", _valid_token("s3cr3t"))
    resp = client.post(
        "/api/info/1/attachments",
        data={"file": (__import__("io").BytesIO(b"x"), "x.txt", "text/plain")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400


def test_options_preflight_204(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
    client = _client()
    resp = client.open(
        "/api/info/1/attachments",
        method="OPTIONS",
        headers={"Origin": "https://app.example.com"},
    )
    assert resp.status_code == 204
    assert resp.headers.get("Access-Control-Allow-Origin") == "https://app.example.com"
    assert resp.headers.get("Access-Control-Allow-Credentials") == "true"
