"""Embedding and LLM provider abstractions.

The default providers (``FakeEmbeddingProvider`` / ``FakeLLMProvider``) are
deterministic and require no network or API key, so the RAG pipeline runs and is
testable offline. The real ``gemini`` providers lazily import their SDK inside
methods, so importing this module never fails when the SDK is absent.
"""

import abc
import hashlib
import logging
import math
import os
import re
from typing import List

logger = logging.getLogger(__name__)

_FAKE_DIMENSION = 256
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


# --- Interfaces ---

class EmbeddingProvider(abc.ABC):
    @property
    @abc.abstractmethod
    def dimension(self) -> int:
        ...

    @abc.abstractmethod
    def embed(self, texts: List[str]) -> List[List[float]]:
        """Return one embedding vector per input text."""
        ...


class LLMProvider(abc.ABC):
    @abc.abstractmethod
    def generate(self, question: str, contexts: List[str]) -> str:
        """Generate an answer for ``question`` grounded in ``contexts``."""
        ...


# --- Fake (deterministic, offline) implementations ---

def _tokenize(text: str) -> List[str]:
    return _TOKEN_RE.findall((text or "").lower())


class FakeEmbeddingProvider(EmbeddingProvider):
    """Deterministic, dependency-free embeddings.

    Each token is hashed into a fixed bucket and accumulated, then the vector is
    L2-normalized. The same text always yields the same vector, and texts that
    share tokens have higher cosine similarity — enough to make vector search
    meaningfully rank relevant chunks in tests and offline use.
    """

    def __init__(self, dimension: int = _FAKE_DIMENSION):
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def _embed_one(self, text: str) -> List[float]:
        vec = [0.0] * self._dimension
        for token in _tokenize(text):
            digest = hashlib.md5(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self._dimension
            # Sign derived from another byte to spread tokens across the space.
            sign = 1.0 if digest[4] & 1 else -1.0
            vec[bucket] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0.0:
            return vec
        return [v / norm for v in vec]

    def embed(self, texts: List[str]) -> List[List[float]]:
        return [self._embed_one(t) for t in texts]


class FakeLLMProvider(LLMProvider):
    """Deterministic answer generation grounded in the retrieved contexts."""

    def generate(self, question: str, contexts: List[str]) -> str:
        if not contexts:
            return f"「{question}」に関連する情報は見つかりませんでした。"
        excerpt = " / ".join(c.strip().replace("\n", " ")[:200] for c in contexts if c.strip())
        return f"「{question}」について、関連情報に基づくと: {excerpt}"


# --- Real (Gemini) implementations — SDK imported lazily ---

def _gemini_api_key() -> str:
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY (or GOOGLE_API_KEY) is not set; cannot use the gemini provider. "
            "Set EMBEDDING_PROVIDER/LLM_PROVIDER=fake for offline use."
        )
    return key


def _import_genai():
    try:
        import google.generativeai as genai  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised only when SDK absent
        raise RuntimeError(
            "google-generativeai is not installed; the gemini provider is unavailable. "
            "Install it or use EMBEDDING_PROVIDER/LLM_PROVIDER=fake."
        ) from exc
    return genai


class GeminiEmbeddingProvider(EmbeddingProvider):
    def __init__(self, model: str = "models/text-embedding-004", dimension: int = 768):
        self._model = model
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: List[str]) -> List[List[float]]:
        genai = _import_genai()
        genai.configure(api_key=_gemini_api_key())
        vectors: List[List[float]] = []
        for text in texts:
            result = genai.embed_content(model=self._model, content=text)
            vectors.append(list(result["embedding"]))
        return vectors


class GeminiLLMProvider(LLMProvider):
    def __init__(self, model: str = "gemini-1.5-flash"):
        self._model = model

    def generate(self, question: str, contexts: List[str]) -> str:
        genai = _import_genai()
        genai.configure(api_key=_gemini_api_key())
        context_block = "\n\n".join(f"- {c}" for c in contexts)
        prompt = (
            "あなたは保育園情報アシスタントです。以下のコンテキストのみに基づいて、"
            "日本語で簡潔に質問へ回答してください。コンテキストに無いことは推測しないでください。\n\n"
            f"# コンテキスト\n{context_block}\n\n# 質問\n{question}\n\n# 回答"
        )
        model = genai.GenerativeModel(self._model)
        response = model.generate_content(prompt)
        return (getattr(response, "text", "") or "").strip()


# --- Factories (env-selected; default = fake) ---

def get_embedding_provider() -> EmbeddingProvider:
    provider = os.getenv("EMBEDDING_PROVIDER", "fake").lower()
    if provider == "gemini":
        return GeminiEmbeddingProvider()
    if provider not in ("fake", ""):
        logger.warning("Unknown EMBEDDING_PROVIDER=%s, falling back to fake", provider)
    return FakeEmbeddingProvider()


def get_llm_provider() -> LLMProvider:
    provider = os.getenv("LLM_PROVIDER", "fake").lower()
    if provider == "gemini":
        return GeminiLLMProvider()
    if provider not in ("fake", ""):
        logger.warning("Unknown LLM_PROVIDER=%s, falling back to fake", provider)
    return FakeLLMProvider()
