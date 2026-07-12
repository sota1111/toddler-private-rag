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


# --- SOT-1597: 「分割タスクを戻す」= (n/N) 分割ステップを全削除し、分割前のタスク(アンカー)は残す ----
# 旧仕様(SOT-1577/1594)は分割群を未分割の1タスクへ統合し直していたが、その統合本文が写真の文字起こし
# 相当になってしまうため、統合タスクは作らず (n/N) 分割ステップの削除のみに変えた（SOT-1597）。
def test_revert_split_registered_deletes_steps_keeps_anchor():
    """SOT-1597: 押下した (n/N) 分割タスクの締切グループの分割ステップ(本登録)を全削除する。
    統合タスク(写真の文字起こし相当)は作らず、分割前のタスク(アンカー, マーカー無し)は残す。"""
    from app.submission_agent import SUBMISSION_TAG

    photo = _create(title="運動会のお知らせ", content="写真全文")
    sid = str(photo["id"])
    # 締切グループ g1: アンカー(元タスク, offset0, マーカー無) + (1/2)(2/2) 分割ステップ。
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

    resp = client.post(f"/api/info/{step1['id']}/revert-split-registered")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # (n/N) 分割ステップ2件のみが削除される。
    assert body["deleted_count"] == 2
    assert set(body["deleted_ids"]) == {step1["id"], step2["id"]}

    listed = client.get("/api/info/").json()
    ids = {i["id"] for i in listed}
    # 分割ステップは消える。
    assert step1["id"] not in ids
    assert step2["id"] not in ids
    # 分割前のタスク(アンカー)はそのまま残る（統合タスク＝写真の文字起こしは作らない）。
    assert anchor["id"] in ids
    anchor_now = next(i for i in listed if i["id"] == anchor["id"])
    assert anchor_now["title"] == "就労証明書"
    assert anchor_now["content"] == "アンカー本文"
    # 同一 source_info_id の本登録タスクはアンカー1件だけ（新規統合タスクは生まれない）。
    same_source = [i for i in listed if str(i.get("source_info_id") or "") == sid]
    assert [i["id"] for i in same_source] == [anchor["id"]]


def test_revert_split_registered_404_when_no_group():
    """当該書類由来の本登録タスクが無ければ 404。"""
    resp = client.post("/api/info/999999/revert-split-registered")
    assert resp.status_code == 404, resp.text


def test_revert_split_registered_scoped_to_deadline_group():
    """SOT-1594/1597: 押下した (n/N) 分割タスクの締切グループの分割ステップだけを削除し、同じ写真由来
    でも別書類・別グループのタスクは残す（旧実装は source_info_id 単位で書類全タスクを潰していた）。"""
    from app.submission_agent import SUBMISSION_TAG

    photo = _create(title="運動会のお知らせ", content="写真全文")
    sid = str(photo["id"])
    # 締切グループ g1: アンカー(元タスク, offset0, タグ無) + (1/2)(2/2) 分割ステップ。
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
    other_step = _create(
        title="遠足(1/2) 持ち物", content="別グループ手順", source_info_id=sid,
        deadline_group_id="g2", deadline_offset_days=-3, tags=SUBMISSION_TAG,
    )

    # 押下タスク = g1 の (1/2)。その締切グループの分割ステップだけが削除対象。
    resp = client.post(f"/api/info/{step1['id']}/revert-split-registered")
    assert resp.status_code == 200, resp.text
    assert set(resp.json()["deleted_ids"]) == {step1["id"], step2["id"]}

    listed = client.get("/api/info/").json()
    titles = {i["title"] for i in listed}
    ids = {i["id"] for i in listed}
    # g1 の分割ステップは消え、アンカーは残る。
    assert step1["id"] not in ids
    assert step2["id"] not in ids
    assert anchor["id"] in ids
    # 別書類タスク・別グループ g2 のステップは残る（＝書類全体が消えない）。
    assert "遠足のしおり" in titles
    assert other_step["id"] in ids


def test_revert_split_drafts_scoped_to_deadline_group():
    """SOT-1594/1597: draft 版も締切グループの分割ステップだけを削除する。別グループの draft は残す。"""
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
    b1 = _create(
        title="書類B(1/2)", content="B1", source_info_id=sid, registration_state="draft",
        deadline_group_id="gb", deadline_offset_days=-3, tags=SUBMISSION_TAG,
    )

    resp = client.post(f"/api/info/drafts/{a1['id']}/revert-split")
    assert resp.status_code == 200, resp.text
    assert set(resp.json()["deleted_ids"]) == {a1["id"], a2["id"]}

    drafts = client.get("/api/info/drafts").json()
    draft_ids = {i["id"] for i in drafts}
    # ga の分割ステップは消える。
    assert a1["id"] not in draft_ids
    assert a2["id"] not in draft_ids
    # 別グループ gb の draft は残る。
    assert b1["id"] in draft_ids


def test_revert_split_registered_keeps_anchor_task_intact():
    """SOT-1597: 分割前のタスク(アンカー)は削除対象外で、その title/content が変更されず残る
    （旧仕様はアンカーを削除して統合タスクへ置き換えていた）。"""
    from app.submission_agent import SUBMISSION_TAG

    photo = _create(title="7月のおたよりと七夕祭りのお知らせ", content="写真全文の文字起こし")
    sid = str(photo["id"])
    anchor = _create(
        title="就労証明書の提出", content="就労証明書を園に提出する",
        source_info_id=sid, deadline_group_id="gX", deadline_offset_days=0,
    )
    step1 = _create(
        title="就労証明書の提出(1/2) 様式入手", content="市役所で様式を入手する（調査結果1）",
        source_info_id=sid, deadline_group_id="gX", deadline_offset_days=-7,
        tags=SUBMISSION_TAG,
    )
    step2 = _create(
        title="就労証明書の提出(2/2) 提出", content="園に提出する（調査結果2）",
        source_info_id=sid, deadline_group_id="gX", deadline_offset_days=0,
        tags=SUBMISSION_TAG,
    )

    resp = client.post(f"/api/info/{step1['id']}/revert-split-registered")
    assert resp.status_code == 200, resp.text
    assert set(resp.json()["deleted_ids"]) == {step1["id"], step2["id"]}

    got = client.get(f"/api/info/{anchor['id']}")
    assert got.status_code == 200, got.text
    anchor_now = got.json()
    # 分割前のタスクはそのまま。写真書類のタイトルにも調査結果本文にもならない。
    assert anchor_now["title"] == "就労証明書の提出"
    assert anchor_now["content"] == "就労証明書を園に提出する"
    # 削除された分割ステップは取得できない。
    assert client.get(f"/api/info/{step2['id']}").status_code == 404


def test_revert_split_drafts_finds_steps_across_registration_states():
    """SOT-1594/1597(実フロー): 締切調査は本登録タスク上で走ることがあり、アンカーは本登録・
    (n/N) 分割ステップは draft という状態違いになりうる。draft 側の分割群を戻すと、draft の分割ステップ
    だけが削除され、本登録アンカーは残る。"""
    from app.submission_agent import SUBMISSION_TAG

    photo = _create(title="写真タイトル", content="写真全文")
    sid = str(photo["id"])
    # アンカーは本登録（手順1のタスク）。
    anchor = _create(
        title="面談の予約", content="担任と面談を予約する",
        source_info_id=sid, deadline_group_id="gm", deadline_offset_days=0,
    )
    # 分割ステップは draft。
    step1 = _create(
        title="面談の予約(1/2) 候補日確認", content="候補日を確認（調査結果1）",
        source_info_id=sid, registration_state="draft",
        deadline_group_id="gm", deadline_offset_days=-3, tags=SUBMISSION_TAG,
    )
    step2 = _create(
        title="面談の予約(2/2) 連絡", content="担任へ連絡（調査結果2）",
        source_info_id=sid, registration_state="draft",
        deadline_group_id="gm", deadline_offset_days=0, tags=SUBMISSION_TAG,
    )

    resp = client.post(f"/api/info/drafts/{step1['id']}/revert-split")
    assert resp.status_code == 200, resp.text
    assert set(resp.json()["deleted_ids"]) == {step1["id"], step2["id"]}

    # draft の分割ステップは消え、本登録アンカーは残る。
    draft_ids = {i["id"] for i in client.get("/api/info/drafts").json()}
    assert step1["id"] not in draft_ids
    assert step2["id"] not in draft_ids
    got = client.get(f"/api/info/{anchor['id']}")
    assert got.status_code == 200
    assert got.json()["content"] == "担任と面談を予約する"


def test_revert_split_does_not_create_transcription_task():
    """SOT-1597 本題: 「分割を戻す」を押しても、写真の生の文字起こしを本文に持つ統合タスクは
    新規作成されない（旧仕様の写真文字起こし相当タスクを撲滅する）。"""
    from app.submission_agent import SUBMISSION_TAG

    raw = "写真全文の文字起こし（お知らせ・持ち物・締切…全部）"
    photo = _create(title="7月のおたより", content=raw)
    sid = str(photo["id"])
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

    resp = client.post(f"/api/info/{step1['id']}/revert-split-registered")
    assert resp.status_code == 200, resp.text

    listed = client.get("/api/info/").json()
    # 生の文字起こし全文を本文に持つタスクは、写真書類(photo)以外に存在しない。
    transcription_holders = [i for i in listed if i["content"] == raw]
    assert [i["id"] for i in transcription_holders] == [photo["id"]]
    # 残るのは写真書類とアンカーのみ（調査結果ステップは全削除）。
    remaining_ids = {i["id"] for i in listed}
    assert photo["id"] in remaining_ids
    assert anchor["id"] in remaining_ids
