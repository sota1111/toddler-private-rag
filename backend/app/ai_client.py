"""Shared Gemini / Vertex AI client factory (google-genai SDK).

Prefers Vertex AI mode (Cloud Run service-account ADC) when
``GOOGLE_GENAI_USE_VERTEXAI`` is truthy; otherwise falls back to API-key mode for
local development. The legacy Google AI Studio SDK path is no longer used.

Environment variables:
- ``GOOGLE_GENAI_USE_VERTEXAI`` — truthy → Vertex AI mode (no API key needed).
- ``GOOGLE_CLOUD_PROJECT``     — default ``gen-lang-client-0243034020``.
- ``GOOGLE_CLOUD_LOCATION``    — default ``global``.
- ``GEMINI_MODEL``             — default ``gemini-3.5-flash``.
- ``GEMINI_API_KEY`` / ``GOOGLE_API_KEY`` — only used in local API-key fallback.
"""

import logging
import os
import time
from typing import Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

DEFAULT_PROJECT = "gen-lang-client-0243034020"
DEFAULT_LOCATION = "global"
DEFAULT_MODEL = "gemini-3.5-flash"

_logged_init = False


def use_vertex() -> bool:
    """Whether Vertex AI mode is enabled via ``GOOGLE_GENAI_USE_VERTEXAI``."""
    return os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def get_model_name() -> str:
    """Resolve the generative model name (``GEMINI_MODEL`` preferred)."""
    return os.getenv("GEMINI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


def _api_key() -> Optional[str]:
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")


def gemini_available() -> bool:
    """True when an AI client can be constructed (Vertex on, or an API key set)."""
    return use_vertex() or bool(_api_key())


def _log_init(vertex: bool, project: str, location: str, model: str) -> None:
    global _logged_init
    if _logged_init:
        return
    _logged_init = True
    if vertex:
        logger.info(
            "AI client: Vertex AI mode ENABLED (project=%s, location=%s, model=%s)",
            project,
            location,
            model,
        )
    else:
        logger.warning(
            "AI client: Vertex AI DISABLED, falling back to API-key mode (model=%s)",
            model,
        )


def get_genai_client():
    """Return a configured ``google.genai`` Client.

    Vertex mode uses Application Default Credentials (Cloud Run service account);
    no API key is read or logged. Otherwise an API-key client is built for local
    dev. Raises ``RuntimeError`` when neither is available.
    """
    from google import genai  # lazy import so importing this module never fails

    project = os.getenv("GOOGLE_CLOUD_PROJECT", DEFAULT_PROJECT)
    location = os.getenv("GOOGLE_CLOUD_LOCATION", DEFAULT_LOCATION)
    model = get_model_name()

    if use_vertex():
        _log_init(True, project, location, model)
        return genai.Client(vertexai=True, project=project, location=location)

    key = _api_key()
    if key:
        _log_init(False, project, location, model)
        return genai.Client(api_key=key)

    raise RuntimeError(
        "No AI client available: set GOOGLE_GENAI_USE_VERTEXAI=true to use Vertex AI "
        "(Cloud Run service account), or GEMINI_API_KEY for local API-key mode."
    )


def default_generate_config(max_output_tokens: int = 2048):
    """Return a ``GenerateContentConfig`` that disables model "thinking".

    思考(thinking)が既定で有効な Gemini 2.5/3 系では、タイトル整形・カテゴリ抽出・本文整理
    などの生成呼び出しが 1 回あたり十数秒かかり、複数を直列実行する ``/info/extract`` が
    Cloud Run のリクエスト上限(300秒)を超えてタイムアウトし、OCR後の整理(enrich)が失敗する
    (SOT-1292)。OCR 呼び出し(ocr.py)と同様に思考を無効化し、出力上限を明示して高速化する。

    SDK 差異で ``types`` が利用できない場合は ``None`` を返し、呼び出し側は config なしで続行する。
    """
    try:
        from google.genai import types

        return types.GenerateContentConfig(
            max_output_tokens=max_output_tokens,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )
    except Exception:  # SDK 差異で types/ThinkingConfig が無い場合は設定なしで続行
        return None


T = TypeVar("T")


def _is_quota_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(
        k in msg
        for k in ("429", "quota", "rate limit", "rate-limit", "resource_exhausted")
    )


def with_retry(fn: Callable[[], T], *, attempts: int = 3, base_delay: float = 1.0) -> T:
    """Run ``fn`` with bounded exponential backoff on Vertex AI quota/429 errors.

    Non-quota errors propagate immediately. After the final attempt a quota error
    is re-raised as a ``RuntimeError`` whose message points at Vertex AI quota
    (not AI Studio free tier). Never retries indefinitely.
    """
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            if not _is_quota_error(exc):
                raise
            if i < attempts - 1:
                time.sleep(base_delay * (2 ** i))
                continue
            raise RuntimeError(
                "AI request failed due to Vertex AI quota / rate limits (429). "
                "Please retry later or request a Vertex AI quota increase."
            ) from exc
    raise RuntimeError("with_retry exhausted without result")  # pragma: no cover
