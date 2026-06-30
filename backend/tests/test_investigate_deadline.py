"""締切調査エンドポイントのテスト (SOT-1406)。

POST /info/{id}/investigate-deadline は、調査対象テキストにタスクのタイトルを含める。
手動追加タスク（書類名がタイトルに入り、本文が空/簡素）でも書類抽出が走るようにするため。
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.routers.auth import get_current_user
from app import database, submission_agent
from app.repository import SqliteInfoRepository

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


def test_investigate_includes_title_in_safe_text(monkeypatch):
    """タイトルに書類名があり本文が空でも、調査対象テキストにタイトルが含まれる。"""
    captured = {}

    def fake_drafts(safe_text, detected_dates=None, **kwargs):
        captured["safe_text"] = safe_text
        return []

    monkeypatch.setattr(submission_agent, "build_submission_task_drafts", fake_drafts)

    # 手動追加タスク: 書類名はタイトルに入り、本文は最小限。
    info = _create(title="就労証明書の提出", content="メモ")

    resp = client.post(f"/api/info/{info['id']}/investigate-deadline")
    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] == 0

    # SOT-1406: タイトルが調査対象テキストの先頭に含まれていること。
    assert "就労証明書の提出" in captured["safe_text"]
    assert captured["safe_text"].startswith("就労証明書の提出")


def test_investigate_excludes_attachment_ocr(monkeypatch):
    """SOT-1406 再オープン: 添付写真のOCR原文は調査対象テキストに含めない。"""
    captured = {}

    def fake_drafts(safe_text, detected_dates=None, **kwargs):
        captured["safe_text"] = safe_text
        return []

    monkeypatch.setattr(submission_agent, "build_submission_task_drafts", fake_drafts)

    # 添付写真のOCRが存在しても調査対象には混ざらないことを検証する。
    class _FakeAttachment:
        ocr_text = "添付写真のOCR原文 2026-12-31 提出書類"

    monkeypatch.setattr(
        SqliteInfoRepository,
        "list_attachments_for_info",
        lambda self, id: [_FakeAttachment()],
    )

    info = _create(title="就労証明書の提出", content="メモ")

    resp = client.post(f"/api/info/{info['id']}/investigate-deadline")
    assert resp.status_code == 200, resp.text

    # 添付OCRは除外、タイトル/本文は含まれること。
    assert "添付写真のOCR原文" not in captured["safe_text"]
    assert "就労証明書の提出" in captured["safe_text"]
    assert "メモ" in captured["safe_text"]


# --- SOT-1411: 基準日変更で付随タスクを一括ずらし ------------------------------------

def _create_grouped(group_id, offset, base_date, due):
    """締切調査グループに属するタスクを作る（offset/base_date/due を直接指定）。"""
    return _create(
        title=f"task-{offset}",
        info_type="提出物",
        content="c",
        due_date=due,
        event_date=due,
        deadline_group_id=group_id,
        deadline_offset_days=offset,
        deadline_base_date=base_date,
    )


def test_reschedule_shifts_sibling_tasks(monkeypatch):
    """基準日を変更すると、同じグループの付随タスクが各オフセット分だけまとめてずれる。"""
    monkeypatch.setattr("app.routers.info.index_info_id", lambda *a, **k: None)

    g = "grp-1411"
    base = "2026-07-30"
    t0 = _create_grouped(g, 8, base, "2026-07-22")  # 基準日-8
    t1 = _create_grouped(g, 5, base, "2026-07-25")  # 基準日-5
    t2 = _create_grouped(g, 0, base, "2026-07-30")  # 基準日当日

    # t1 の基準日を 8/10 に変更（同グループの t0/t1/t2 が一緒にずれる）。
    resp = client.post(
        f"/api/info/{t1['id']}/reschedule-deadline", json={"base_date": "2026-08-10"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated"] == 3

    def _due(info_id):
        r = client.get(f"/api/info/{info_id}")
        assert r.status_code == 200, r.text
        return r.json()

    d0, d1, d2 = _due(t0["id"]), _due(t1["id"]), _due(t2["id"])
    # 新基準日 8/10 - 各オフセット
    assert d0["due_date"] == "2026-08-02" and d0["event_date"] == "2026-08-02"
    assert d1["due_date"] == "2026-08-05" and d1["event_date"] == "2026-08-05"
    assert d2["due_date"] == "2026-08-10" and d2["event_date"] == "2026-08-10"
    # 基準日も更新される
    assert d0["deadline_base_date"] == "2026-08-10"
    assert d2["deadline_base_date"] == "2026-08-10"


def test_reschedule_is_idempotent(monkeypatch):
    """同じ基準日で2回呼んでも結果は変わらない（常に新基準日 - オフセットで再計算）。"""
    monkeypatch.setattr("app.routers.info.index_info_id", lambda *a, **k: None)

    g = "grp-idem"
    base = "2026-07-30"
    t0 = _create_grouped(g, 8, base, "2026-07-22")

    for _ in range(2):
        resp = client.post(
            f"/api/info/{t0['id']}/reschedule-deadline", json={"base_date": "2026-08-10"}
        )
        assert resp.status_code == 200, resp.text

    r = client.get(f"/api/info/{t0['id']}").json()
    assert r["due_date"] == "2026-08-02"
    assert r["event_date"] == "2026-08-02"
    assert r["deadline_base_date"] == "2026-08-10"


def test_reschedule_404_for_missing(monkeypatch):
    monkeypatch.setattr("app.routers.info.index_info_id", lambda *a, **k: None)
    resp = client.post("/api/info/999999/reschedule-deadline", json={"base_date": "2026-08-10"})
    assert resp.status_code == 404


def test_forward_generated_group_is_reschedulable(monkeypatch):
    """SOT-1411 再オープン: 最終提出期限が不明な書類（前向き累積で生成）でも、各手順タスクに
    オフセットと基準日が記録され、基準日変更で付随タスクがまとめてずれること。

    回帰: 修正前は前向き経路の offset が全て None・基準日が空で保存され、基準日変更時に編集した
    タスク1件しか動かなかった（=「他のやることの日付が変わらない」）。
    """
    # 最終提出期限を持たない（due_date が空の）書類を、手順つきで生成させる。
    def fake_extract(safe_text, detected_dates=None, language="ja", final_due_iso=None):
        return [
            {
                "name": "在籍証明書",
                "due_date": "",  # 最終提出期限が不明
                "lead_time_days": None,
                "steps": [
                    {"name": "会社へ依頼", "lead_time_days": 3},
                    {"name": "受領", "lead_time_days": 2},
                    {"name": "園へ提出", "lead_time_days": 1},
                ],
            }
        ]

    monkeypatch.setattr(submission_agent, "extract_submission_documents", fake_extract)

    drafts = submission_agent.build_submission_task_drafts("在籍証明書", None, language="ja")
    assert len(drafts) == 3

    # 全タスクにオフセットが記録され（None でない）、最終タスクが基準（offset=0）になっている。
    offsets = [d["deadline_offset_days"] for d in drafts]
    assert all(o is not None for o in offsets), offsets
    assert offsets[-1] == 0
    # 基準日（グループの最終タスク日付）が空でないこと。
    base_dates = {d["deadline_base_date"] for d in drafts}
    assert "" not in base_dates and len(base_dates) == 1
    # 同一グループ識別子を共有していること。
    assert len({d["deadline_group_id"] for d in drafts}) == 1

    # 生成された前向きグループを実際に永続化し、基準日変更で付随タスクが一緒にずれることを確認する。
    monkeypatch.setattr("app.routers.info.index_info_id", lambda *a, **k: None)
    created = []
    for d in drafts:
        created.append(
            _create(
                title=d["title"],
                info_type=d["info_type"],
                content=d["content"],
                event_date=d["event_date"],
                due_date=d["due_date"],
                deadline_group_id=d["deadline_group_id"],
                deadline_offset_days=d["deadline_offset_days"],
                deadline_base_date=d["deadline_base_date"],
            )
        )

    resp = client.post(
        f"/api/info/{created[0]['id']}/reschedule-deadline",
        json={"base_date": "2026-09-30"},
    )
    assert resp.status_code == 200, resp.text
    # 付随タスク全件（3件）がずれること（修正前は1件しか動かなかった）。
    assert resp.json()["updated"] == 3

    for d, c in zip(drafts, created):
        r = client.get(f"/api/info/{c['id']}").json()
        expected = (
            __import__("datetime").date(2026, 9, 30)
            - __import__("datetime").timedelta(days=d["deadline_offset_days"])
        ).isoformat()
        assert r["due_date"] == expected and r["event_date"] == expected
        assert r["deadline_base_date"] == "2026-09-30"


def test_investigate_anchors_source_task_to_group(monkeypatch):
    """SOT-1411 再オープン: 締切調査の元タスク(親)が、生成した付随タスク(子)と同じ締切グループの
    アンカー(deadline_offset_days == 0)になること。

    回帰: 修正前は元タスクがグループに含まれず、親の日付を変えても子が連動しなかった。さらに
    基準日変更ボタンが子タスク側にだけ表示されていた（親=アンカーにのみ表示すべき）。
    """
    monkeypatch.setattr("app.routers.info.index_info_id", lambda *a, **k: None)

    # build_submission_task_drafts は子タスク draft を返すスタブ。assign_anchor_group は実物が走る。
    def fake_drafts(safe_text, detected_dates=None, **kwargs):
        return [
            {
                "title": "在籍証明書の準備",
                "info_type": "提出物",
                "content": "c",
                "items": "",
                "date": "",
                "event_date": "2026-07-22",
                "due_date": "2026-07-22",
                "tags": None,
                "deadline_group_id": "per-doc-old",  # 上書きされる想定
                "deadline_offset_days": 999,  # 上書きされる想定
                "deadline_base_date": "old",  # 上書きされる想定
            },
        ]

    monkeypatch.setattr(submission_agent, "build_submission_task_drafts", fake_drafts)

    # 元タスク(親): 最終提出期限(due_date)を持つ。
    info = _create(title="就労証明書の提出", content="メモ", due_date="2026-07-30")

    resp = client.post(f"/api/info/{info['id']}/investigate-deadline")
    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] == 1
    child_id = resp.json()["ids"][0]

    # 元タスク(親)がグループのアンカー(offset 0, base_date=親の期限)になっていること。
    parent = client.get(f"/api/info/{info['id']}").json()
    assert parent["deadline_group_id"], parent
    assert parent["deadline_offset_days"] == 0
    assert parent["deadline_base_date"] == "2026-07-30"

    # 生成された子タスクが親と同じグループに属し、offset > 0（基準日変更ボタン非表示の対象）。
    child = client.get(f"/api/info/{child_id}").json()
    assert child["deadline_group_id"] == parent["deadline_group_id"]
    assert child["deadline_offset_days"] == 8  # 2026-07-30 - 2026-07-22


def test_investigate_no_anchor_when_base_date_empty(monkeypatch):
    """SOT-1411 再オープン: 元タスクに最終提出期限が無い場合はグループ化・アンカー化しない。"""
    monkeypatch.setattr("app.routers.info.index_info_id", lambda *a, **k: None)

    def fake_drafts(safe_text, detected_dates=None, **kwargs):
        return [
            {
                "title": "在籍証明書の準備",
                "info_type": "提出物",
                "content": "c",
                "items": "",
                "date": "",
                "event_date": "",
                "due_date": "",
                "tags": None,
                "deadline_group_id": "g",
                "deadline_offset_days": None,
                "deadline_base_date": "",
            },
        ]

    monkeypatch.setattr(submission_agent, "build_submission_task_drafts", fake_drafts)

    # 期限を一切持たない元タスク。
    info = _create(title="就労証明書の提出", content="メモ")

    resp = client.post(f"/api/info/{info['id']}/investigate-deadline")
    assert resp.status_code == 200, resp.text

    parent = client.get(f"/api/info/{info['id']}").json()
    # 基準日が無いのでアンカー化されない（offset 0 にならない）。
    assert parent["deadline_offset_days"] != 0
