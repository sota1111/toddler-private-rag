import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.routers import auth


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", "test-secret-value-1234567890")
    monkeypatch.setenv("FIREBASE_API_KEY", "test-api-key")
    monkeypatch.setenv("ALLOWED_USER_EMAILS", "allowed@example.com")
    return TestClient(app)


def test_session_success_sets_cookie(client, monkeypatch):
    def fake_post(url, params=None, json=None, timeout=None):
        # Never echo the password back; return the verified identity only.
        return FakeResponse(200, {"email": "allowed@example.com"})

    monkeypatch.setattr(auth.httpx, "post", fake_post)

    res = client.post(
        "/api/auth/session",
        json={"email": "allowed@example.com", "password": "correct-password"},
    )
    assert res.status_code == 200
    assert res.json()["success"] is True
    assert "auth_token" in res.cookies


def test_session_invalid_credentials_returns_401(client, monkeypatch):
    def fake_post(url, params=None, json=None, timeout=None):
        return FakeResponse(400, {"error": {"message": "INVALID_LOGIN_CREDENTIALS"}})

    monkeypatch.setattr(auth.httpx, "post", fake_post)

    res = client.post(
        "/api/auth/session",
        json={"email": "allowed@example.com", "password": "wrong"},
    )
    assert res.status_code == 401
    assert "auth_token" not in res.cookies


def test_session_email_not_allowed_returns_403(client, monkeypatch):
    def fake_post(url, params=None, json=None, timeout=None):
        return FakeResponse(200, {"email": "intruder@example.com"})

    monkeypatch.setattr(auth.httpx, "post", fake_post)

    res = client.post(
        "/api/auth/session",
        json={"email": "intruder@example.com", "password": "correct-password"},
    )
    assert res.status_code == 403
    assert "auth_token" not in res.cookies


def test_session_too_many_attempts_returns_429(client, monkeypatch):
    def fake_post(url, params=None, json=None, timeout=None):
        return FakeResponse(
            400, {"error": {"message": "TOO_MANY_ATTEMPTS_TRY_LATER"}}
        )

    monkeypatch.setattr(auth.httpx, "post", fake_post)

    res = client.post(
        "/api/auth/session",
        json={"email": "allowed@example.com", "password": "x"},
    )
    assert res.status_code == 429


# --- SOT-1487: Google sign-in (Firebase ID token) ---

def test_google_session_success_sets_cookie(client, monkeypatch):
    def fake_post(url, params=None, json=None, timeout=None):
        # accounts:lookup returns the verified user for a valid project token.
        return FakeResponse(
            200,
            {"users": [{"email": "allowed@example.com", "emailVerified": True}]},
        )

    monkeypatch.setattr(auth.httpx, "post", fake_post)

    res = client.post("/api/auth/session/google", json={"id_token": "valid.token"})
    assert res.status_code == 200
    assert res.json()["success"] is True
    assert "auth_token" in res.cookies


def test_google_session_invalid_token_returns_401(client, monkeypatch):
    def fake_post(url, params=None, json=None, timeout=None):
        return FakeResponse(400, {"error": {"message": "INVALID_ID_TOKEN"}})

    monkeypatch.setattr(auth.httpx, "post", fake_post)

    res = client.post("/api/auth/session/google", json={"id_token": "bad"})
    assert res.status_code == 401
    assert "auth_token" not in res.cookies


def test_google_session_any_verified_email_allowed(client, monkeypatch):
    # SOT-1497: Google 認証は allowlist を免除し、検証済みメールを持つ任意の
    # アカウント（allowlist 外でも）に使用を許可する。
    def fake_post(url, params=None, json=None, timeout=None):
        return FakeResponse(
            200,
            {"users": [{"email": "anyone@example.com", "emailVerified": True}]},
        )

    monkeypatch.setattr(auth.httpx, "post", fake_post)

    res = client.post("/api/auth/session/google", json={"id_token": "valid.token"})
    assert res.status_code == 200
    assert res.json()["success"] is True
    assert "auth_token" in res.cookies


def test_google_session_unverified_email_returns_401(client, monkeypatch):
    def fake_post(url, params=None, json=None, timeout=None):
        return FakeResponse(
            200,
            {"users": [{"email": "allowed@example.com", "emailVerified": False}]},
        )

    monkeypatch.setattr(auth.httpx, "post", fake_post)

    res = client.post("/api/auth/session/google", json={"id_token": "valid.token"})
    assert res.status_code == 401
    assert "auth_token" not in res.cookies


# --- SOT-1528(M4): セッショントークンの有効期限・失効 ---

_SECRET = "test-secret-value-1234567890"
_OWNER = "0" * 32


def test_valid_session_returns_owner(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", _SECRET)
    token = auth._build_session_token(_OWNER, _SECRET)
    assert auth.get_current_user(auth_token=token) == _OWNER


def test_tampered_signature_rejected(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", _SECRET)
    issued_at = int(time.time())
    token = f"{_OWNER}.{issued_at}.{'0' * 64}"
    with pytest.raises(HTTPException) as exc:
        auth.get_current_user(auth_token=token)
    assert exc.value.status_code == 401


def test_expired_session_rejected(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", _SECRET)
    monkeypatch.setenv("SESSION_MAX_AGE_SECONDS", "60")
    old = int(time.time()) - 3600
    token = auth._build_session_token(_OWNER, _SECRET, issued_at=old)
    with pytest.raises(HTTPException) as exc:
        auth.get_current_user(auth_token=token)
    assert exc.value.status_code == 401


def test_legacy_two_part_token_rejected(monkeypatch):
    # SOT-1528(M4): 発行時刻を含まない旧形式 `<owner_id>.<sig>` は失効させ再ログインを促す。
    monkeypatch.setenv("AUTH_SECRET", _SECRET)
    legacy_sig = auth.hmac.new(
        _SECRET.encode(), f"{auth._APP_NAME}-auth:{_OWNER}".encode(), auth.hashlib.sha256
    ).hexdigest()
    token = f"{_OWNER}.{legacy_sig}"
    with pytest.raises(HTTPException) as exc:
        auth.get_current_user(auth_token=token)
    assert exc.value.status_code == 401
