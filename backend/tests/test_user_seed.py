"""SOT-1507: 新規ユーザー初回ログイン時の初期データ配布（案B）のテスト。

既定オーナー（sota.moro@gmail.com）のデータを正とし、新規ユーザーの初回ログイン時に
やることタスク（NurseryInfo）と子ども（Child）を独立コピーとして配布する。オーナーごとに
一度だけ実行する（冪等）。
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app import database, models
from app.identity import DEFAULT_OWNER_ID
from app.user_seed import ensure_user_seeded

SQLALCHEMY_DATABASE_URL = "sqlite://"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_and_teardown(monkeypatch):
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(database, "SessionLocal", TestingSessionLocal)
    yield
    Base.metadata.drop_all(bind=engine)


def _seed_default_owner_data():
    """既定オーナーのデータ（子ども1件 + タスク3件、うち1件は draft）を用意する。"""
    db = TestingSessionLocal()
    try:
        child = models.Child(owner_id=DEFAULT_OWNER_ID, name="あお")
        db.add(child)
        db.flush()

        db.add(
            models.NurseryInfo(
                owner_id=DEFAULT_OWNER_ID,
                title="遠足のお知らせ",
                info_type="行事",
                content="来週遠足です",
                status="対応中",
                is_favorite=True,
                priority="高",
                tags="行事,遠足",
                child_id=str(child.id),
            )
        )
        db.add(
            models.NurseryInfo(
                owner_id=DEFAULT_OWNER_ID,
                title="健康診断票の提出",
                info_type="提出物",
                content="月曜までに提出",
                status="対応済",
                is_favorite=False,
            )
        )
        # draft はコピー対象外
        db.add(
            models.NurseryInfo(
                owner_id=DEFAULT_OWNER_ID,
                title="仮登録タスク",
                info_type="行事",
                content="draft",
                registration_state="draft",
            )
        )
        db.commit()
        return child.id
    finally:
        db.close()


def _infos_for(owner_id):
    db = TestingSessionLocal()
    try:
        return (
            db.query(models.NurseryInfo)
            .filter(models.NurseryInfo.owner_id == owner_id)
            .all()
        )
    finally:
        db.close()


def _children_for(owner_id):
    db = TestingSessionLocal()
    try:
        return (
            db.query(models.Child)
            .filter(models.Child.owner_id == owner_id)
            .all()
        )
    finally:
        db.close()


def test_new_user_gets_copy_of_default_owner_data():
    src_child_id = _seed_default_owner_data()

    assert ensure_user_seeded("ownerX") is True

    infos = _infos_for("ownerX")
    titles = sorted(i.title for i in infos)
    # 本登録2件のみコピー（draft は除外）
    assert titles == ["健康診断票の提出", "遠足のお知らせ"]

    children = _children_for("ownerX")
    assert [c.name for c in children] == ["あお"]

    # child_id は新オーナーの Child.id にリマップされている（旧 id を指さない）。
    excursion = next(i for i in infos if i.title == "遠足のお知らせ")
    assert excursion.child_id == str(children[0].id)
    assert excursion.child_id != str(src_child_id)


def test_status_and_favorite_are_copied_from_default_owner():
    """対応ステータス（status）とお気に入り（is_favorite）も既定オーナーの値どおりに配布される。"""
    _seed_default_owner_data()

    assert ensure_user_seeded("ownerX") is True

    infos = {i.title: i for i in _infos_for("ownerX")}

    # お気に入り + 対応中 のタスクは、その状態のままコピーされる。
    excursion = infos["遠足のお知らせ"]
    assert excursion.status == "対応中"
    assert excursion.is_favorite is True

    # 非お気に入り + 対応済 のタスクも、その状態のままコピーされる。
    checkup = infos["健康診断票の提出"]
    assert checkup.status == "対応済"
    assert checkup.is_favorite is False


def test_seeding_is_idempotent_per_owner():
    _seed_default_owner_data()

    assert ensure_user_seeded("ownerX") is True
    # 2回目はスキップされ、重複しない。
    assert ensure_user_seeded("ownerX") is False
    assert len(_infos_for("ownerX")) == 2
    assert len(_children_for("ownerX")) == 1

    # マーカーが記録されている。
    db = TestingSessionLocal()
    try:
        assert (
            db.query(models.SeededOwner)
            .filter(models.SeededOwner.owner_id == "ownerX")
            .first()
            is not None
        )
    finally:
        db.close()


def test_default_owner_is_not_seeded():
    _seed_default_owner_data()

    # 既定オーナー自身にはコピーしない（そのデータが正）。
    assert ensure_user_seeded(DEFAULT_OWNER_ID) is False
    # 既定オーナーのデータは元の2件（本登録）のまま増えていない。
    registered = [
        i
        for i in _infos_for(DEFAULT_OWNER_ID)
        if (i.registration_state or "registered") == "registered"
    ]
    assert len(registered) == 2


def test_empty_owner_id_is_ignored():
    _seed_default_owner_data()
    assert ensure_user_seeded("") is False
