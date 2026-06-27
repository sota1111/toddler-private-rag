"""SOT-1293/SOT-1324: 写真登録の enrich→永続化→昇格をサーバ側 background task で行う検証。

写真アップロードをトリガーに、processing のレコードがサーバ側で昇格すること
（ブラウザの PUT/extract に依存しない）、写真紐付けが維持されること、registered には
副作用が無いこと、OCR 失敗時もフォールバックタイトルで昇格することを確認する。

SOT-1324: 写真(メイン)レコードは本登録(finalize)を介さず直接 registered へ昇格し、
写真一覧(GET /info/)に即時に出る（仮登録一覧 drafts には出ない）。
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import ocr, models, database
from app.database import Base, get_db
from app.routers.auth import get_current_user
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

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


def override_get_current_user():
    return "test_user"


@pytest.fixture(autouse=True)
def setup_db(monkeypatch):
    Base.metadata.create_all(bind=engine)
    # process_ocr / get_info_repo_standalone が同じ in-memory DB を使うよう SessionLocal を差し替える
    monkeypatch.setattr(database, "SessionLocal", TestingSessionLocal)
    monkeypatch.setitem(app.dependency_overrides, get_db, override_get_db)
    monkeypatch.setitem(app.dependency_overrides, get_current_user, override_get_current_user)
    yield
    Base.metadata.drop_all(bind=engine)


client = TestClient(app)


def _create_info(registration_state: str) -> int:
    resp = client.post(
        "/api/info/",
        json={
            "title": "",
            "info_type": "資料",
            "content": "",
            "registration_state": registration_state,
        },
    )
    assert resp.status_code == 200
    return resp.json()["id"]


def _upload(info_id: int):
    return client.post(
        f"/api/info/{info_id}/attachments",
        files={"file": ("test.png", b"fake image", "image/png")},
    )


def test_processing_record_promoted_to_registered_server_side(monkeypatch):
    """SOT-1324: processing レコードは写真アップロードをトリガーにサーバ側で
    本登録(registered)へ直接昇格する（本登録ステップを介さない）。"""
    monkeypatch.setattr(
        ocr, "extract_text", lambda *a, **k: "プール開きのお知らせ\n水着を持参してください"
    )

    info_id = _create_info("processing")
    resp = _upload(info_id)
    assert resp.status_code == 200
    att_id = resp.json()["id"]

    db = TestingSessionLocal()
    info = db.query(models.NurseryInfo).filter(models.NurseryInfo.id == info_id).first()
    # ブラウザの PUT 無しで registered へ直接昇格している（draft を介さない）
    assert info.registration_state == "registered"
    assert info.title  # タイトルが付与されている（OCR本文の先頭行 or enrich由来）
    assert info.content  # 本文(RAG対象)が空でない
    # 写真紐付けが維持されている
    att = db.query(models.Attachment).filter(models.Attachment.id == att_id).first()
    assert att is not None
    assert att.info_id == info_id
    db.close()

    # 写真一覧(GET /info/ = registered のみ)に出る
    registered = client.get("/api/info/").json()
    assert any(r["id"] == info_id for r in registered)
    # 仮登録一覧(drafts)には出ない
    drafts = client.get("/api/info/drafts").json()
    assert all(d["id"] != info_id for d in drafts)


def test_registered_record_not_modified(monkeypatch):
    """通常の手動添付(registered)には enrich/昇格の副作用が無い。"""
    monkeypatch.setattr(ocr, "extract_text", lambda *a, **k: "なにかのテキスト")

    info_id = _create_info("registered")
    resp = _upload(info_id)
    assert resp.status_code == 200

    db = TestingSessionLocal()
    info = db.query(models.NurseryInfo).filter(models.NurseryInfo.id == info_id).first()
    assert info.registration_state == "registered"
    assert info.title == ""  # 触られていない
    db.close()


def test_processing_record_promoted_even_on_ocr_failure(monkeypatch):
    """OCR 失敗時もフォールバックタイトルで registered 昇格し、写真付きで写真一覧に出す。"""

    def boom(*a, **k):
        raise Exception("OCR Error")

    monkeypatch.setattr(ocr, "extract_text", boom)

    info_id = _create_info("processing")
    resp = _upload(info_id)
    assert resp.status_code == 200
    att_id = resp.json()["id"]

    db = TestingSessionLocal()
    info = db.query(models.NurseryInfo).filter(models.NurseryInfo.id == info_id).first()
    assert info.registration_state == "registered"
    assert info.title.startswith("写真から登録")
    att = db.query(models.Attachment).filter(models.Attachment.id == att_id).first()
    assert att.ocr_status == "failed"
    assert att.info_id == info_id
    db.close()
