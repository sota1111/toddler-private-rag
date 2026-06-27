"""RagService: ties chunking, embedding, vector search and answer generation."""

import logging
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from .chunking import Chunk, build_documents
from .embedding_cache import EmbeddingCache, get_embedding_cache, text_hash
from .providers import (
    EmbeddingProvider,
    LLMProvider,
    get_embedding_provider,
    get_llm_provider,
)
from .vector_store import InMemoryVectorStore

logger = logging.getLogger(__name__)


@dataclass
class Source:
    info_id: Any
    title: str
    source: str
    score: float
    text: str
    filename: Optional[str] = None


@dataclass
class Answer:
    answer: str
    sources: List[Source]


class RagService:
    def __init__(
        self,
        embedding_provider: Optional[EmbeddingProvider] = None,
        llm_provider: Optional[LLMProvider] = None,
        chunk_size: int = 500,
        overlap: int = 50,
        embedding_cache: Optional[EmbeddingCache] = None,
    ) -> None:
        self.embedding_provider = embedding_provider or get_embedding_provider()
        self.llm_provider = llm_provider or get_llm_provider()
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.store = InMemoryVectorStore()
        # 永続埋め込みキャッシュ (SOT-1294): chunk 埋め込みを Firestore に永続化し再利用する。
        self.embedding_cache = embedding_cache or get_embedding_cache()

    def _embed_cached(self, texts: List[str]) -> List[List[float]]:
        """``texts`` の埋め込みを返す。保存済みは再利用し、未保存分のみ embed して永続化する。

        これにより「登録時にベクトル化して保存 → 質問時は保存済みを再利用」となり、
        質問のたびに全件 re-embed していた従来コストを無くす (SOT-1294)。
        """
        model = getattr(self.embedding_provider, "_model", "")
        dim = getattr(self.embedding_provider, "dimension", 0)
        keys = [text_hash(t, model, dim) for t in texts]

        cached = self.embedding_cache.get_many(keys)

        # キャッシュミスのテキストだけを（重複排除して）embed する。
        missing_keys = [k for k in dict.fromkeys(keys) if k not in cached]
        if missing_keys:
            key_to_text = {k: t for k, t in zip(keys, texts)}
            miss_texts = [key_to_text[k] for k in missing_keys]
            miss_vectors = self.embedding_provider.embed(miss_texts)
            new_items = dict(zip(missing_keys, miss_vectors))
            self.embedding_cache.put_many(new_items, model=model, dim=dim or 0)
            cached = {**cached, **new_items}

        return [cached[k] for k in keys]

    def build_index(self, infos: List[Any]) -> int:
        """Chunk + (cached) embed all infos and populate the vector store. Returns chunk count.

        埋め込みは ``_embed_cached`` 経由で保存済みベクトルを再利用する。既存データも初回質問時に
        ここでミスを埋めて永続化されるため、別途バックフィルは不要 (SOT-1294)。
        """
        chunks = build_documents(infos, self.chunk_size, self.overlap)
        if not chunks:
            return 0
        vectors = self._embed_cached([c.text for c in chunks])
        self.store.add(chunks, vectors)
        return len(chunks)

    def index_info(self, info: Any) -> int:
        """単一 info を chunk → 埋め込み → 永続化する（登録/更新時の eager 実行用 SOT-1294）。

        ベクトル検索インデックス（self.store）は構築せず、埋め込みキャッシュの永続化のみ行う。
        返り値は処理した chunk 数。
        """
        chunks = build_documents([info], self.chunk_size, self.overlap)
        if not chunks:
            return 0
        # _embed_cached が未保存分を embed して put_many する（保存が目的）。
        self._embed_cached([c.text for c in chunks])
        return len(chunks)

    def _search_chunks(self, query: str, top_k: int = 4) -> List[Tuple[Chunk, float]]:
        if len(self.store) == 0:
            return []
        query_vector = self.embedding_provider.embed([query])[0]
        return self.store.search(query_vector, top_k=top_k)

    def search(self, query: str, top_k: int = 4) -> List[Source]:
        hits = self._search_chunks(query, top_k=top_k)
        return [
            Source(
                info_id=c.info_id,
                title=c.title,
                source=c.source,
                score=score,
                text=c.text,
                filename=c.filename,
            )
            for c, score in hits
        ]

    def answer(
        self,
        query: str,
        top_k: int = 4,
        extra_contexts: Optional[List[str]] = None,
    ) -> Answer:
        sources = self.search(query, top_k=top_k)
        contexts = [s.text for s in sources]
        # SOT-1304: ベクトル検索に漏れるが回答に必要な文脈（例: 日付つきの直近行事）を先頭に追加する。
        # 相対日付クエリ（今週/来週/再来週）は語が一致せず検索で取りこぼすため、ここで補う。
        if extra_contexts:
            contexts = [c for c in extra_contexts if c] + contexts
        answer_text = self.llm_provider.generate(query, contexts)
        return Answer(answer=answer_text, sources=sources)


def get_rag_service(repo, **kwargs) -> RagService:
    """Build a RagService indexed over all infos in the given repository."""
    service = RagService(**kwargs)
    try:
        infos = repo.list()
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to list infos for RAG index")
        infos = []
    service.build_index(infos)
    return service
