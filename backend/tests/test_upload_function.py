"""SOT-1359: tests for the gen2 upload Cloud Function (backend/upload_function/main.py).

The function lives in a separate slim package with its own requirements (functions-framework).
These tests exercise the auth / path / validation branches that run BEFORE any GCP call, so they
need no GCS/Firestore access. They are skipped where functions-framework is not installed (e.g. the
backend CI image, which only installs backend/requirements.txt).
"""
import hashlib
import hmac
import os
import time

import pytest

functions_framework = pytest.importorskip("functions_framework")

_FUNCTION_SOURCE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "upload_function", "main.py"
)
_APP_NAME = "toddler-private-rag"
_OWNER = "0" * 32  # 32桁 hex 相当の owner_id（形式のみ重要）


def _client():
    app = functions_framework.create_app("upload_attachment", source=_FUNCTION_SOURCE)
    return app.test_client()


def _valid_token(secret: str, owner_id: str = _OWNER, issued_at: int | None = None) -> str:
    """SOT-1528: backend と同一スキームの署名付きセッション `<owner_id>.<issued_at>.<sig>`。"""
    if issued_at is None:
        issued_at = int(time.time())
    message = f"{_APP_NAME}-auth:{owner_id}:{issued_at}"
    sig = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return f"{owner_id}.{issued_at}.{sig}"


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


def test_legacy_fixed_token_rejected_401(monkeypatch):
    # SOT-1528(M3): 旧固定トークン（owner 非依存・有効期限なし）は失効させる。
    monkeypatch.setenv("AUTH_SECRET", "s3cr3t")
    legacy = hmac.new(
        b"s3cr3t", f"{_APP_NAME}-auth".encode(), hashlib.sha256
    ).hexdigest()
    client = _client()
    client.set_cookie("auth_token", legacy)
    resp = client.post("/api/info/1/attachments")
    assert resp.status_code == 401


def test_expired_session_rejected_401(monkeypatch):
    # SOT-1528(M4): 有効期限切れのセッションは拒否する。
    monkeypatch.setenv("AUTH_SECRET", "s3cr3t")
    monkeypatch.setenv("SESSION_MAX_AGE_SECONDS", "60")
    client = _client()
    client.set_cookie("auth_token", _valid_token("s3cr3t", issued_at=int(time.time()) - 3600))
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


def _load_main():
    import importlib.util

    spec = importlib.util.spec_from_file_location("upload_main_under_test", _FUNCTION_SOURCE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_dispatch_ocr_uses_short_timeout(monkeypatch):
    """SOT-1377: OCR dispatch はブラウザ応答を長くブロックしない短い read timeout を使う。"""
    main = _load_main()
    import requests

    captured = {}

    class _Resp:
        status_code = 202
        text = ""

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["timeout"] = timeout
        return _Resp()

    monkeypatch.setenv("AI_WORKER_URL", "https://backend.example")
    monkeypatch.setattr(requests, "post", fake_post)
    assert main._dispatch_ocr("att1", "info1", "ja") is True
    # (connect, read) のタプルで、read 待ちは短い（以前の 15s 同期待ちではない）。
    assert isinstance(captured["timeout"], tuple)
    assert captured["timeout"][1] <= 3.0


def test_dispatch_ocr_readtimeout_does_not_block(monkeypatch):
    """SOT-1377: 応答待ちタイムアウトでも例外を投げずアップロード応答をブロックしない。"""
    main = _load_main()
    import requests

    def fake_post(url, json=None, headers=None, timeout=None):
        raise requests.exceptions.ReadTimeout("timed out")

    monkeypatch.setenv("AI_WORKER_URL", "https://backend.example")
    monkeypatch.setattr(requests, "post", fake_post)
    assert main._dispatch_ocr("att1", "info1", "ja") is False
