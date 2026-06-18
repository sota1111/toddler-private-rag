"""RagService: ties chunking, embedding, vector search and answer generation."""

import logging
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from .chunking import Chunk, build_documents
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
    ) -> None:
        self.embedding_provider = embedding_provider or get_embedding_provider()
        self.llm_provider = llm_provider or get_llm_provider()
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.store = InMemoryVectorStore()

    def build_index(self, infos: List[Any]) -> int:
        """Chunk + embed all infos and populate the vector store. Returns chunk count."""
        chunks = build_documents(infos, self.chunk_size, self.overlap)
        if not chunks:
            return 0
        vectors = self.embedding_provider.embed([c.text for c in chunks])
        self.store.add(chunks, vectors)
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

    def answer(self, query: str, top_k: int = 4) -> Answer:
        sources = self.search(query, top_k=top_k)
        contexts = [s.text for s in sources]
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
