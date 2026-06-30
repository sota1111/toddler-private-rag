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

# 日付を一切含まないおたより本文（締切アンカーが見つからない＝前向きフォールバック検証用）。
SAMPLE_NO_DATES = """入園のしおり
在籍証明書を提出してください。会社/勤務先の発行が必要です。
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
            "steps": [
                {"name": "役所で申請する", "lead_time_days": 2},
                {"name": "記入して提出する", "lead_time_days": 5},
            ],
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
    monkeypatch.setattr(
        ai_client,
        "generate_grounded_with_sources",
        lambda prompt, **k: (_enrich_json(), []),
    )

    docs = submission_agent.extract_submission_documents(SAMPLE, language="ja")
    assert len(docs) == 2
    health = docs[0]
    assert health["name"] == "健康調査票"
    # 5月1日 → 当年 ISO に正規化
    assert health["due_date"].endswith("-05-01")
    assert health["steps"] == [
        {"name": "役所で申請する", "lead_time_days": 2},
        {"name": "記入して提出する", "lead_time_days": 5},
    ]
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
    monkeypatch.setattr(
        ai_client, "generate_grounded_with_sources", lambda prompt, **k: ("", [])
    )
    info = submission_agent._grounded_enrich("就労証明書", "ja")
    assert info == {
        "steps": [],
        "needs_company_issuance": None,
        "lead_time_days": None,
        "source": "",
        "sources": [],
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
        ai_client,
        "generate_grounded_with_sources",
        lambda prompt, **k: (_enrich_json(lead=7), []),
    )

    drafts = submission_agent.build_submission_task_drafts(SAMPLE, language="ja")
    # 手順ごとに分割: 2 手順 → 2 タスク
    assert len(drafts) == 2
    for d in drafts:
        assert d["info_type"] == "提出物"
        assert d["tags"] == submission_agent.SUBMISSION_TAG
        assert "就労証明書" in d["title"]
        # build_task_drafts と同形のキー集合 + due_date/tags
        assert set(d["categories"].keys()) == {"title", *extraction_keys()}
    # タイトルに何番目/全何ステップが入る（例: 就労証明書(1/2) ...）
    assert drafts[0]["title"].startswith("就労証明書(1/2)")
    assert drafts[1]["title"].startswith("就労証明書(2/2)")
    # 後ろ向き逆算: 記入して提出(5日)=5/5, 役所で申請(2日)=5/3（実行順で返る）
    assert drafts[0]["due_date"] == "2026-05-03"
    assert drafts[0]["event_date"] == "2026-05-03"
    assert drafts[1]["due_date"] == "2026-05-05"
    # 各タスク本文に手順位置と所要期間の目安（平均日数の注意事項）が入る
    assert "手順 1/2" in drafts[0]["content"]
    assert "所要期間の目安" in drafts[0]["content"]


def test_build_drafts_per_step_backward_chain(monkeypatch):
    """Issue 例: 期限 7/30、4 手順を後ろ向きに逆算して手順ごとに分割する。"""
    monkeypatch.setattr(ai_client, "gemini_available", lambda: True)
    monkeypatch.setattr(
        submission_agent,
        "_llm_extract_documents",
        lambda text, language: [{"name": "在籍証明書", "due_date": "2026-07-30"}],
    )
    enrich = json.dumps(
        {
            "steps": [
                {"name": "テンプレート入手", "lead_time_days": 3},
                {"name": "証明書発行", "lead_time_days": 14},
                {"name": "誤り確認", "lead_time_days": 1},
                {"name": "市町村に提出", "lead_time_days": 3},
            ],
            "needs_company_issuance": True,
            "lead_time_days": None,
            "source": "https://example.go.jp",
        }
    )
    monkeypatch.setattr(
        ai_client, "generate_grounded_with_sources", lambda prompt, **k: (enrich, [])
    )

    drafts = submission_agent.build_submission_task_drafts(SAMPLE, language="ja")
    assert len(drafts) == 4
    # 実行順 + 後ろ向き逆算の締切（テンプレ3/発行14/確認1/提出3 を 7/30 から逆算）
    assert [d["due_date"] for d in drafts] == [
        "2026-07-09",
        "2026-07-12",
        "2026-07-26",
        "2026-07-27",
    ]
    for i, d in enumerate(drafts):
        assert d["event_date"] == d["due_date"]
        assert f"手順 {i + 1}/4" in d["content"]
        assert "所要期間の目安" in d["content"]
        assert "最終提出期限: 2026-07-30" in d["content"]
    # タイトルに「書類名(何番目/全数) 手順名」が入る（Issue 例: 在籍証明書(1/5) サブタイトル）
    assert drafts[0]["title"] == "在籍証明書(1/4) テンプレート入手"
    assert drafts[3]["title"] == "在籍証明書(4/4) 市町村に提出"


def test_step_subtitle_shortens_long_step_name():
    """長い動作文の手順名は最初の区切りまで＋字数上限で簡潔な見出しにする（SOT-1402 再オープン）。"""
    # 既に簡潔な手順名はそのまま
    assert submission_agent._step_subtitle("テンプレート入手") == "テンプレート入手"
    # 「、」区切りの先頭句だけを採用し、長ければ末尾に「…」
    sub = submission_agent._step_subtitle(
        "勤務先（会社の人事や総務担当部署）に様式を提出し、証明書の記入・発行を依頼する"
    )
    assert sub.endswith("…")
    assert "、" not in sub
    assert len(sub) <= 19  # limit(18) + ellipsis


def test_build_drafts_long_step_name_title_not_truncated_midsentence(monkeypatch):
    """手順名が長文でもタイトルは途中切れの本文ではなく簡潔なサブタイトルになる（SOT-1402 再オープン）。"""
    monkeypatch.setattr(ai_client, "gemini_available", lambda: True)
    monkeypatch.setattr(
        submission_agent,
        "_llm_extract_documents",
        lambda text, language: [{"name": "会社の在籍証明書", "due_date": "2026-07-30"}],
    )
    enrich = json.dumps(
        {
            "steps": [
                {"name": "勤務先に様式の発行を依頼する", "lead_time_days": 2},
                {
                    "name": "勤務先（会社の人事や総務担当部署）に様式を提出し、証明書の記入・発行を依頼する",
                    "lead_time_days": 1,
                },
            ],
            "needs_company_issuance": True,
            "lead_time_days": None,
            "source": "",
        }
    )
    monkeypatch.setattr(
        ai_client, "generate_grounded_with_sources", lambda prompt, **k: (enrich, [])
    )

    drafts = submission_agent.build_submission_task_drafts(SAMPLE, language="ja")
    assert len(drafts) == 2
    # サブタイトルは長文の途中切れにならない（「、」で切れた本文ではない）
    assert drafts[1]["title"].startswith("会社の在籍証明書(2/2) ")
    assert "、" not in drafts[1]["title"]
    # 手順名フルは本文に残るので情報は失われない
    assert "様式を提出し、証明書の記入・発行を依頼する" in drafts[1]["content"]


def test_step_deadlines_forward_when_due_unknown(monkeypatch):
    """最終期限が不明な場合、本日起点で各手順の所要日数を前向きに累積して締切を割り当てる。"""
    monkeypatch.setattr(
        submission_agent, "_today", lambda: datetime.date(2026, 6, 30)
    )
    steps = [
        {"name": "テンプレート入手", "lead_time_days": 3},
        {"name": "証明書発行", "lead_time_days": 14},
        {"name": "誤り確認", "lead_time_days": 1},
        {"name": "市町村に提出", "lead_time_days": 3},
    ]
    result = submission_agent._step_deadlines("", steps, None)
    # 本日 6/30 起点で前向き累積: +3, +14, +1, +3
    assert [r["due_iso"] for r in result] == [
        "2026-07-03",
        "2026-07-17",
        "2026-07-18",
        "2026-07-21",
    ]


def test_build_drafts_forward_schedule_when_no_due(monkeypatch):
    """書類にも本文にも日付が無いときだけ、本日起点の前向き締切でフォールバックする。"""
    monkeypatch.setattr(ai_client, "gemini_available", lambda: True)
    monkeypatch.setattr(
        submission_agent, "_today", lambda: datetime.date(2026, 6, 30)
    )
    monkeypatch.setattr(
        submission_agent,
        "_llm_extract_documents",
        lambda text, language: [{"name": "在籍証明書", "due_date": ""}],
    )
    enrich = json.dumps(
        {
            "steps": [
                {"name": "テンプレート入手", "lead_time_days": 3},
                {"name": "証明書発行", "lead_time_days": 14},
                {"name": "誤り確認", "lead_time_days": 1},
                {"name": "市町村に提出", "lead_time_days": 3},
            ],
            "needs_company_issuance": True,
            "lead_time_days": None,
            "source": "https://example.go.jp",
        }
    )
    monkeypatch.setattr(
        ai_client, "generate_grounded_with_sources", lambda prompt, **k: (enrich, [])
    )

    # SAMPLE_NO_DATES は日付を含まないため、アンカーが無く前向きフォールバックになる。
    drafts = submission_agent.build_submission_task_drafts(SAMPLE_NO_DATES, language="ja")
    assert len(drafts) == 4
    # 期限が一切無いときは各やることに本日起点の具体的な日付が登録される（空でない）
    assert [d["due_date"] for d in drafts] == [
        "2026-07-03",
        "2026-07-17",
        "2026-07-18",
        "2026-07-21",
    ]
    for d in drafts:
        assert d["event_date"] == d["due_date"]
        assert d["due_date"]  # 空文字でない
        assert "この手順の締切" in d["content"]


def test_build_drafts_backward_from_text_date_when_doc_due_empty(monkeypatch):
    """SOT-1399 3rd: 書類に締切が紐づかなくても、本文の最終締切から各手順を後ろ向きに逆算する。

    再オープン「前向きの期限が設定される」への対応。本文に 2026-07-31 があるのに LLM が
    書類へ締切を紐づけられない場合、前向き累積ではなく 7/31 を最終提出期限として逆算する。
    """
    monkeypatch.setattr(ai_client, "gemini_available", lambda: True)
    monkeypatch.setattr(
        submission_agent, "_today", lambda: datetime.date(2026, 6, 30)
    )
    monkeypatch.setattr(
        submission_agent,
        "_llm_extract_documents",
        lambda text, language: [{"name": "在籍証明書", "due_date": ""}],
    )
    enrich = json.dumps(
        {
            "steps": [
                {"name": "テンプレート入手", "lead_time_days": 3},
                {"name": "証明書発行", "lead_time_days": 14},
                {"name": "誤り確認", "lead_time_days": 1},
                {"name": "市町村に提出", "lead_time_days": 3},
            ],
            "needs_company_issuance": True,
            "lead_time_days": None,
            "source": "https://example.go.jp",
        }
    )
    monkeypatch.setattr(
        ai_client, "generate_grounded_with_sources", lambda prompt, **k: (enrich, [])
    )

    text = "入園のしおり\n在籍証明書を2026-07-31までにご提出ください。\n面談は2026-07-15。\n"
    drafts = submission_agent.build_submission_task_drafts(text, language="ja")
    assert len(drafts) == 4
    # 本文の最も遅い日付 7/31 を最終提出期限として後ろ向きに逆算（実行順で返る）
    assert [d["due_date"] for d in drafts] == [
        "2026-07-10",
        "2026-07-13",
        "2026-07-27",
        "2026-07-28",
    ]
    for d in drafts:
        assert d["event_date"] == d["due_date"]
        assert "最終提出期限: 2026-07-31" in d["content"]


def test_build_drafts_explicit_final_due_takes_priority(monkeypatch):
    """SOT-1399 4th: 調査対象タスクに設定済みの期限(final_due_iso)を最優先アンカーにする。

    再オープン「タスク追加時に日付を設定している。その日付を最終期限としてください。」への対応。
    本文の最も遅い日付(7/15)や LLM 抽出の書類別締切(7/20)があっても、明示的に渡した
    タスクの期限 7/31 を最終提出期限として後ろ向きに逆算する。
    """
    monkeypatch.setattr(ai_client, "gemini_available", lambda: True)
    monkeypatch.setattr(
        submission_agent, "_today", lambda: datetime.date(2026, 6, 30)
    )
    monkeypatch.setattr(
        submission_agent,
        "_llm_extract_documents",
        # LLM はあえて別の締切(7/20)を返す。明示アンカーが優先されることを確認する。
        lambda text, language: [{"name": "在籍証明書", "due_date": "2026-07-20"}],
    )
    enrich = json.dumps(
        {
            "steps": [
                {"name": "テンプレート入手", "lead_time_days": 3},
                {"name": "証明書発行", "lead_time_days": 14},
                {"name": "誤り確認", "lead_time_days": 1},
                {"name": "市町村に提出", "lead_time_days": 3},
            ],
            "needs_company_issuance": True,
            "lead_time_days": None,
            "source": "https://example.go.jp",
        }
    )
    monkeypatch.setattr(
        ai_client, "generate_grounded_with_sources", lambda prompt, **k: (enrich, [])
    )

    # 本文には別の日付(7/15)しか無い。タスクの期限 7/31 を明示的に渡す。
    text = "入園のしおり\n面談は2026-07-15。\n"
    drafts = submission_agent.build_submission_task_drafts(
        text, language="ja", final_due_iso="2026-07-31"
    )
    assert len(drafts) == 4
    # タスク設定日付 7/31 を最終提出期限として後ろ向きに逆算（実行順で返る）
    assert [d["due_date"] for d in drafts] == [
        "2026-07-10",
        "2026-07-13",
        "2026-07-27",
        "2026-07-28",
    ]
    for d in drafts:
        assert d["event_date"] == d["due_date"]
        assert "最終提出期限: 2026-07-31" in d["content"]


def test_build_drafts_default_buffer_when_lead_unknown(monkeypatch):
    monkeypatch.setattr(ai_client, "gemini_available", lambda: True)
    monkeypatch.setattr(
        submission_agent,
        "_llm_extract_documents",
        lambda text, language: [{"name": "健康調査票", "due_date": "2026-05-10"}],
    )
    monkeypatch.setattr(
        ai_client,
        "generate_grounded_with_sources",
        lambda prompt, **k: (
            json.dumps(
                {"steps": [], "needs_company_issuance": None, "lead_time_days": None, "source": ""}
            ),
            [],
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
    monkeypatch.setattr(
        ai_client, "generate_grounded_with_sources", lambda prompt, **k: ("", [])
    )
    # 手順も日付も無い書類は従来どおり日付が空（SAMPLE_NO_DATES でアンカー無し）。
    drafts = submission_agent.build_submission_task_drafts(SAMPLE_NO_DATES, language="ja")
    assert drafts[0]["due_date"] == ""
    assert drafts[0]["event_date"] == ""


def test_detect_deadline_iso():
    """本文中の最も遅い日付を ISO で返す（提出期限アンカー）。"""
    assert (
        submission_agent._detect_deadline_iso(
            "提出は2026-07-31まで、面談は2026-07-15。"
        )
        == "2026-07-31"
    )
    assert submission_agent._detect_deadline_iso("") == ""
    assert submission_agent._detect_deadline_iso("日付の無い本文です。") == ""


# --- 根拠となる出典リンク (SOT-1404) ------------------------------------------------

def test_grounded_enrich_collects_grounding_sources(monkeypatch):
    """grounding メタデータ由来の実出典URLが doc の sources に入る（LLM source より優先）。"""
    grounding = [
        {"title": "横浜市 就労証明書", "url": "https://city.example.go.jp/form"},
        {"title": "", "url": "https://mhlw.example.go.jp/guide"},
    ]
    monkeypatch.setattr(
        ai_client,
        "generate_grounded_with_sources",
        lambda prompt, **k: (_enrich_json(source="就労証明書 案内"), grounding),
    )
    info = submission_agent._grounded_enrich("就労証明書", "ja")
    assert info["sources"] == grounding
    # LLM 自己申告の source 文字列も従来どおり保持される
    assert info["source"] == "就労証明書 案内"


def test_grounded_enrich_falls_back_to_llm_url_when_no_grounding(monkeypatch):
    """grounding が空でも、LLM の source が http(s) URL ならフォールバックで sources に入れる。"""
    monkeypatch.setattr(
        ai_client,
        "generate_grounded_with_sources",
        lambda prompt, **k: (_enrich_json(source="https://example.go.jp"), []),
    )
    info = submission_agent._grounded_enrich("就労証明書", "ja")
    assert info["sources"] == [
        {"title": "https://example.go.jp", "url": "https://example.go.jp"}
    ]


def test_grounded_enrich_non_url_source_has_no_links(monkeypatch):
    """URL でない単なる名称の source は根拠リンク扱いしない（sources は空）。"""
    monkeypatch.setattr(
        ai_client,
        "generate_grounded_with_sources",
        lambda prompt, **k: (_enrich_json(source="市区町村の窓口"), []),
    )
    info = submission_agent._grounded_enrich("就労証明書", "ja")
    assert info["sources"] == []
    assert info["source"] == "市区町村の窓口"


def test_build_drafts_content_includes_source_links(monkeypatch):
    """各手順タスク本文に「根拠リンク」と grounding 由来の実URLが出る。"""
    monkeypatch.setattr(ai_client, "gemini_available", lambda: True)
    monkeypatch.setattr(
        submission_agent,
        "_llm_extract_documents",
        lambda text, language: [{"name": "就労証明書", "due_date": "2026-05-10"}],
    )
    grounding = [{"title": "横浜市 案内", "url": "https://city.example.go.jp/form"}]
    monkeypatch.setattr(
        ai_client,
        "generate_grounded_with_sources",
        lambda prompt, **k: (_enrich_json(lead=7), grounding),
    )
    drafts = submission_agent.build_submission_task_drafts(SAMPLE, language="ja")
    assert drafts
    for d in drafts:
        assert "根拠リンク:" in d["content"]
        assert "https://city.example.go.jp/form" in d["content"]
        # grounding がある時は LLM 自己申告の単一「出典:」行は出さない
        assert "出典:" not in d["content"]


def test_build_drafts_content_source_line_when_no_links(monkeypatch):
    """grounding も URL も無い時は従来どおり「出典:」行（LLM source）を出す（後方互換）。"""
    monkeypatch.setattr(ai_client, "gemini_available", lambda: True)
    monkeypatch.setattr(
        submission_agent,
        "_llm_extract_documents",
        lambda text, language: [{"name": "就労証明書", "due_date": "2026-05-10"}],
    )
    monkeypatch.setattr(
        ai_client,
        "generate_grounded_with_sources",
        lambda prompt, **k: (_enrich_json(lead=7, source="市区町村の窓口"), []),
    )
    drafts = submission_agent.build_submission_task_drafts(SAMPLE, language="ja")
    assert drafts
    assert "出典: 市区町村の窓口" in drafts[0]["content"]
    assert "根拠リンク:" not in drafts[0]["content"]


def test_extract_grounding_sources_from_response():
    """ai_client._extract_grounding_sources が grounding_metadata から実URLを取り出す。"""
    from app import ai_client as ac

    class _Web:
        def __init__(self, uri, title):
            self.uri = uri
            self.title = title

    class _Chunk:
        def __init__(self, web):
            self.web = web

    class _Meta:
        def __init__(self, chunks):
            self.grounding_chunks = chunks

    class _Cand:
        def __init__(self, meta):
            self.grounding_metadata = meta

    class _Resp:
        def __init__(self, candidates):
            self.candidates = candidates

    resp = _Resp(
        [
            _Cand(
                _Meta(
                    [
                        _Chunk(_Web("https://a.example.go.jp", "A")),
                        _Chunk(_Web("https://a.example.go.jp", "dup")),  # 重複は除外
                        _Chunk(_Web("", "no-url")),  # url 空は除外
                        _Chunk(_Web("https://b.example.go.jp", "")),
                    ]
                )
            )
        ]
    )
    assert ac._extract_grounding_sources(resp) == [
        {"title": "A", "url": "https://a.example.go.jp"},
        {"title": "", "url": "https://b.example.go.jp"},
    ]
    # 形が違う応答でも例外を出さず空リスト
    assert ac._extract_grounding_sources(object()) == []


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
