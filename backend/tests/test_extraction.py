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


def test_extract_categories_has_all_content_keys():
    # 5カテゴリ＋その他 (SOT-1294)
    result = extraction.extract_categories(SAMPLE)
    assert set(result.keys()) == set(extraction.ALL_CONTENT_KEYS)


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
    assert result == {k: [] for k in extraction.ALL_CONTENT_KEYS}


def test_unclassified_lines_go_to_other_and_appear_in_content():
    # どのカテゴリにも当てはまらない行は「その他」に収容され、構造化contentに残る (SOT-1294)。
    text = "本日は園庭で自由遊びを行いました。\n駐車場は北側をご利用ください。"
    result = extraction.extract_categories(text)
    assert result["other"], "未分類行が other に入っていない"
    structured = extraction.build_structured_content(result)
    assert "【その他】" in structured
    assert "駐車場は北側" in structured


def test_extracted_categories_schema_default():
    draft = InfoExtractDraft(title="t", info_type="お知らせ", content="c")
    assert isinstance(draft.categories, ExtractedCategories)
    assert draft.categories.notes == []


# --- 文字起こしの整理 (SOT-1214) ---
# テスト環境では Gemini 非利用なので organize_content は決定的なヒューリスティック整形になる。


def test_organize_content_empty_returns_empty():
    assert extraction.organize_content("") == ""
    assert extraction.organize_content("   \n  \n") == ""


def test_organize_content_collapses_blank_lines_and_trims():
    raw = "  運動会のお知らせ  \n\n\n\n5月10日に開催します。\n\n"
    organized = extraction.organize_content(raw, categories={k: [] for k in extraction.CATEGORY_KEYS})
    # 前後の空白除去・連続空行が1つに圧縮され、末尾の空行も除去される
    assert organized == "運動会のお知らせ\n\n5月10日に開催します。"


def test_organize_content_appends_category_section():
    raw = "運動会のお知らせ"
    categories = {
        "submissions": ["健康調査票"],
        "belongings": ["水筒", "タオル"],
        "deadlines": [],
        "events": [],
        "notes": ["車での来園は禁止"],
    }
    organized = extraction.organize_content(raw, categories=categories)
    assert organized.startswith("運動会のお知らせ")
    # 空でないカテゴリのみ見出し付き箇条書きで付与される
    assert "【提出物】" in organized
    assert "・健康調査票" in organized
    assert "【持ち物】" in organized
    assert "・水筒" in organized and "・タオル" in organized
    assert "【注意事項】" in organized and "・車での来園は禁止" in organized
    # 空カテゴリの見出しは出さない
    assert "【締切】" not in organized
    assert "【行事予定】" not in organized


def test_organize_content_no_categories_returns_body_only():
    raw = "おしらせ\n本文です"
    organized = extraction.organize_content(raw, categories={k: [] for k in extraction.CATEGORY_KEYS})
    assert organized == "おしらせ\n本文です"
    assert "【" not in organized


# --- build_task_drafts (SOT-1307) ---
# テスト環境では Gemini 非利用なので、タスク分割は単一 draft へフォールバックする（決定的）。

_TASK_DRAFT_KEYS = {"title", "info_type", "content", "items", "date", "event_date", "categories"}


def test_build_task_drafts_falls_back_to_single_draft_offline():
    drafts = extraction.build_task_drafts(SAMPLE)
    # オフライン(LLM不可)では1件にフォールバックする（後方互換）
    assert isinstance(drafts, list)
    assert len(drafts) == 1
    draft = drafts[0]
    # build_draft_fields と同形のキー集合 ＋ event_date を必ず持つ
    assert _TASK_DRAFT_KEYS.issubset(set(draft.keys()))
    assert "event_date" in draft
    assert draft["info_type"] in extraction.INFO_TYPES


def test_build_task_drafts_empty_text_is_safe():
    drafts = extraction.build_task_drafts("")
    assert len(drafts) == 1
    assert "event_date" in drafts[0]


# --- 設定言語でのタスク登録 (SOT-1315) ---


def _patch_fake_genai(monkeypatch, captured):
    """``_llm_tasks`` が使う genai クライアントをプロンプト捕捉用に差し替える。"""

    class _FakeModels:
        def generate_content(self, model, contents, config=None):
            captured["prompt"] = contents

            class _R:
                text = "[]"

            return _R()

    class _FakeClient:
        models = _FakeModels()

    monkeypatch.setattr(extraction.ai_client, "get_genai_client", lambda: _FakeClient())
    monkeypatch.setattr(extraction.ai_client, "get_model_name", lambda: "fake-model")
    monkeypatch.setattr(extraction.ai_client, "default_generate_config", lambda: None)
    monkeypatch.setattr(extraction.ai_client, "with_retry", lambda fn: fn())


def test_llm_tasks_includes_language_instruction(monkeypatch):
    captured = {}
    _patch_fake_genai(monkeypatch, captured)

    extraction._llm_tasks("運動会のお知らせ", "en")
    assert "English" in captured["prompt"]

    extraction._llm_tasks("運動会のお知らせ", "ja")
    assert "日本語" in captured["prompt"]


def test_llm_tasks_defaults_to_japanese(monkeypatch):
    captured = {}
    _patch_fake_genai(monkeypatch, captured)

    extraction._llm_tasks("運動会のお知らせ")  # language 省略
    assert "日本語" in captured["prompt"]


def test_build_task_drafts_forwards_language(monkeypatch):
    seen = {}
    monkeypatch.setattr(extraction.ai_client, "gemini_available", lambda: True)

    def _fake_llm_tasks(text, language="ja"):
        seen["language"] = language
        return []  # 空 → 単一 draft フォールバック（言語伝播のみ検証）

    monkeypatch.setattr(extraction, "_llm_tasks", _fake_llm_tasks)

    extraction.build_task_drafts("運動会のお知らせ", language="en")
    assert seen["language"] == "en"


# --- 設定言語でのタイトル生成 (SOT-1336) ---


def _patch_fake_genai_obj(monkeypatch, captured):
    """``_llm_categories`` 用: JSONオブジェクトを返す genai クライアントに差し替える。"""

    class _FakeModels:
        def generate_content(self, model, contents, config=None):
            captured["prompt"] = contents

            class _R:
                text = "{}"

            return _R()

    class _FakeClient:
        models = _FakeModels()

    monkeypatch.setattr(extraction.ai_client, "get_genai_client", lambda: _FakeClient())
    monkeypatch.setattr(extraction.ai_client, "get_model_name", lambda: "fake-model")
    monkeypatch.setattr(extraction.ai_client, "default_generate_config", lambda: None)
    monkeypatch.setattr(extraction.ai_client, "with_retry", lambda fn: fn())


def test_llm_categories_title_language_instruction(monkeypatch):
    captured = {}
    _patch_fake_genai_obj(monkeypatch, captured)

    extraction._llm_categories("運動会のお知らせ", "en")
    assert "English" in captured["prompt"]

    extraction._llm_categories("運動会のお知らせ", "ja")
    assert "日本語" in captured["prompt"]


def test_llm_categories_title_defaults_to_japanese(monkeypatch):
    captured = {}
    _patch_fake_genai_obj(monkeypatch, captured)

    extraction._llm_categories("運動会のお知らせ")  # language 省略
    assert "日本語" in captured["prompt"]


def test_extract_titled_categories_forwards_language(monkeypatch):
    seen = {}
    monkeypatch.setattr(extraction.ai_client, "gemini_available", lambda: True)

    def _fake_llm_categories(text, language="ja"):
        seen["language"] = language
        return {"title": "x"}

    monkeypatch.setattr(extraction, "_llm_categories", _fake_llm_categories)

    extraction.extract_titled_categories("運動会のお知らせ", "en")
    assert seen["language"] == "en"


def test_build_draft_fields_forwards_language(monkeypatch):
    seen = {}

    def _fake_extract(text, language="ja"):
        seen["language"] = language
        return {"title": "x"}

    monkeypatch.setattr(extraction, "extract_titled_categories", _fake_extract)

    extraction.build_draft_fields("運動会のお知らせ", None, None, language="en")
    assert seen["language"] == "en"
