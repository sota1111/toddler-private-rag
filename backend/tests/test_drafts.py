"""仮登録(draft) / 本登録(finalize) のテスト (SOT-1113)。

- POST /info/ に registration_state="draft" で作成すると drafts 一覧にのみ出る
- 通常一覧 (/info/, /info/today 等) には draft が混ざらない
- POST /info/{id}/finalize で draft が registered になり通常一覧に出る
- registration_state 省略時は registered 扱い（後方互換）
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.routers.auth import get_current_user
from app import database, clock

SQLALCHEMY_DATABASE_URL = "sqlite://"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def setup_and_teardown(monkeypatch):
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(database, "SessionLocal", TestingSessionLocal)
    monkeypatch.setitem(app.dependency_overrides, get_db, override_get_db)
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: "test_user")
    yield
    Base.metadata.drop_all(bind=engine)


client = TestClient(app)


def _create(**kwargs):
    body = {"title": "t", "info_type": "お知らせ", "content": "c"}
    body.update(kwargs)
    resp = client.post("/api/info/", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_draft_appears_only_in_drafts_list():
    draft = _create(title="draft-1", registration_state="draft")
    assert draft["registration_state"] == "draft"

    draft_titles = {i["title"] for i in client.get("/api/info/drafts").json()}
    assert "draft-1" in draft_titles

    list_titles = {i["title"] for i in client.get("/api/info/").json()}
    assert "draft-1" not in list_titles


def test_default_create_is_registered():
    _create(title="registered-default")
    item = client.get("/api/info/").json()
    titles = {i["title"] for i in item}
    assert "registered-default" in titles
    assert all(i["registration_state"] == "registered" for i in item)
    assert client.get("/api/info/drafts").json() == []


def test_draft_excluded_from_today():
    # /api/info/today はサーバの clock.today()(JST基準) で判定するため、
    # テストも同じ基準で「今日」を作る。素の date.today()(UTC) だと
    # UTC/JST 境界時間帯でフレークする (SOT-1493)。
    today = clock.today().isoformat()
    _create(title="draft-today", registration_state="draft", due_date=today)
    _create(title="reg-today", due_date=today)

    today_titles = {i["title"] for i in client.get("/api/info/today").json()}
    assert "reg-today" in today_titles
    assert "draft-today" not in today_titles


def test_finalize_moves_draft_to_registered():
    draft = _create(title="to-finalize", registration_state="draft")
    info_id = draft["id"]

    resp = client.post(f"/api/info/{info_id}/finalize")
    assert resp.status_code == 200, resp.text
    assert resp.json()["registration_state"] == "registered"

    # drafts から消える
    assert "to-finalize" not in {i["title"] for i in client.get("/api/info/drafts").json()}
    # 通常一覧に出る
    assert "to-finalize" in {i["title"] for i in client.get("/api/info/").json()}


def test_finalize_404_for_missing():
    resp = client.post("/api/info/999999/finalize")
    assert resp.status_code == 404


def test_processing_list_returns_only_processing():
    # SOT-1499: 読み取り中(processing)の項目一覧。追加自動登録した写真を仮登録画面に
    # 「読み取り中」カードとして表示するため、processing のみを返す。
    _create(title="reading-1", registration_state="processing")
    _create(title="draft-1", registration_state="draft")
    _create(title="registered-1")

    processing_titles = {i["title"] for i in client.get("/api/info/drafts/processing").json()}
    assert processing_titles == {"reading-1"}

    # processing は仮登録(draft)一覧にも通常一覧にも出ない
    assert "reading-1" not in {i["title"] for i in client.get("/api/info/drafts").json()}
    assert "reading-1" not in {i["title"] for i in client.get("/api/info/").json()}

    # 件数エンドポイントとも整合する
    assert client.get("/api/info/drafts/processing-count").json()["count"] == 1


def test_processing_list_empty_by_default():
    _create(title="draft-only", registration_state="draft")
    assert client.get("/api/info/drafts/processing").json() == []


def test_create_draft_with_empty_string_dates(monkeypatch):
    """SOT-1197: 自動登録の save-first ペイロード（空文字の日付）で 422 にならない。

    フロント AutoRegisterPage は date/event_date/due_date を空文字 "" で送る。
    空文字は「未設定」として None に正規化され、作成が成功すること。
    """
    body = {
        "title": "",
        "info_type": "資料",
        "content": "",
        "date": "",
        "event_date": "",
        "due_date": "",
        "items": "",
        "status": "未対応",
        "priority": "普通",
        "tags": "",
        "memo": "",
        "registration_state": "draft",
    }
    resp = client.post("/api/info/", json=body)
    assert resp.status_code == 200, resp.text
    created = resp.json()
    assert created["date"] is None
    assert created["event_date"] is None
    assert created["due_date"] is None
    assert created["registration_state"] == "draft"

    # PUT 更新（enrichment 経路）でも空文字日付が許容される
    upd = client.put(f"/api/info/{created['id']}", json={"date": "", "event_date": "2026-07-01"})
    assert upd.status_code == 200, upd.text
    assert upd.json()["date"] is None
    assert upd.json()["event_date"] == "2026-07-01"


# --- SOT-1577: 本登録後の「分割前のタスクに戻す」（revert-split-registered）---------------
def test_revert_split_registered_merges_group_into_single():
    """同一書類(source_info_id)から分割された本登録タスク群を、未分割の1タスクへまとめ直す。"""
    src = _create(title="元書類", content="全文まとめ")
    sid = str(src["id"])
    a = _create(title="タスクA", content="Aの内容", source_info_id=sid)
    b = _create(title="タスクB", content="Bの内容", source_info_id=sid)

    resp = client.post(f"/api/info/{sid}/revert-split-registered")
    assert resp.status_code == 200, resp.text
    merged = resp.json()
    assert merged["registration_state"] == "registered"
    assert str(merged["source_info_id"]) == sid

    titles = {i["title"] for i in client.get("/api/info/").json()}
    # 元の分割タスクは置き換えられて消える。元書類レコードは残る。
    assert "タスクA" not in titles
    assert "タスクB" not in titles
    assert "元書類" in titles
    assert merged["id"] not in {a["id"], b["id"]}
    # 同一書類由来の本登録タスクは統合後1件（= merged）だけになる。
    same_source = [
        i for i in client.get("/api/info/").json()
        if str(i.get("source_info_id") or "") == sid
    ]
    assert len(same_source) == 1
    assert same_source[0]["id"] == merged["id"]


def test_revert_split_registered_404_when_no_group():
    """当該書類由来の本登録タスクが無ければ 404。"""
    resp = client.post("/api/info/999999/revert-split-registered")
    assert resp.status_code == 404, resp.text


def test_revert_split_registered_content_from_tasks_not_source_document():
    """SOT-1577 REOPEN#2: 戻した本文が書類全体(全写真の文字起こし)ではなく分割タスク群の内容から復元される。"""
    src = _create(title="運動会のお知らせ", content="写真全ての文字起こし（書類全文）")
    sid = str(src["id"])
    _create(title="タスクA", content="Aの内容", source_info_id=sid)
    _create(title="タスクB", content="Bの内容", source_info_id=sid)

    merged = client.post(f"/api/info/{sid}/revert-split-registered").json()
    # 書類全文（全写真の文字起こし）は流し込まれない。
    assert "写真全ての文字起こし" not in merged["content"]
    assert merged["content"] == "Aの内容\n\nBの内容"


def test_revert_split_registered_excludes_deadline_companion_content():
    """SOT-1577 REOPEN#2: 締切調査の付随タスク(deadline_group_id + offset≠0)は統合本文に含めない。"""
    src = _create(title="提出書類のお知らせ", content="書類全文")
    sid = str(src["id"])
    _create(title="タスクA", content="Aの内容", source_info_id=sid)
    _create(title="タスクB", content="Bの内容", source_info_id=sid)
    # 締切調査の付随タスク（別グループ・offset≠0）。統合対象外にする。
    _create(
        title="付随: 書類を印刷",
        content="付随タスクの内容",
        source_info_id=sid,
        deadline_group_id="g-1",
        deadline_offset_days=-7,
    )

    merged = client.post(f"/api/info/{sid}/revert-split-registered").json()
    assert merged["content"] == "Aの内容\n\nBの内容"


# --- SOT-1594: 「分割を戻す」を締切逆算タスクの (n/N) 分割群単位に限定する ------------------
def test_revert_split_registered_scoped_to_deadline_group():
    """SOT-1594: 押下した (n/N) 分割タスクの締切グループだけを1つに戻し、同じ写真由来でも別書類・
    別グループのタスクは残す（旧実装は source_info_id 単位で書類全タスクを潰していた）。"""
    from app.submission_agent import SUBMISSION_TAG

    photo = _create(title="運動会のお知らせ", content="写真全文")
    sid = str(photo["id"])
    # 締切グループ g1: アンカー(元タスク, offset0, タグ無) + (1/2)(2/2) 分割ステップ(付随タスク)。
    anchor = _create(
        title="就労証明書", content="アンカー本文", source_info_id=sid,
        deadline_group_id="g1", deadline_offset_days=0,
    )
    step1 = _create(
        title="就労証明書(1/2) 様式入手", content="手順1", source_info_id=sid,
        deadline_group_id="g1", deadline_offset_days=-7, tags=SUBMISSION_TAG,
    )
    step2 = _create(
        title="就労証明書(2/2) 提出", content="手順2", source_info_id=sid,
        deadline_group_id="g1", deadline_offset_days=0, tags=SUBMISSION_TAG,
    )
    # 残すべき: 同じ写真由来の別書類タスク(グループ無) と 別グループ g2 のステップ。
    _create(title="遠足のしおり", content="別書類本文", source_info_id=sid)
    _create(
        title="遠足(1/1) 持ち物", content="別グループ手順", source_info_id=sid,
        deadline_group_id="g2", deadline_offset_days=-3, tags=SUBMISSION_TAG,
    )

    # 押下タスク = g1 の (1/2)。その締切グループだけが戻す対象。
    resp = client.post(f"/api/info/{step1['id']}/revert-split-registered")
    assert resp.status_code == 200, resp.text
    merged = resp.json()
    assert merged["registration_state"] == "registered"
    assert str(merged["source_info_id"]) == sid

    listed = client.get("/api/info/").json()
    titles = {i["title"] for i in listed}
    ids = {i["id"] for i in listed}
    # g1 のメンバ(アンカー+ステップ)は置き換えられて消える。
    assert anchor["id"] not in ids
    assert step1["id"] not in ids
    assert step2["id"] not in ids
    # 別書類タスク・別グループ g2 のステップは残る（＝書類全体が1つに潰れない）。
    assert "遠足のしおり" in titles
    assert "遠足(1/1) 持ち物" in titles
    # 統合本文は付随タスク(ステップ)を除外し、アンカー本文から復元する。
    assert "アンカー本文" in merged["content"]
    assert "手順1" not in merged["content"]


def test_revert_split_drafts_scoped_to_deadline_group():
    """SOT-1594: draft 版も締切グループ単位。別グループの draft は残す。"""
    from app.submission_agent import SUBMISSION_TAG

    photo = _create(title="写真", content="写真全文", registration_state="draft")
    sid = str(photo["id"])
    a1 = _create(
        title="書類A(1/2)", content="A1", source_info_id=sid, registration_state="draft",
        deadline_group_id="ga", deadline_offset_days=-7, tags=SUBMISSION_TAG,
    )
    a2 = _create(
        title="書類A(2/2)", content="A2", source_info_id=sid, registration_state="draft",
        deadline_group_id="ga", deadline_offset_days=0, tags=SUBMISSION_TAG,
    )
    _create(
        title="書類B(1/1)", content="B1", source_info_id=sid, registration_state="draft",
        deadline_group_id="gb", deadline_offset_days=-3, tags=SUBMISSION_TAG,
    )

    resp = client.post(f"/api/info/drafts/{a1['id']}/revert-split")
    assert resp.status_code == 200, resp.text
    merged = resp.json()
    assert merged["registration_state"] == "draft"
    assert str(merged["source_info_id"]) == sid

    drafts = client.get("/api/info/drafts").json()
    draft_titles = {i["title"] for i in drafts}
    draft_ids = {i["id"] for i in drafts}
    # ga のメンバは戻されて消える。
    assert a1["id"] not in draft_ids
    assert a2["id"] not in draft_ids
    # 別グループ gb の draft は残る。
    assert "書類B(1/1)" in draft_titles
    assert "付随タスクの内容" not in merged["content"]


# --- SOT-1594 REOPEN: 戻し先の title/content を「分割前のタスク（アンカー）」から復元する ------
def test_revert_split_registered_restores_anchor_title_not_photo():
    """SOT-1594 REOPEN: 戻すと title が写真書類のタイトルではなく締切分割前タスク（アンカー）の
    title になり、content が締切調査結果の羅列ではなく手順1（文字起こし後）のタスク内容になる。"""
    from app.submission_agent import SUBMISSION_TAG

    photo = _create(
        title="7月のおたよりと七夕祭りのお知らせ", content="写真全文の文字起こし"
    )
    sid = str(photo["id"])
    # アンカー（締切調査の元タスク, offset0, タグ無し）＝手順1の状態（文字起こし後のタスク）。
    anchor = _create(
        title="就労証明書の提出", content="就労証明書を園に提出する",
        source_info_id=sid, deadline_group_id="gX", deadline_offset_days=0,
    )
    # (n/N) 分割ステップ（付随タスク）。本文は締切調査の調査結果。
    step1 = _create(
        title="就労証明書の提出(1/2) 様式入手", content="市役所で様式を入手する（調査結果1）",
        source_info_id=sid, deadline_group_id="gX", deadline_offset_days=-7,
        tags=SUBMISSION_TAG,
    )
    _create(
        title="就労証明書の提出(2/2) 提出", content="園に提出する（調査結果2）",
        source_info_id=sid, deadline_group_id="gX", deadline_offset_days=0,
        tags=SUBMISSION_TAG,
    )

    merged = client.post(f"/api/info/{step1['id']}/revert-split-registered").json()
    # AC1: 写真書類のタイトルにならず、分割前タスク（アンカー）のタイトルになる。
    assert merged["title"] == "就労証明書の提出"
    assert merged["title"] != "7月のおたよりと七夕祭りのお知らせ"
    # AC2: 締切調査の調査結果を羅列せず、手順1（文字起こし後）のタスク内容へ戻る。
    assert merged["content"] == "就労証明書を園に提出する"
    assert "調査結果" not in merged["content"]


def test_revert_split_drafts_restores_anchor_title_and_content():
    """SOT-1594 REOPEN(draft 版): draft の締切分割群を戻すと、アンカー（分割前タスク）の
    title/content へ戻る。"""
    from app.submission_agent import SUBMISSION_TAG

    photo = _create(title="おたより", content="写真全文", registration_state="draft")
    sid = str(photo["id"])
    _create(
        title="健康診断の申込", content="健康診断を申し込む",
        source_info_id=sid, registration_state="draft",
        deadline_group_id="gd", deadline_offset_days=0,
    )
    step1 = _create(
        title="健康診断の申込(1/2) 用紙記入", content="用紙に記入（調査結果1）",
        source_info_id=sid, registration_state="draft",
        deadline_group_id="gd", deadline_offset_days=-5, tags=SUBMISSION_TAG,
    )
    _create(
        title="健康診断の申込(2/2) 提出", content="窓口に提出（調査結果2）",
        source_info_id=sid, registration_state="draft",
        deadline_group_id="gd", deadline_offset_days=0, tags=SUBMISSION_TAG,
    )

    merged = client.post(f"/api/info/drafts/{step1['id']}/revert-split").json()
    assert merged["title"] == "健康診断の申込"
    assert merged["title"] != "おたより"
    assert merged["content"] == "健康診断を申し込む"
    assert "調査結果" not in merged["content"]


def test_revert_split_drafts_finds_anchor_in_registered_state():
    """SOT-1594 REOPEN(実フロー): 締切調査は本登録タスク上で走ることがあり、アンカーは本登録・
    (n/N) 分割ステップは draft という状態違いになりうる。draft 側の分割群を戻すときも、登録状態に
    依らずアンカー（本登録側）の title/content を復元する。"""
    from app.submission_agent import SUBMISSION_TAG

    photo = _create(title="写真タイトル", content="写真全文")
    sid = str(photo["id"])
    # アンカーは本登録（手順1のタスク）。
    _create(
        title="面談の予約", content="担任と面談を予約する",
        source_info_id=sid, deadline_group_id="gm", deadline_offset_days=0,
    )
    # 分割ステップは draft。
    step1 = _create(
        title="面談の予約(1/2) 候補日確認", content="候補日を確認（調査結果1）",
        source_info_id=sid, registration_state="draft",
        deadline_group_id="gm", deadline_offset_days=-3, tags=SUBMISSION_TAG,
    )
    _create(
        title="面談の予約(2/2) 連絡", content="担任へ連絡（調査結果2）",
        source_info_id=sid, registration_state="draft",
        deadline_group_id="gm", deadline_offset_days=0, tags=SUBMISSION_TAG,
    )

    merged = client.post(f"/api/info/drafts/{step1['id']}/revert-split").json()
    assert merged["registration_state"] == "draft"
    assert merged["title"] == "面談の予約"
    assert merged["content"] == "担任と面談を予約する"
    assert "調査結果" not in merged["content"]


def test_revert_split_registered_restores_task_not_raw_transcription():
    """SOT-1594 REOPEN#3: 戻す先は「文字起こし後にタスク分解して、（締切逆算）エージェントを起動する
    前」のタスク本文であること。元書類(写真)の生の文字起こし全文（＝「文字起こし後の状態」）にしない。

    実フロー再現: 元書類(写真)の content は全文文字起こし。手順1で分解されたタスク（アンカー, offset0,
    タグ無し）の content はそのタスク分の本文。締切逆算の (n/N) 付随タスク（SUBMISSION_TAG）は調査結果。
    「分割を戻す」を押したら、生の文字起こし全文でも調査結果でもなく、タスク分解後（手順1）の本文へ戻る。
    """
    from app.submission_agent import SUBMISSION_TAG

    raw = "写真全文の文字起こし（お知らせ・持ち物・締切…全部）"
    photo = _create(title="7月のおたより", content=raw)
    sid = str(photo["id"])
    # アンカー = 手順1でタスク分解した本文（締切エージェント起動前の状態）。
    anchor = _create(
        title="就労証明書の提出", content="就労証明書を園に提出する",
        source_info_id=sid, deadline_group_id="gR3", deadline_offset_days=0,
    )
    step1 = _create(
        title="就労証明書の提出(1/2) 様式入手", content="市役所で様式を入手（調査結果1）",
        source_info_id=sid, deadline_group_id="gR3", deadline_offset_days=-7,
        tags=SUBMISSION_TAG,
    )
    _create(
        title="就労証明書の提出(2/2) 提出", content="園に提出（調査結果2）",
        source_info_id=sid, deadline_group_id="gR3", deadline_offset_days=0,
        tags=SUBMISSION_TAG,
    )

    merged = client.post(f"/api/info/{step1['id']}/revert-split-registered").json()
    # タスク分解後（手順1）の本文へ戻る。
    assert merged["content"] == "就労証明書を園に提出する"
    # 生の文字起こし全文（文字起こし後の状態）は出さない。
    assert merged["content"] != raw
    assert "写真全文の文字起こし" not in merged["content"]
    # 調査結果の羅列にもしない。
    assert "調査結果" not in merged["content"]
    # タイトルも写真書類でなくアンカー。
    assert merged["title"] == "就労証明書の提出"
    assert anchor["id"]  # アンカーレコードは前提として存在
