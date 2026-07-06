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


# --- 同一日・同一イベントのタスク統合 (SOT-1350) ---


def test_consolidate_tasks_merges_same_date_same_event():
    tasks = [
        {"title": "七夕会のお願いごと", "date": "2026-07-07", "detail": "短冊にお願いごとを書いてください", "category": "notes"},
        {"title": "七夕会", "date": "2026-07-07", "detail": "7月7日に七夕会を行います", "category": "events"},
        {"title": "水あそびの持ち物", "date": "2026-07-12", "detail": "水着とタオルを持参", "category": "belongings"},
        {"title": "水あそび開始", "date": "2026-07-12", "detail": "7月12日から水あそびを始めます", "category": "events"},
        {"title": "お誕生日会の服装", "date": "2026-07-17", "detail": "私服で参加", "category": "belongings"},
        {"title": "お誕生日会", "date": "2026-07-17", "detail": "7月17日にお誕生日会を開催", "category": "events"},
    ]
    merged = extraction._consolidate_tasks(tasks)
    # 3イベントに統合される
    assert len(merged) == 3
    by_date = {t["date"]: t for t in merged}
    # events 優先で category=events、title はイベント名
    assert by_date["2026-07-07"]["category"] == "events"
    assert by_date["2026-07-07"]["title"] == "七夕会"
    # detail に両方の情報が含まれる
    assert "お願いごと" in by_date["2026-07-07"]["detail"]
    assert "七夕会を行います" in by_date["2026-07-07"]["detail"]
    assert by_date["2026-07-12"]["category"] == "events"
    assert "水着" in by_date["2026-07-12"]["detail"]
    assert by_date["2026-07-17"]["category"] == "events"
    assert "私服" in by_date["2026-07-17"]["detail"]


def test_consolidate_tasks_does_not_merge_different_dates():
    tasks = [
        {"title": "七夕会", "date": "2026-07-07", "detail": "七夕会", "category": "events"},
        {"title": "七夕会の準備", "date": "2026-07-06", "detail": "前日準備", "category": "events"},
    ]
    merged = extraction._consolidate_tasks(tasks)
    assert len(merged) == 2  # 日付が違えばマージしない


def test_consolidate_tasks_does_not_merge_unrelated_titles():
    tasks = [
        {"title": "運動会", "date": "2026-07-07", "detail": "運動会", "category": "events"},
        {"title": "面談のお知らせ", "date": "2026-07-07", "detail": "面談", "category": "notes"},
    ]
    merged = extraction._consolidate_tasks(tasks)
    assert len(merged) == 2  # 共通接頭辞が短い無関係タイトルはマージしない


def test_consolidate_tasks_never_merges_empty_dates():
    tasks = [
        {"title": "七夕会", "date": "", "detail": "七夕会その1", "category": "events"},
        {"title": "七夕会のお願い", "date": "", "detail": "七夕会その2", "category": "notes"},
    ]
    merged = extraction._consolidate_tasks(tasks)
    assert len(merged) == 2  # 日付不明同士は同一日と確認できないためマージしない


def test_build_task_drafts_consolidates_via_llm(monkeypatch):
    monkeypatch.setattr(extraction.ai_client, "gemini_available", lambda: True)

    def _fake_llm_tasks(text, language="ja"):
        return [
            {"title": "七夕会のお願いごと", "date": "2026-07-07", "detail": "短冊", "category": "notes"},
            {"title": "七夕会", "date": "2026-07-07", "detail": "七夕会を行います", "category": "events"},
        ]

    monkeypatch.setattr(extraction, "_llm_tasks", _fake_llm_tasks)
    drafts = extraction.build_task_drafts("七夕会のおたより", language="ja")
    assert len(drafts) == 1  # 同一日・同一イベントは1 draft に統合
    assert drafts[0]["info_type"] == "行事"
    assert _TASK_DRAFT_KEYS.issubset(set(drafts[0].keys()))


def test_llm_tasks_prompt_includes_same_event_merge_instruction(monkeypatch):
    captured = {}
    _patch_fake_genai(monkeypatch, captured)
    extraction._llm_tasks("七夕会のおたより", "ja")
    assert "SAME event" in captured["prompt"]


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


# --- SOT-1407: 締め切り調査が必要かのフラグ -----------------------------------
def test_needs_deadline_investigation_submission_type():
    # info_type が「提出物」なら常に True。
    assert extraction.needs_deadline_investigation("提出物", "") is True


def test_needs_deadline_investigation_keyword():
    # 提出書類系キーワード（証明書/提出 等）を含む本文は True。
    assert extraction.needs_deadline_investigation("お知らせ", "就労証明書の提出") is True
    assert extraction.needs_deadline_investigation("お知らせ", "Please submit the form") is True


def test_needs_deadline_investigation_generic_notice_false():
    # 提出と無関係なお知らせは False。
    assert extraction.needs_deadline_investigation("行事", "明日は運動会です") is False


def test_task_to_draft_sets_needs_deadline_investigation():
    task = {"title": "就労証明書の提出", "detail": "勤務先で記入してもらう", "category": "submissions"}
    draft = extraction._task_to_draft(task, "")
    assert draft["needs_deadline_investigation"] is True

    task2 = {"title": "運動会", "detail": "5月10日開催", "category": "events"}
    draft2 = extraction._task_to_draft(task2, "")
    assert draft2["needs_deadline_investigation"] is False


def test_build_draft_fields_includes_needs_deadline_investigation():
    fields = extraction.build_draft_fields("健康調査票を提出してください", None, None)
    assert "needs_deadline_investigation" in fields
    assert fields["needs_deadline_investigation"] is True


# --- SOT-1577: 分割前のタスクに戻す（merge_split_drafts_to_single）--------------
def test_merge_split_drafts_ignores_source_content():
    # SOT-1577 REOPEN#2: source（元書類=全写真の文字起こし）本文があっても content には採用せず、
    # 分割タスク群自身の本文から復元する（「戻す」で全写真分が出るのを防ぐ）。title / info_type は source を優先。
    drafts = [
        {"title": "水筒を用意", "info_type": "持ち物", "content": "水筒", "items": "水筒", "date": "2026-05-10", "event_date": "2026-05-10"},
        {"title": "タオルを用意", "info_type": "持ち物", "content": "タオル", "items": "タオル", "date": "2026-05-09", "event_date": "2026-05-09"},
    ]
    source = {"title": "運動会のお知らせ", "info_type": "行事", "content": "運動会の書類全文", "items": "", "date": "", "event_date": ""}
    merged = extraction.merge_split_drafts_to_single(drafts, source)
    # content は書類全文ではなく分割タスク群の本文連結。
    assert merged["content"] == "水筒\n\nタオル"
    assert "運動会の書類全文" not in merged["content"]
    # title / info_type は source を優先。
    assert merged["title"] == "運動会のお知らせ"
    assert merged["info_type"] == "行事"
    # 最も早い非空の日付を採用する。
    assert merged["date"] == "2026-05-09"
    assert merged["event_date"] == "2026-05-09"
    # items は重複なく出現順に連結。
    assert merged["items"] == "水筒\nタオル"


def test_is_deadline_companion_distinguishes_companion_from_split():
    # SOT-1577 REOPEN#2: 締切グループがあり offset≠0 の付随タスクのみ True。
    # 通常の分割タスク（group なし）・締切グループのアンカー（offset 0）は False（＝実タスク）。
    assert extraction.is_deadline_companion(
        {"deadline_group_id": "g1", "deadline_offset_days": -7}
    ) is True
    # offset 未設定でも締切グループに属していれば付随タスク扱い。
    assert extraction.is_deadline_companion(
        {"deadline_group_id": "g1", "deadline_offset_days": None}
    ) is True
    # 締切グループのアンカー（元タスク, offset 0）は実タスク。
    assert extraction.is_deadline_companion(
        {"deadline_group_id": "g1", "deadline_offset_days": 0}
    ) is False
    # 締切グループなし（通常の分割タスク）は実タスク。
    assert extraction.is_deadline_companion(
        {"deadline_group_id": None, "deadline_offset_days": None}
    ) is False
    assert extraction.is_deadline_companion({}) is False


def test_merge_split_drafts_concatenates_content_without_source():
    # source が無い場合は各タスク本文を出現順に重複なく連結する。
    drafts = [
        {"title": "A", "info_type": "持ち物", "content": "水筒", "items": "水筒", "date": "", "event_date": ""},
        {"title": "B", "info_type": "持ち物", "content": "タオル", "items": "水筒", "date": "", "event_date": ""},
        {"title": "C", "info_type": "持ち物", "content": "水筒", "items": "", "date": "", "event_date": ""},
    ]
    merged = extraction.merge_split_drafts_to_single(drafts)
    assert merged["content"] == "水筒\n\nタオル"
    # items も重複除去（水筒は1回だけ）。
    assert merged["items"] == "水筒"
    # title は先頭 draft を継承（source 無し）。
    assert merged["title"] == "A"


def test_merge_split_drafts_keys_match_draft_shape():
    merged = extraction.merge_split_drafts_to_single([
        {"title": "t", "info_type": "資料", "content": "c", "items": "", "date": "", "event_date": ""},
    ])
    assert set(merged.keys()) == {"title", "info_type", "content", "items", "date", "event_date"}


def test_merge_split_drafts_falls_back_info_type():
    # 不正な info_type は "資料" にフォールバックする。
    merged = extraction.merge_split_drafts_to_single([
        {"title": "t", "info_type": "存在しない種別", "content": "本文", "items": "", "date": "", "event_date": ""},
    ])
    assert merged["info_type"] == "資料"
