import pytest
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
