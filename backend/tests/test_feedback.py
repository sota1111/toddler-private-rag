"""SOT-1473: answer feedback (👍/👎) collection endpoint."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.routers.auth import get_current_user
from app import database

SQLALCHEMY_DATABASE_URL = "sqlite://"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


def override_get_current_user():
    return "test_user"


@pytest.fixture(autouse=True)
def setup_and_teardown(monkeypatch):
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(database, "SessionLocal", TestingSessionLocal)
    monkeypatch.setitem(app.dependency_overrides, get_db, override_get_db)
    monkeypatch.setitem(app.dependency_overrides, get_current_user, override_get_current_user)
    yield
    Base.metadata.drop_all(bind=engine)


client = TestClient(app)


def test_post_feedback_persists_and_summary_counts():
    up = client.post(
        "/api/feedback",
        json={"question": "遠足はいつ？", "answer": "11月10日です。", "rating": "up"},
    )
    assert up.status_code == 200, up.text
    assert up.json()["rating"] == "up"

    client.post(
        "/api/feedback",
        json={"question": "持ち物は？", "answer": "お弁当。", "rating": "down"},
    )
    client.post(
        "/api/feedback",
        json={"question": "時間は？", "answer": "9時。", "rating": "up"},
    )

    summary = client.get("/api/feedback/summary")
    assert summary.status_code == 200
    assert summary.json() == {"up": 2, "down": 1, "total": 3}


def test_invalid_rating_rejected():
    resp = client.post(
        "/api/feedback",
        json={"question": "q", "answer": "a", "rating": "meh"},
    )
    assert resp.status_code == 422
