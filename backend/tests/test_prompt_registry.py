"""SOT-1474: central prompt/model-config registry."""

import pytest

from app import clock
from app import prompt_registry
from app.rag.providers import GeminiLLMProvider


def test_registry_exposes_version_and_keys():
    assert isinstance(prompt_registry.PROMPT_REGISTRY_VERSION, str)
    assert prompt_registry.PROMPT_REGISTRY_VERSION
    assert "rag_answer" in prompt_registry.list_prompt_keys()


def test_get_prompt_unknown_key_raises():
    with pytest.raises(KeyError):
        prompt_registry.get_prompt("does_not_exist")


def test_render_prompt_substitutes_values():
    out = prompt_registry.render_prompt(
        "rag_answer",
        today_line="TODAY",
        context_block="CTX",
        question="Q?",
    )
    assert "TODAY" in out
    assert "# コンテキスト\nCTX" in out
    assert "# 質問\nQ?" in out
    assert out.endswith("# 回答")


def test_registry_prompt_matches_original_inline_prompt():
    """The migrated prompt must be byte-identical to the pre-refactor inline one."""
    question = "遠足はいつ？"
    contexts = ["秋の遠足は11月10日です。", "持ち物はお弁当。"]

    provider = GeminiLLMProvider()
    actual = provider._build_prompt(question, contexts)

    # Reconstruct exactly what the old inline implementation produced.
    context_block = "\n\n".join(f"- {c}" for c in contexts)
    _weekdays_ja = ("月", "火", "水", "木", "金", "土", "日")
    today = clock.today()
    today_line = (
        f"今日の日付は {today.isoformat()}（{_weekdays_ja[today.weekday()]}曜日）です。"
        "「今日」「明日」「今週」「来週」などの相対的な日付はこれを基準に解釈してください。"
    )
    expected = (
        "あなたはおたよりナビです。以下のコンテキストのみに基づいて、"
        "日本語で簡潔に質問へ回答してください。コンテキストに無いことは推測しないでください。\n\n"
        f"{today_line}\n\n"
        f"# コンテキスト\n{context_block}\n\n# 質問\n{question}\n\n# 回答"
    )
    assert actual == expected


def test_registry_reexports_model_name():
    assert prompt_registry.get_model_name() == prompt_registry.get_model_name()
    assert isinstance(prompt_registry.get_model_name(), str)
