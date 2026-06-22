"""Tests for SOT-1039: 登録時AI自動タグ付け (/suggest-tags) と ハイブリッド検索 (/hybrid-search).

AI クライアントは未設定なので決定的なヒューリスティックで動作する。
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.routers.auth import get_current_user
from app import storage, database

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
def setup_and_teardown(tmp_path, monkeypatch):
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(database, "SessionLocal", TestingSessionLocal)
    monkeypatch.setitem(app.dependency_overrides, get_db, override_get_db)
    monkeypatch.setitem(app.dependency_overrides, get_current_user, override_get_current_user)
    # AI クライアントを無効化してヒューリスティック経路を強制
    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    original_upload_dir = storage.UPLOAD_DIR
    storage.UPLOAD_DIR = tmp_path / "uploads"
    (tmp_path / "uploads").mkdir(parents=True, exist_ok=True)

    yield

    Base.metadata.drop_all(bind=engine)
    storage.UPLOAD_DIR = original_upload_dir


client = TestClient(app)

INFO_TYPES = ["資料", "掲示", "行事", "持ち物", "提出物", "お知らせ", "給食", "休園変更"]
PRIORITY_TYPES = ["高", "普通", "低"]


def _create(payload: dict) -> dict:
    body = {"title": "t", "info_type": "お知らせ", "content": "c", **payload}
    resp = client.post("/api/info/", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


# --- 提案3: 自動タグ付け ---

def test_suggest_tags_returns_valid_metadata():
    resp = client.post(
        "/api/info/suggest-tags",
        json={"title": "運動会のお知らせ", "content": "5月1日に運動会を行います。締切は4月20日です。"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["info_type"] in INFO_TYPES
    assert data["priority"] in PRIORITY_TYPES
    assert data["source"] == "heuristic"  # AIクライアント無効
    assert isinstance(data["tags"], list)
    # 行事キーワード → 行事
    assert data["info_type"] == "行事"
    # 締切キーワードがあるので優先度は高
    assert data["priority"] == "高"
    # 日付が検出される
    assert data["date"] == "2026-05-01"
    assert "運動会" in data["tags"]


def test_suggest_tags_respects_existing_type():
    resp = client.post(
        "/api/info/suggest-tags",
        json={"title": "給食だより", "content": "今月の献立です。", "info_type": "給食"},
    )
    assert resp.status_code == 200
    assert resp.json()["info_type"] == "給食"


# --- 提案6: ハイブリッド検索 ---

def test_hybrid_search_keyword_and_facets():
    _create({"title": "遠足のお知らせ", "content": "来週は遠足です", "info_type": "行事", "priority": "高"})
    _create({"title": "給食だより", "content": "今月の献立", "info_type": "給食", "priority": "普通"})

    # キーワード検索（遠足）
    resp = client.get("/api/info/hybrid-search", params={"q": "遠足"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["query"] == "遠足"
    titles = [r["info"]["title"] for r in data["results"]]
    assert "遠足のお知らせ" in titles
    # 関連度の高い順
    top = data["results"][0]
    assert top["info"]["title"] == "遠足のお知らせ"
    assert top["score"] >= 0
    assert "keyword_score" in top and "vector_score" in top

    # 種別ファセットで給食のみ
    resp2 = client.get("/api/info/hybrid-search", params={"info_type": "給食"})
    assert resp2.status_code == 200
    titles2 = [r["info"]["title"] for r in resp2.json()["results"]]
    assert titles2 == ["給食だより"]


def test_hybrid_search_date_range_facet():
    _create({"title": "5月行事", "content": "x", "info_type": "行事", "date": "2026-05-10"})
    _create({"title": "3月行事", "content": "y", "info_type": "行事", "date": "2026-03-10"})

    resp = client.get(
        "/api/info/hybrid-search",
        params={"date_from": "2026-05-01", "date_to": "2026-05-31"},
    )
    assert resp.status_code == 200, resp.text
    titles = [r["info"]["title"] for r in resp.json()["results"]]
    assert "5月行事" in titles
    assert "3月行事" not in titles
