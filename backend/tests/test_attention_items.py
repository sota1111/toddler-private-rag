"""SOT-2734: 要確認（Attention Item）の登録時生成・根拠付き永続化・確認済/非該当分類のテスト。

検証観点（受け入れ条件対応）:
- おたより登録(照合)時に要確認項目が**根拠付きで**生成・永続化される。
- 「なぜ」根拠（該当文書箇所/対応プロファイル項目/信頼度）が各項目に付与される。
- 保護者が「確認済/非該当」を分類でき、状態が永続化される。
- 断定表現（安全/食べられる）を出さない（照合エンジンの契約踏襲）。
- owner 分離／再登録の冪等（二重生成しない）／子ども未紐付け・プロファイル無しは何も作らない。
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.routers.auth import get_current_user
from app import database, models, care_attention
from app.repository import (
    SqliteCareProfileRepository,
    SqliteAttentionItemRepository,
)

SQLALCHEMY_DATABASE_URL = "sqlite://"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

_current_owner = {"id": "ownerA"}


def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


def override_get_current_user():
    return _current_owner["id"]


@pytest.fixture(autouse=True)
def setup_and_teardown(monkeypatch):
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(database, "SessionLocal", TestingSessionLocal)
    monkeypatch.setitem(app.dependency_overrides, get_db, override_get_db)
    monkeypatch.setitem(app.dependency_overrides, get_current_user, override_get_current_user)
    _current_owner["id"] = "ownerA"
    yield
    Base.metadata.drop_all(bind=engine)


client = TestClient(app)


def _as(owner: str):
    _current_owner["id"] = owner


def _make_child(name: str = "たろう") -> str:
    return str(client.post("/api/children", json={"name": name}).json()["id"])


def _make_profile(child_id: str, **kwargs):
    body = {"child_id": child_id, **kwargs}
    return client.post("/api/care-profiles", json=body).json()


def _egg_menu(day="2026-09-01"):
    return {
        "month": day[:7],
        "days": [
            {
                "date": day,
                "lunch": ["親子丼"],
                "main_ingredients": {"red": ["鶏卵", "豆腐"], "yellow": [], "green": [], "other": []},
            }
        ],
    }


def _generate(info_id, child_id, owner_id="ownerA", notice_text=None, menu_json=None):
    """API 越しではなく生成サービスを直接叩いて要確認項目を作る（登録フロー相当）。"""
    db = TestingSessionLocal()
    try:
        care_repo = SqliteCareProfileRepository(db, owner_id=owner_id)
        attention_repo = SqliteAttentionItemRepository(db, owner_id=owner_id)
        return care_attention.generate_attention_items(
            info_id=info_id,
            child_id=child_id,
            owner_id=owner_id,
            notice_text=notice_text,
            menu_json=menu_json,
            care_repo=care_repo,
            attention_repo=attention_repo,
            use_llm=False,
        )
    finally:
        db.close()


# =========================== 生成（受け入れ条件1） ===============================


def test_generation_creates_attention_item_with_evidence():
    child = _make_child()
    _make_profile(child, allergens=["たまご"])
    created = _generate(1001, child, notice_text="9月の献立表", menu_json=_egg_menu())
    assert created, "要確認項目が生成されない"

    items = client.get("/api/attention-items").json()
    assert len(items) == len(created)
    egg = next(i for i in items if i["canonical"] == "egg")
    assert egg["kind"] == "allergen"
    assert egg["status"] == "attention"
    assert egg["review_status"] == "unreviewed"
    assert egg["reviewed_at"] is None
    assert egg["source_info_id"] == "1001"
    assert egg["child_id"] == str(child)
    # 根拠3要素（受け入れ条件2: なぜ）
    ev = egg["evidence"]
    assert ev["span"]
    assert ev["profile_item"]
    assert ev["confidence"] == "high"
    assert ev["source"] == "menu_json"


def test_generated_message_has_no_assertive_safety_language():
    """断定表現（安全/食べられる）を出さない（要確認/情報不足のみ）。"""
    child = _make_child()
    _make_profile(child, allergens=["たまご"])
    _generate(1002, child, notice_text="9月の献立表", menu_json=_egg_menu())
    for item in client.get("/api/attention-items").json():
        assert "安全" not in item["message"]
        assert "食べられます" not in item["message"]
        assert "要確認" in item["message"]


def test_no_child_no_profile_generates_nothing():
    # 子ども未紐付け
    assert _generate(1003, None, notice_text="卵を使います", menu_json=_egg_menu()) == []
    # プロファイル無しの子ども
    child = _make_child("はなこ")
    assert _generate(1004, child, notice_text="卵を使います", menu_json=_egg_menu()) == []
    assert client.get("/api/attention-items").json() == []


def test_regeneration_is_idempotent_per_source():
    """同じおたより(source_info_id)の再登録は既存を作り直す（二重生成しない）。"""
    child = _make_child()
    _make_profile(child, allergens=["たまご"])
    first = _generate(1005, child, notice_text="9月の献立表", menu_json=_egg_menu())
    second = _generate(1005, child, notice_text="9月の献立表", menu_json=_egg_menu())
    assert len(first) == len(second)
    items = client.get("/api/attention-items?source_info_id=1005").json()
    assert len(items) == len(second)  # 累積せず作り直しになっている


# =========================== 分類（受け入れ条件3） ===============================


def test_review_confirmed_and_not_applicable_flow():
    child = _make_child()
    _make_profile(child, allergens=["たまご"])
    _generate(1006, child, notice_text="9月の献立表", menu_json=_egg_menu())
    item = client.get("/api/attention-items").json()[0]
    iid = item["id"]

    # 確認済
    r = client.patch(f"/api/attention-items/{iid}/review", json={"review_status": "confirmed"})
    assert r.status_code == 200
    assert r.json()["review_status"] == "confirmed"
    assert r.json()["reviewed_at"] is not None

    # 非該当（誤検出）
    r = client.patch(f"/api/attention-items/{iid}/review", json={"review_status": "not_applicable"})
    assert r.status_code == 200
    assert r.json()["review_status"] == "not_applicable"

    # 未確認へ戻すと reviewed_at がクリアされる
    r = client.patch(f"/api/attention-items/{iid}/review", json={"review_status": "unreviewed"})
    assert r.status_code == 200
    assert r.json()["review_status"] == "unreviewed"
    assert r.json()["reviewed_at"] is None


def test_review_invalid_status_rejected():
    child = _make_child()
    _make_profile(child, allergens=["たまご"])
    _generate(1007, child, notice_text="9月の献立表", menu_json=_egg_menu())
    iid = client.get("/api/attention-items").json()[0]["id"]
    assert client.patch(
        f"/api/attention-items/{iid}/review", json={"review_status": "done"}
    ).status_code == 422


def test_review_missing_item_returns_404():
    assert client.patch(
        "/api/attention-items/99999/review", json={"review_status": "confirmed"}
    ).status_code == 404
    assert client.get("/api/attention-items/99999").status_code == 404


# =========================== 一覧フィルタ ===============================


def test_list_filters_by_child_source_and_review_status():
    c1 = _make_child("たろう")
    c2 = _make_child("はなこ")
    _make_profile(c1, allergens=["たまご"])
    _make_profile(c2, allergens=["たまご"])
    _generate(2001, c1, notice_text="献立", menu_json=_egg_menu())
    _generate(2002, c2, notice_text="献立", menu_json=_egg_menu())

    # child_id で絞り込み
    only_c1 = client.get(f"/api/attention-items?child_id={c1}").json()
    assert only_c1 and all(i["child_id"] == str(c1) for i in only_c1)

    # source_info_id で絞り込み
    only_src = client.get("/api/attention-items?source_info_id=2002").json()
    assert only_src and all(i["source_info_id"] == "2002" for i in only_src)

    # review_status で絞り込み
    iid = only_c1[0]["id"]
    client.patch(f"/api/attention-items/{iid}/review", json={"review_status": "confirmed"})
    confirmed = client.get("/api/attention-items?review_status=confirmed").json()
    assert [i["id"] for i in confirmed] == [iid]
    unreviewed = client.get("/api/attention-items?review_status=unreviewed").json()
    assert iid not in [i["id"] for i in unreviewed]

    # 不正な review_status は 422
    assert client.get("/api/attention-items?review_status=bogus").status_code == 422


# =========================== owner 分離 ===============================


def test_attention_items_are_owner_scoped():
    _as("ownerA")
    a_child = _make_child()
    _make_profile(a_child, allergens=["たまご"])
    _generate(3001, a_child, owner_id="ownerA", notice_text="献立", menu_json=_egg_menu())
    a_item = client.get("/api/attention-items").json()[0]

    # ownerB は ownerA の要確認項目を一覧・取得・レビューできない
    _as("ownerB")
    assert client.get("/api/attention-items").json() == []
    assert client.get(f"/api/attention-items/{a_item['id']}").status_code == 404
    assert client.patch(
        f"/api/attention-items/{a_item['id']}/review", json={"review_status": "confirmed"}
    ).status_code == 404

    # ownerA 自身の項目は無傷
    _as("ownerA")
    assert client.get(f"/api/attention-items/{a_item['id']}").json()["review_status"] == "unreviewed"


# =========================== 登録フックのラッパ配線 ===============================


def test_attachments_hook_wrapper_generates_via_standalone_repos():
    """登録昇格フック(_generate_attention_items)が standalone repo 経由で生成できる。

    背景 OCR 経路と同様に database.SessionLocal(テストでは差し替え済み) からリポジトリを
    構築し、owner を継承して要確認項目を永続化する配線を検証する。
    """
    from app.routers import attachments

    child = _make_child()
    _make_profile(child, allergens=["たまご"])
    attachments._generate_attention_items(
        info_id=4001,
        child_id=child,
        owner_id="ownerA",
        notice_text="9月の献立表",
        menu_json=_egg_menu(),
    )
    items = client.get("/api/attention-items?source_info_id=4001").json()
    assert items and any(i["canonical"] == "egg" for i in items)


# =========================== additive migration 非破壊性 ===============================


def test_existing_rows_survive_attention_item_table():
    """attention_item 追加後も既存 Child 行が読める(additive/非破壊)ことを確認する。"""
    from app.migrations import ensure_sqlite_schema

    db = TestingSessionLocal()
    try:
        db.add(models.Child(name="既存の子", owner_id="ownerA"))
        db.commit()
    finally:
        db.close()

    ensure_sqlite_schema(engine)  # 冪等・非破壊

    _as("ownerA")
    children = client.get("/api/children").json()
    assert any(c["name"] == "既存の子" for c in children)
