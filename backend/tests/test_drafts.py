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
    assert "付随タスクの内容" not in merged["content"]
