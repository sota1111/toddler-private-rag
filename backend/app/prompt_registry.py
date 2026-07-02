"""Central prompt & model-config registry (SOT-1474).

A single place to view and version the prompts and model settings the agent uses,
so changes are auditable. The human-readable change history lives in
``docs/prompt-registry.md``.

Prompts are migrated here incrementally to avoid regressions: call sites read
templates via :func:`render_prompt` / :func:`get_prompt` instead of hard-coding
them inline. Model name / config resolution stays in :mod:`app.ai_client` and is
re-exported here so there is one import surface for "what model & prompts do we use".
"""

from typing import List

from .ai_client import get_model_name  # re-export: single config surface

__all__ = [
    "PROMPT_REGISTRY_VERSION",
    "get_prompt",
    "render_prompt",
    "list_prompt_keys",
    "get_model_name",
]

# Bump on any prompt change; record the change in docs/prompt-registry.md.
PROMPT_REGISTRY_VERSION = "1.0.0"

# key -> template. Templates use ``str.format`` placeholders. Substituted values
# (user/context text) may contain literal braces safely — only the template's own
# ``{...}`` placeholders are interpreted.
_PROMPTS = {
    # RAG /ask answer prompt (migrated from app/rag/providers.py, SOT-1474).
    "rag_answer": (
        "あなたはおたよりナビです。以下のコンテキストのみに基づいて、"
        "日本語で簡潔に質問へ回答してください。コンテキストに無いことは推測しないでください。\n\n"
        "{today_line}\n\n"
        "# コンテキスト\n{context_block}\n\n# 質問\n{question}\n\n# 回答"
    ),
}


def get_prompt(key: str) -> str:
    """Return the raw prompt template for ``key`` (raises ``KeyError`` if unknown)."""
    return _PROMPTS[key]


def render_prompt(key: str, **kwargs) -> str:
    """Return the prompt for ``key`` with ``kwargs`` substituted."""
    return get_prompt(key).format(**kwargs)


def list_prompt_keys() -> List[str]:
    """Return all registered prompt keys (sorted)."""
    return sorted(_PROMPTS)
