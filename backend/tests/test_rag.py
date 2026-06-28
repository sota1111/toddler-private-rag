import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app import models
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


def test_build_documents_ocr_chunks_carry_filename():
    class FakeAtt:
        ocr_text = "OCRから抽出した持ち物リスト"
        original_filename = "おたより_2026-06.pdf"

    class FakeInfo:
        id = 1
        title = "遠足のお知らせ"
        content = "来週の遠足について"
        attachments = [FakeAtt()]

    docs = build_documents([FakeInfo()])
    ocr_chunks = [d for d in docs if d.source == "ocr"]
    content_chunks = [d for d in docs if d.source == "content"]
    assert ocr_chunks and all(d.filename == "おたより_2026-06.pdf" for d in ocr_chunks)
    # content chunks have no attachment filename
    assert content_chunks and all(d.filename is None for d in content_chunks)


def test_build_documents_ocr_only_excludes_content():
    # SOT-1357: ocr_only=True では写真の文字起こし(source="ocr")のみを対象とする
    class FakeAtt:
        ocr_text = "OCRから抽出した持ち物リスト"
        original_filename = "おたより_2026-06.pdf"

    class FakeInfo:
        id = 1
        title = "遠足のお知らせ"
        content = "来週の遠足について"
        attachments = [FakeAtt()]

    docs = build_documents([FakeInfo()], ocr_only=True)
    sources = {d.source for d in docs}
    assert sources == {"ocr"}
    assert docs and all(d.source == "ocr" for d in docs)


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


def _seed_with_ocr(title, info_type, ocr_text, *, filename="おたより.png", content=""):
    """info を作成し、その添付として ``ocr_text`` を持つ写真を直接DBに登録する。

    SOT-1357: RAG /ask は写真の文字起こし(添付OCR)のみを根拠にするため、テストでは
    添付の ocr_text に根拠テキストを持たせる。
    """
    info_id = _seed(title, info_type, content)
    db = TestingSessionLocal()
    try:
        att = models.Attachment(
            info_id=info_id,
            stored_filename="stored.png",
            original_filename=filename,
            mime_type="image/png",
            file_size=123,
            storage_backend="local",
            ocr_text=ocr_text,
            ocr_status="done",
        )
        db.add(att)
        db.commit()
    finally:
        db.close()
    return info_id


def test_ask_endpoint_returns_answer_and_sources():
    id1 = _seed_with_ocr(
        "遠足のお知らせ", "行事", "来週の遠足では お弁当 水筒 レジャーシート を持参してください"
    )
    _seed_with_ocr("発表会", "行事", "発表会の衣装は各家庭で準備してください")

    resp = client.post("/api/info/ask", json={"query": "遠足に持っていくものは？", "top_k": 3})
    assert resp.status_code == 200
    data = resp.json()
    assert data["answer"]
    assert len(data["sources"]) >= 1
    # SOT-1357: 根拠はすべて写真の文字起こし(ocr)のみ。
    assert all(s["source"] == "ocr" for s in data["sources"])
    # The most relevant source should be the 遠足 info.
    assert data["sources"][0]["info_id"] == id1


def test_ask_endpoint_sources_include_citation_label():
    _seed_with_ocr(
        "遠足のお知らせ", "行事",
        "来週の遠足では お弁当 水筒 レジャーシート を持参してください",
        filename="遠足のしおり.png",
    )

    resp = client.post("/api/info/ask", json={"query": "遠足の持ち物", "top_k": 3})
    assert resp.status_code == 200
    sources = resp.json()["sources"]
    assert sources
    for s in sources:
        # citation metadata is present for every source
        assert "filename" in s and "label" in s
        assert s["label"]
    # SOT-1357: 出典は写真の文字起こし(ocr)のみで、ラベルに添付ファイル名を含む。
    ocr_sources = [s for s in sources if s["source"] == "ocr"]
    assert ocr_sources
    assert all(s["source"] == "ocr" for s in sources)
    assert "遠足のしおり.png" in ocr_sources[0]["label"]


def test_ask_endpoint_sources_include_text_snippet():
    # SOT-1094: 回答の根拠となる元テキストの抜粋(引用)を出典に含める
    _seed_with_ocr(
        "遠足のお知らせ", "行事", "来週の遠足では お弁当 水筒 レジャーシート を持参してください"
    )

    resp = client.post("/api/info/ask", json={"query": "遠足の持ち物", "top_k": 3})
    assert resp.status_code == 200
    sources = resp.json()["sources"]
    assert sources
    for s in sources:
        assert "snippet" in s
    # 少なくとも1件は実際の元テキスト抜粋を持つ
    assert any(s["snippet"] for s in sources)


# --- SOT-1304: 相対日付クエリで登録済み行事をコンテキストに補う ---

def test_upcoming_event_contexts_includes_dated_event_with_date_label():
    import datetime

    from app import clock
    from app.routers.info import _upcoming_event_contexts

    today = clock.today()

    class FakeInfo:
        def __init__(self, id, title, info_type, content, event_date):
            self.id = id
            self.title = title
            self.info_type = info_type
            self.content = content
            self.event_date = event_date
            self.date = None
            self.due_date = None
            self.items = None

    class FakeRepo:
        def list(self):
            return [
                # 35日先のホライズン内 → 含まれる
                FakeInfo(1, "七夕会", "行事", "短冊に願い事を書きます", today + datetime.timedelta(days=10)),
                # ホライズン外（遠い未来） → 含まれない
                FakeInfo(2, "運動会", "行事", "秋の運動会", today + datetime.timedelta(days=120)),
                # 日付なし → 含まれない
                FakeInfo(3, "園だより", "お知らせ", "今月のお便り", None),
            ]

    contexts = _upcoming_event_contexts(FakeRepo())
    joined = "\n".join(contexts)
    assert "七夕会" in joined
    # 絶対日付を明示してLLMが相対日付を解釈できるようにする
    assert (today + datetime.timedelta(days=10)).isoformat() in joined
    assert "運動会" not in joined
    assert "園だより" not in joined


def test_answer_includes_extra_contexts():
    class FakeInfo:
        def __init__(self, id, title, content):
            self.id = id
            self.title = title
            self.content = content
            self.attachments = []

    service = RagService(embedding_provider=FakeEmbeddingProvider(), llm_provider=FakeLLMProvider())
    service.build_index([FakeInfo(1, "給食", "今週の献立はカレーです")])
    # FakeLLMProvider はコンテキストをそのまま回答に反映する。
    result = service.answer("再来週の予定は？", top_k=2, extra_contexts=["【行事】七夕会 / 日付: 2026-07-07（火曜日）"])
    assert "七夕会" in result.answer


# SOT-1357: /ask の日付イベント追加コンテキスト注入(SOT-1304)は廃止したため、
# 旧 test_ask_endpoint_answers_relative_date_event_question は削除。
# RagService.answer の extra_contexts 機能自体は test_answer_includes_extra_contexts で維持。


def test_vector_search_endpoint():
    id1 = _seed("給食の献立", "連絡", "今週の給食はカレーライスとサラダです アレルギー対応あり")
    _seed("運動会", "行事", "運動会は晴天の場合に開催します")

    resp = client.get("/api/info/search", params={"q": "給食 献立 アレルギー", "top_k": 2})
    assert resp.status_code == 200
    data = resp.json()
    assert data["query"] == "給食 献立 アレルギー"
    assert data["sources"][0]["info_id"] == id1
