"""5カテゴリ構造化抽出のテスト (SOT-1085 / SOT-1092)。

ヒューリスティック経路のみを検証する（テスト環境では Gemini 非利用なので決定的）。
"""

from app import extraction
from app.schemas import ExtractedCategories, InfoExtractDraft

SAMPLE = """運動会のお知らせ
5月10日に運動会を開催します。
持ち物
・水筒
・タオル
健康調査票を提出してください。
申込書は5月1日までにご提出ください。
注意: 車での来園は禁止です。
"""


def test_extract_categories_has_all_five_keys():
    result = extraction.extract_categories(SAMPLE)
    assert set(result.keys()) == set(extraction.CATEGORY_KEYS)


def test_extract_categories_detects_each_category():
    result = extraction.extract_categories(SAMPLE)
    assert any("運動会" in e for e in result["events"])
    assert any("水筒" in b or "タオル" in b for b in result["belongings"])
    assert any("提出" in s for s in result["submissions"]) or any(
        "提出" in d for d in result["deadlines"]
    )
    assert any("禁止" in n or "注意" in n for n in result["notes"])


def test_extract_categories_empty_text_is_safe():
    result = extraction.extract_categories("")
    assert result == {k: [] for k in extraction.CATEGORY_KEYS}


def test_extracted_categories_schema_default():
    draft = InfoExtractDraft(title="t", info_type="お知らせ", content="c")
    assert isinstance(draft.categories, ExtractedCategories)
    assert draft.categories.notes == []
