"""永続埋め込みキャッシュと RagService の再利用テスト (SOT-1294)。

登録時にベクトル化して保存 → 質問時は保存済みを再利用、という挙動を、
決定的な Fake provider と呼び出しカウンタで検証する。
"""

from typing import List

from app.rag.embedding_cache import (
    InMemoryEmbeddingCache,
    text_hash,
)
from app.rag.providers import FakeEmbeddingProvider, FakeLLMProvider
from app.rag.service import RagService


class CountingEmbeddingProvider(FakeEmbeddingProvider):
    """embed したテキスト総数を数える Fake provider。"""

    def __init__(self) -> None:
        super().__init__()
        self.embedded_count = 0

    def embed(self, texts: List[str]) -> List[List[float]]:
        self.embedded_count += len(texts)
        return super().embed(texts)


class FakeInfo:
    def __init__(self, id, title, content):
        self.id = id
        self.title = title
        self.content = content
        self.attachments = []


def test_text_hash_stable_and_sensitive():
    assert text_hash("hello", "m", 256) == text_hash("hello", "m", 256)
    assert text_hash("hello", "m", 256) != text_hash("hello", "m", 768)
    assert text_hash("hello", "m", 256) != text_hash("world", "m", 256)


def test_in_memory_cache_get_put_roundtrip():
    cache = InMemoryEmbeddingCache()
    assert cache.get_many(["a", "b"]) == {}
    cache.put_many({"a": [1.0, 2.0]}, model="m", dim=2)
    got = cache.get_many(["a", "b"])
    assert got == {"a": [1.0, 2.0]}


def test_build_index_reuses_persisted_embeddings():
    # 同じキャッシュを共有する2つのサービスで、2回目は埋め込み呼び出しが発生しないこと。
    cache = InMemoryEmbeddingCache()
    infos = [
        FakeInfo(1, "遠足", "遠足 持ち物 お弁当 水筒 が必要です"),
        FakeInfo(2, "発表会", "発表会 衣装 練習 ホール"),
    ]

    provider1 = CountingEmbeddingProvider()
    svc1 = RagService(
        embedding_provider=provider1,
        llm_provider=FakeLLMProvider(),
        embedding_cache=cache,
    )
    n1 = svc1.build_index(infos)
    assert n1 > 0
    assert provider1.embedded_count == n1  # 初回は全 chunk を embed

    provider2 = CountingEmbeddingProvider()
    svc2 = RagService(
        embedding_provider=provider2,
        llm_provider=FakeLLMProvider(),
        embedding_cache=cache,
    )
    n2 = svc2.build_index(infos)
    assert n2 == n1
    assert provider2.embedded_count == 0  # 2回目は全て保存済みを再利用


def test_index_info_persists_without_building_store():
    # index_info は永続化のみ行い、その後の build_index で再 embed されないこと。
    cache = InMemoryEmbeddingCache()
    info = FakeInfo(1, "遠足", "遠足 持ち物 お弁当 水筒")

    writer = CountingEmbeddingProvider()
    writer_svc = RagService(
        embedding_provider=writer,
        llm_provider=FakeLLMProvider(),
        embedding_cache=cache,
    )
    chunk_count = writer_svc.index_info(info)
    assert chunk_count > 0
    assert writer.embedded_count == chunk_count
    assert len(writer_svc.store) == 0  # index_info は検索ストアを作らない

    reader = CountingEmbeddingProvider()
    reader_svc = RagService(
        embedding_provider=reader,
        llm_provider=FakeLLMProvider(),
        embedding_cache=cache,
    )
    reader_svc.build_index([info])
    assert reader.embedded_count == 0  # 登録時に保存済みなので再 embed なし
