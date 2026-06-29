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
from typing import Iterator, List

logger = logging.getLogger(__name__)

_FAKE_DIMENSION = 256
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _embed_max_workers() -> int:
    """並列 embed のワーカー数(``EMBED_MAX_WORKERS``、既定 4)。"""
    try:
        return max(1, int(os.getenv("EMBED_MAX_WORKERS", "4")))
    except (TypeError, ValueError):
        return 4


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

    def generate_stream(self, question: str, contexts: List[str]) -> Iterator[str]:
        """回答を逐次(チャンク)で返す (SOT-1374 / C ストリーミング)。

        既定実装は ``generate`` を1回呼んで全文を1チャンクとして返す
        (後方互換: ストリーミング非対応プロバイダでも動く)。
        """
        yield self.generate(question, contexts)


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

    def generate_stream(self, question: str, contexts: List[str]) -> Iterator[str]:
        # オフライン/テストでもストリーミング経路を観測できるよう、全文を空白で分割して逐次返す。
        text = self.generate(question, contexts)
        parts = text.split(" ")
        for i, part in enumerate(parts):
            yield part if i == 0 else " " + part


# --- Real (Gemini) implementations — Vertex AI via google-genai, SDK imported lazily ---


class GeminiEmbeddingProvider(EmbeddingProvider):
    def __init__(self, model: str = "text-embedding-004", dimension: int = 768):
        self._model = model
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: List[str]) -> List[List[float]]:
        # SOT-1374 / B+C: 埋め込みは外部API待ちが主体なので、複数テキストを
        # ThreadPoolExecutor で並列(バッチ的)に embed して壁時計時間を縮める。
        # 入力順は parallel_map が保持する。OCR は並列化しない(指示)。
        from ..ai_client import get_genai_client, with_retry
        from ..concurrency import parallel_map

        client = get_genai_client()

        def _embed_one(text: str) -> List[float]:
            result = with_retry(
                lambda t=text: client.models.embed_content(model=self._model, contents=t)
            )
            return list(result.embeddings[0].values)

        max_workers = _embed_max_workers()
        return parallel_map(_embed_one, list(texts), max_workers=max_workers)


class GeminiLLMProvider(LLMProvider):
    def __init__(self, model: str | None = None):
        from ..ai_client import get_model_name

        self._model = model or get_model_name()

    def _build_prompt(self, question: str, contexts: List[str]) -> str:
        from .. import clock

        context_block = "\n\n".join(f"- {c}" for c in contexts)
        # SOT-1297: 今日の日付(JST)を注入し、相対的な日付の質問に答えられるようにする。
        _weekdays_ja = ("月", "火", "水", "木", "金", "土", "日")
        today = clock.today()
        today_line = (
            f"今日の日付は {today.isoformat()}（{_weekdays_ja[today.weekday()]}曜日）です。"
            "「今日」「明日」「今週」「来週」などの相対的な日付はこれを基準に解釈してください。"
        )
        return (
            "あなたはおたよりナビです。以下のコンテキストのみに基づいて、"
            "日本語で簡潔に質問へ回答してください。コンテキストに無いことは推測しないでください。\n\n"
            f"{today_line}\n\n"
            f"# コンテキスト\n{context_block}\n\n# 質問\n{question}\n\n# 回答"
        )

    def generate(self, question: str, contexts: List[str]) -> str:
        from ..ai_client import default_generate_config, get_genai_client, with_retry

        client = get_genai_client()
        prompt = self._build_prompt(question, contexts)
        cfg = default_generate_config(max_output_tokens=4096)

        def _gen():
            if cfg is not None:
                return client.models.generate_content(
                    model=self._model, contents=prompt, config=cfg
                )
            return client.models.generate_content(model=self._model, contents=prompt)

        response = with_retry(_gen)
        return (getattr(response, "text", "") or "").strip()

    def generate_stream(self, question: str, contexts: List[str]) -> Iterator[str]:
        """Gemini のストリーミング生成 (SOT-1374 / C)。

        逐次チャンクを yield する。SDK 差異/失敗時は ``generate`` の全文を1回 yield する
        フォールバックに落ちる(回答が必ず返るようにする)。
        """
        from ..ai_client import default_generate_config, get_genai_client

        prompt = self._build_prompt(question, contexts)
        cfg = default_generate_config(max_output_tokens=4096)
        try:
            client = get_genai_client()
            stream_fn = getattr(client.models, "generate_content_stream", None)
            if stream_fn is None:  # SDK が古い等
                yield self.generate(question, contexts)
                return
            if cfg is not None:
                chunks = stream_fn(model=self._model, contents=prompt, config=cfg)
            else:
                chunks = stream_fn(model=self._model, contents=prompt)
            emitted = False
            for chunk in chunks:
                piece = getattr(chunk, "text", "") or ""
                if piece:
                    emitted = True
                    yield piece
            if not emitted:
                # ストリームが空だったら非ストリームで取り直す。
                text = self.generate(question, contexts)
                if text:
                    yield text
        except Exception as e:  # graceful degradation
            logger.warning("generate_stream failed, falling back to non-stream: %s", e)
            text = self.generate(question, contexts)
            if text:
                yield text


# --- Factories (env-selected; default = gemini when AI client available, else fake) ---

def _gemini_available() -> bool:
    from ..ai_client import gemini_available

    return gemini_available()


def _resolve_provider(env_name: str) -> str:
    """Resolve which provider to use for ``env_name``.

    An explicit value (e.g. ``fake`` or ``gemini``) always wins, keeping tests and
    offline use deterministic. When unset, default to ``gemini`` only if an AI
    client is available (Vertex AI enabled or an API key present), otherwise
    ``fake``.
    """
    val = os.getenv(env_name, "").strip().lower()
    if val:
        return val
    return "gemini" if _gemini_available() else "fake"


def get_embedding_provider() -> EmbeddingProvider:
    provider = _resolve_provider("EMBEDDING_PROVIDER")
    if provider == "gemini":
        return GeminiEmbeddingProvider()
    if provider not in ("fake", ""):
        logger.warning("Unknown EMBEDDING_PROVIDER=%s, falling back to fake", provider)
    return FakeEmbeddingProvider()


def get_llm_provider() -> LLMProvider:
    provider = _resolve_provider("LLM_PROVIDER")
    if provider == "gemini":
        return GeminiLLMProvider()
    if provider not in ("fake", ""):
        logger.warning("Unknown LLM_PROVIDER=%s, falling back to fake", provider)
    return FakeLLMProvider()
