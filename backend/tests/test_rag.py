import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.routers.auth import get_current_user

from app.rag.chunking import chunk_text, build_documents, Chunk
from app.rag.providers import FakeEmbeddingProvider, FakeLLMProvider
from app.rag.vector_store import InMemoryVectorStore, cosine_similarity
from app.rag.service import RagService


# --- Test DB / auth overrides (mirrors test_attachments.py) ---

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


@pytest.fixture(autouse=True)
def setup_and_teardown():
    # Force the deterministic offline providers regardless of ambient env.
    os.environ["EMBEDDING_PROVIDER"] = "fake"
    os.environ["LLM_PROVIDER"] = "fake"
    Base.metadata.create_all(bind=engine)

    # Save/restore overrides so this module never clobbers sibling test modules.
    original_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: "test_user"

    yield

    app.dependency_overrides = original_overrides
    Base.metadata.drop_all(bind=engine)


client = TestClient(app)


# --- chunking ---

def test_chunk_text_splits_long_text_with_overlap():
    text = "あ" * 1200
    chunks = chunk_text(text, chunk_size=500, overlap=50)
    assert len(chunks) == 3  # step 450 -> 0,450,900
    assert all(len(c) <= 500 for c in chunks)


def test_chunk_text_drops_empty_and_short():
    assert chunk_text("") == []
    assert chunk_text("   ") == []
    assert chunk_text("hello") == ["hello"]


def test_build_documents_includes_content_and_ocr():
    class FakeAtt:
        ocr_text = "OCRから抽出した持ち物リスト"

    class FakeInfo:
        id = 1
        title = "遠足のお知らせ"
        content = "来週の遠足について"
        attachments = [FakeAtt()]

    docs = build_documents([FakeInfo()])
    sources = {d.source for d in docs}
    assert sources == {"content", "ocr"}
    assert all(isinstance(d, Chunk) for d in docs)


# --- embeddings ---

def test_fake_embedding_deterministic_and_dimension():
    provider = FakeEmbeddingProvider()
    v1 = provider.embed(["保育園の遠足"])[0]
    v2 = provider.embed(["保育園の遠足"])[0]
    assert v1 == v2
    assert len(v1) == provider.dimension


def test_cosine_similarity_basic():
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


# --- vector search (acceptance #1) ---

def test_cosine_search_ranks_relevant_chunk_first():
    embedder = FakeEmbeddingProvider()
    store = InMemoryVectorStore()
    chunks = [
        Chunk(info_id=1, title="遠足", text="遠足 持ち物 お弁当 水筒", source="content"),
        Chunk(info_id=2, title="発表会", text="発表会 衣装 練習 ホール", source="content"),
        Chunk(info_id=3, title="献立", text="今週 の 給食 献立 アレルギー", source="content"),
    ]
    vectors = embedder.embed([c.text for c in chunks])
    store.add(chunks, vectors)

    query_vec = embedder.embed(["遠足 持ち物 お弁当"])[0]
    results = store.search(query_vec, top_k=3)
    assert results[0][0].info_id == 1
    assert results[0][1] >= results[1][1] >= results[2][1]


def test_rag_service_search_returns_sources():
    class FakeInfo:
        def __init__(self, id, title, content):
            self.id = id
            self.title = title
            self.content = content
            self.attachments = []

    service = RagService(embedding_provider=FakeEmbeddingProvider(), llm_provider=FakeLLMProvider())
    service.build_index([
        FakeInfo(1, "遠足", "遠足 持ち物 お弁当 水筒 が必要です"),
        FakeInfo(2, "発表会", "発表会 衣装 練習 ホール"),
    ])
    sources = service.search("遠足 持ち物 お弁当", top_k=2)
    assert sources
    assert sources[0].info_id == 1


# --- answer generation via endpoint (acceptance #2) ---

def _seed(title, info_type, content):
    resp = client.post(
        "/api/info/",
        json={"title": title, "info_type": info_type, "content": content},
    )
    assert resp.status_code == 200
    return resp.json()["id"]


def test_ask_endpoint_returns_answer_and_sources():
    id1 = _seed("遠足のお知らせ", "行事", "来週の遠足では お弁当 水筒 レジャーシート を持参してください")
    _seed("発表会", "行事", "発表会の衣装は各家庭で準備してください")

    resp = client.post("/api/info/ask", json={"query": "遠足に持っていくものは？", "top_k": 3})
    assert resp.status_code == 200
    data = resp.json()
    assert data["answer"]
    assert len(data["sources"]) >= 1
    # The most relevant source should be the 遠足 info.
    assert data["sources"][0]["info_id"] == id1


def test_vector_search_endpoint():
    id1 = _seed("給食の献立", "連絡", "今週の給食はカレーライスとサラダです アレルギー対応あり")
    _seed("運動会", "行事", "運動会は晴天の場合に開催します")

    resp = client.get("/api/info/search", params={"q": "給食 献立 アレルギー", "top_k": 2})
    assert resp.status_code == 200
    data = resp.json()
    assert data["query"] == "給食 献立 アレルギー"
    assert data["sources"][0]["info_id"] == id1
