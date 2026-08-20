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
PROMPT_REGISTRY_VERSION = "1.1.0"

# key -> template. Templates use ``str.format`` placeholders. Substituted values
# (user/context text) may contain literal braces safely — only the template's own
# ``{...}`` placeholders are interpreted.
_PROMPTS = {
    # RAG /ask answer prompt (migrated from app/rag/providers.py, SOT-1474).
    "rag_answer": (
        "あなたはおたよりナビです。以下のコンテキストのみに基づいて、"
        "日本語で簡潔に質問へ回答してください。コンテキストに無いことは推測しないでください。\n\n"
        # SOT-2736: 健康・安全に関する安全設計。誤った安心を与えない。
        "# 安全に関する制約\n"
        "- 健康・アレルギー・安全については『安全です』『食べられます』『問題ありません』"
        "『大丈夫です』のような断定をしないでください。安全側の断定も同様に禁止です。"
        "確認が必要な場合は『確認が必要な可能性があります（要確認）』と述べてください。\n"
        "- 最終判断は保護者、専門判断は医療者・園にゆだねる前提で回答してください。\n"
        "- コンテキストに矛盾・相反する記載がある場合は、どちらか一方に断定せず、"
        "両論を併記して『どちらも確認が必要』と伝えてください。\n\n"
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
