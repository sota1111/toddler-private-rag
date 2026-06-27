"""提出書類先回りエージェントのテスト (SOT-1316 / SOT-1338).

LLM / grounding 呼び出しはすべてモックし、決定的に検証する（ネットワーク不要）。
"""

import datetime
import json

from app import submission_agent, ai_client


SAMPLE = """入園のしおり
健康調査票を5月1日までに提出してください。
就労証明書は2026-05-10までにご提出ください。
運動会は5月20日に開催します。
"""


class _FakeResponse:
    def __init__(self, text):
        self.text = text


class _FakeModels:
    def __init__(self, text):
        self._text = text

    def generate_content(self, *args, **kwargs):
        return _FakeResponse(self._text)


class _FakeClient:
    def __init__(self, text):
        self.models = _FakeModels(text)


def _enrich_json(lead=7, needs=True, source="https://example.go.jp"):
    return json.dumps(
        {
            "steps": ["役所で申請する", "記入して提出する"],
            "needs_company_issuance": needs,
            "lead_time_days": lead,
            "source": source,
        }
    )


# --- extract_submission_documents --------------------------------------------------

def test_extract_documents_happy(monkeypatch):
    monkeypatch.setattr(ai_client, "gemini_available", lambda: True)
    monkeypatch.setattr(
        submission_agent,
        "_llm_extract_documents",
        lambda text, language: [
            {"name": "健康調査票", "due_date": "5月1日"},
            {"name": "就労証明書", "due_date": "2026-05-10"},
        ],
    )
    monkeypatch.setattr(ai_client, "generate_grounded", lambda prompt, **k: _enrich_json())

    docs = submission_agent.extract_submission_documents(SAMPLE, language="ja")
    assert len(docs) == 2
    health = docs[0]
    assert health["name"] == "健康調査票"
    # 5月1日 → 当年 ISO に正規化
    assert health["due_date"].endswith("-05-01")
    assert health["steps"] == ["役所で申請する", "記入して提出する"]
    assert health["needs_company_issuance"] is True
    assert health["lead_time_days"] == 7
    assert health["source"] == "https://example.go.jp"
    assert docs[1]["due_date"] == "2026-05-10"


def test_extract_documents_unavailable_returns_empty(monkeypatch):
    monkeypatch.setattr(ai_client, "gemini_available", lambda: False)
    assert submission_agent.extract_submission_documents(SAMPLE) == []


def test_extract_documents_empty_text(monkeypatch):
    monkeypatch.setattr(ai_client, "gemini_available", lambda: True)
    assert submission_agent.extract_submission_documents("   ") == []


def test_llm_extract_documents_parsing(monkeypatch):
    """実 _llm_extract_documents の JSON 配列パースを、偽クライアントで検証する。"""
    payload = '[{"name":"健康調査票","due_date":"5月1日"},{"name":"","due_date":"x"}]'
    monkeypatch.setattr(ai_client, "get_genai_client", lambda: _FakeClient(payload))
    docs = submission_agent._llm_extract_documents(SAMPLE, "ja")
    # 空 name は除外される
    assert docs == [{"name": "健康調査票", "due_date": "5月1日"}]


def test_grounded_enrich_handles_empty(monkeypatch):
    """grounding が空文字を返しても例外なく既定値を返す。"""
    monkeypatch.setattr(ai_client, "generate_grounded", lambda prompt, **k: "")
    info = submission_agent._grounded_enrich("就労証明書", "ja")
    assert info == {
        "steps": [],
        "needs_company_issuance": None,
        "lead_time_days": None,
        "source": "",
    }


# --- build_submission_task_drafts --------------------------------------------------

def test_build_drafts_backward_calc(monkeypatch):
    monkeypatch.setattr(ai_client, "gemini_available", lambda: True)
    monkeypatch.setattr(
        submission_agent,
        "_llm_extract_documents",
        lambda text, language: [{"name": "就労証明書", "due_date": "2026-05-10"}],
    )
    monkeypatch.setattr(
        ai_client, "generate_grounded", lambda prompt, **k: _enrich_json(lead=7)
    )

    drafts = submission_agent.build_submission_task_drafts(SAMPLE, language="ja")
    assert len(drafts) == 1
    d = drafts[0]
    assert d["info_type"] == "提出物"
    assert d["tags"] == submission_agent.SUBMISSION_TAG
    assert d["due_date"] == "2026-05-10"
    # 逆算: 提出期限 - 所要期間(7日)
    expected = (datetime.date(2026, 5, 10) - datetime.timedelta(days=7)).isoformat()
    assert d["event_date"] == expected
    assert "就労証明書" in d["title"]
    assert "手順" in d["content"]
    # build_task_drafts と同形のキー集合 + due_date/tags
    assert set(d["categories"].keys()) == {"title", *extraction_keys()}


def test_build_drafts_default_buffer_when_lead_unknown(monkeypatch):
    monkeypatch.setattr(ai_client, "gemini_available", lambda: True)
    monkeypatch.setattr(
        submission_agent,
        "_llm_extract_documents",
        lambda text, language: [{"name": "健康調査票", "due_date": "2026-05-10"}],
    )
    monkeypatch.setattr(
        ai_client,
        "generate_grounded",
        lambda prompt, **k: json.dumps(
            {"steps": [], "needs_company_issuance": None, "lead_time_days": None, "source": ""}
        ),
    )
    drafts = submission_agent.build_submission_task_drafts(SAMPLE, language="ja")
    expected = (
        datetime.date(2026, 5, 10)
        - datetime.timedelta(days=submission_agent._DEFAULT_LEAD_DAYS)
    ).isoformat()
    assert drafts[0]["event_date"] == expected


def test_build_drafts_no_due_date_gives_empty_event(monkeypatch):
    monkeypatch.setattr(ai_client, "gemini_available", lambda: True)
    monkeypatch.setattr(
        submission_agent,
        "_llm_extract_documents",
        lambda text, language: [{"name": "口座振替依頼書", "due_date": ""}],
    )
    monkeypatch.setattr(ai_client, "generate_grounded", lambda prompt, **k: "")
    drafts = submission_agent.build_submission_task_drafts(SAMPLE, language="ja")
    assert drafts[0]["due_date"] == ""
    assert drafts[0]["event_date"] == ""


def test_build_drafts_unavailable_returns_empty(monkeypatch):
    monkeypatch.setattr(ai_client, "gemini_available", lambda: False)
    assert submission_agent.build_submission_task_drafts(SAMPLE) == []


def extraction_keys():
    from app import extraction

    return set(extraction.ALL_CONTENT_KEYS)


# --- reminders categorization (SOT-1339) -------------------------------------------

class _FakeInfo:
    def __init__(self, **kw):
        self.id = kw.get("id", 1)
        self.title = kw.get("title", "")
        self.info_type = kw.get("info_type", "提出物")
        self.status = kw.get("status", "未対応")
        self.priority = kw.get("priority", "普通")
        self.due_date = kw.get("due_date")
        self.event_date = kw.get("event_date")
        self.date = kw.get("date")
        self.items = kw.get("items")
        self.tags = kw.get("tags")


def test_reminders_categorizes_submission_kind():
    from app import reminders

    today = datetime.date(2026, 5, 1)
    sub = _FakeInfo(
        id="sub-1",
        title="就労証明書の準備",
        due_date=datetime.date(2026, 5, 3),
        event_date=datetime.date(2026, 5, 1),  # 準備開始日 (重複通知しないこと)
        tags=submission_agent.SUBMISSION_TAG,
    )
    out = reminders.build_reminders([sub], today=today, horizon_days=7)
    # 提出書類は submission kind 1件のみ（event で重複しない）
    assert len(out) == 1
    assert out[0]["kind"] == "submission"
    assert out[0]["urgency"] == "soon"
    assert "就労証明書" in out[0]["message"]


def test_reminders_non_submission_stays_deadline():
    from app import reminders

    today = datetime.date(2026, 5, 1)
    normal = _FakeInfo(
        id=2, title="健康調査票", due_date=datetime.date(2026, 5, 3), tags=None
    )
    out = reminders.build_reminders([normal], today=today, horizon_days=7)
    assert len(out) == 1
    assert out[0]["kind"] == "deadline"
