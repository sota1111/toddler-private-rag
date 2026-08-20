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


def test_registry_prompt_matches_current_contract():
    """The rendered prompt must match the registry template (SOT-2736: +安全制約ブロック)."""
    question = "遠足はいつ？"
    contexts = ["秋の遠足は11月10日です。", "持ち物はお弁当。"]

    provider = GeminiLLMProvider()
    actual = provider._build_prompt(question, contexts)

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
        "# 安全に関する制約\n"
        "- 健康・アレルギー・安全については『安全です』『食べられます』『問題ありません』"
        "『大丈夫です』のような断定をしないでください。安全側の断定も同様に禁止です。"
        "確認が必要な場合は『確認が必要な可能性があります（要確認）』と述べてください。\n"
        "- 最終判断は保護者、専門判断は医療者・園にゆだねる前提で回答してください。\n"
        "- コンテキストに矛盾・相反する記載がある場合は、どちらか一方に断定せず、"
        "両論を併記して『どちらも確認が必要』と伝えてください。\n\n"
        f"{today_line}\n\n"
        f"# コンテキスト\n{context_block}\n\n# 質問\n{question}\n\n# 回答"
    )
    assert actual == expected
    # 安全設計の核（断定禁止・両論提示）がプロンプトに含まれること。
    assert "断定をしないでください" in actual
    assert "両論を併記" in actual


def test_registry_reexports_model_name():
    assert prompt_registry.get_model_name() == prompt_registry.get_model_name()
    assert isinstance(prompt_registry.get_model_name(), str)
