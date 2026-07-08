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
from app import storage as storage_mod
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


def test_existing_user_without_data_is_resynced():
    """SOT-1507 再同期: マーカーは持つがデータが無い既存ユーザーにも配布する。

    マーカーではなく「本登録タスクを持つか」で判定するため、旧仕様でシード済み扱いだった
    （マーカーだけ存在する）既存ユーザーでも、データが無ければ次回ログイン時に配布される。
    """
    _seed_default_owner_data()

    # 既にマーカーだけ存在する既存ユーザー（データは未保有）を用意する。
    db = TestingSessionLocal()
    try:
        db.add(models.SeededOwner(owner_id="existingEmpty"))
        db.commit()
    finally:
        db.close()

    assert ensure_user_seeded("existingEmpty") is True

    titles = sorted(i.title for i in _infos_for("existingEmpty"))
    assert titles == ["健康診断票の提出", "遠足のお知らせ"]
    assert [c.name for c in _children_for("existingEmpty")] == ["あお"]


def _add_default_owner_photo(info_title, upload_dir, content=b"PHOTOBYTES", write_blob=True):
    """SOT-1600: 既定オーナーの指定タスクに写真(添付)1件（と実体ファイル）を用意する。"""
    stored = storage_mod.generate_stored_filename("photo.png")
    object_key = storage_mod.build_object_key(stored)
    if write_blob:
        (upload_dir / object_key).write_bytes(content)
    db = TestingSessionLocal()
    try:
        info = (
            db.query(models.NurseryInfo)
            .filter(
                models.NurseryInfo.owner_id == DEFAULT_OWNER_ID,
                models.NurseryInfo.title == info_title,
            )
            .first()
        )
        db.add(
            models.Attachment(
                info_id=info.id,
                stored_filename=stored,
                original_filename="photo.png",
                mime_type="image/png",
                file_size=len(content),
                storage_backend="local",
                object_key=object_key,
                ocr_text="運動会は10月",
                ocr_status="done",
            )
        )
        db.commit()
        return stored, object_key
    finally:
        db.close()


def _attachments_for_owner(owner_id):
    db = TestingSessionLocal()
    try:
        ids = [i.id for i in _infos_for(owner_id)]
        if not ids:
            return []
        return (
            db.query(models.Attachment)
            .filter(models.Attachment.info_id.in_(ids))
            .all()
        )
    finally:
        db.close()


def test_photos_are_copied_from_default_owner(monkeypatch, tmp_path):
    """SOT-1600: 既定オーナーの写真(添付)も新オーナーへ独立した実体コピーとして配布される。"""
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setattr(storage_mod, "UPLOAD_DIR", tmp_path)
    _seed_default_owner_data()
    src_stored, src_key = _add_default_owner_photo("遠足のお知らせ", tmp_path, b"PHOTOBYTES")

    assert ensure_user_seeded("ownerX") is True

    atts = _attachments_for_owner("ownerX")
    assert len(atts) == 1
    att = atts[0]
    # スカラー項目（原文/OCR/種別等）はそのままコピーされる。
    assert att.original_filename == "photo.png"
    assert att.mime_type == "image/png"
    assert att.ocr_text == "運動会は10月"
    assert att.ocr_status == "done"
    assert att.file_size == len(b"PHOTOBYTES")
    # 実体は独立コピー（stored_filename / object_key は作り直され、元を指さない）。
    assert att.stored_filename != src_stored
    assert att.object_key != src_key
    # 新しいキーで実体ファイルが存在し、内容が一致する。
    assert (tmp_path / att.object_key).read_bytes() == b"PHOTOBYTES"
    # 元オーナーの実体ファイルは残っている（破壊しない）。
    assert (tmp_path / src_key).read_bytes() == b"PHOTOBYTES"


def test_photo_is_attached_to_the_matching_copied_task(monkeypatch, tmp_path):
    """写真は正しいコピー先タスク（同一タイトル）に紐づく。"""
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setattr(storage_mod, "UPLOAD_DIR", tmp_path)
    _seed_default_owner_data()
    _add_default_owner_photo("遠足のお知らせ", tmp_path)

    assert ensure_user_seeded("ownerX") is True

    infos = {i.title: i for i in _infos_for("ownerX")}
    atts = _attachments_for_owner("ownerX")
    assert len(atts) == 1
    assert atts[0].info_id == infos["遠足のお知らせ"].id


def test_seeding_skips_photo_when_blob_missing(monkeypatch, tmp_path):
    """SOT-1600: 実体ファイルが無い添付は best-effort でスキップし、配布は止めない。"""
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setattr(storage_mod, "UPLOAD_DIR", tmp_path)
    _seed_default_owner_data()
    # 実体ファイルを作らずに添付レコードだけ用意する。
    _add_default_owner_photo("遠足のお知らせ", tmp_path, write_blob=False)

    assert ensure_user_seeded("ownerX") is True

    # タスク自体は配布され、壊れた添付レコードは作られない。
    assert sorted(i.title for i in _infos_for("ownerX")) == ["健康診断票の提出", "遠足のお知らせ"]
    assert _attachments_for_owner("ownerX") == []


def test_existing_user_with_own_data_is_not_overwritten():
    """SOT-1507 再同期: 既に自分のデータを持つユーザーは上書きしない（編集を保護）。"""
    _seed_default_owner_data()

    # 自分で作成した本登録タスクを1件持つ既存ユーザー。
    db = TestingSessionLocal()
    try:
        db.add(
            models.NurseryInfo(
                owner_id="ownerWithData",
                title="自分で作ったタスク",
                info_type="メモ",
                content="ユーザー固有データ",
            )
        )
        db.commit()
    finally:
        db.close()

    assert ensure_user_seeded("ownerWithData") is False

    # 既定オーナーのデータは配布されず、自分のデータだけが残っている。
    titles = [i.title for i in _infos_for("ownerWithData")]
    assert titles == ["自分で作ったタスク"]
    assert _children_for("ownerWithData") == []
