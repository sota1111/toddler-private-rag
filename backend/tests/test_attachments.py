import pytest
import os
import shutil
import datetime
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from pathlib import Path

from app.main import app
from app.database import Base, get_db
from app.routers.auth import get_current_user
from app import storage, models, database

# Test database setup
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
def setup_and_teardown(tmp_path, monkeypatch):
    # Setup
    Base.metadata.create_all(bind=engine)
    # Patch SessionLocal so process_ocr uses the same in-memory DB
    monkeypatch.setattr(database, "SessionLocal", TestingSessionLocal)
    
    # Dependency overrides
    monkeypatch.setitem(app.dependency_overrides, get_db, override_get_db)
    monkeypatch.setitem(app.dependency_overrides, get_current_user, override_get_current_user)
    
    test_upload_dir = tmp_path / "uploads"
    os.makedirs(test_upload_dir, exist_ok=True)
    
    # Override storage directory
    original_upload_dir = storage.UPLOAD_DIR
    storage.UPLOAD_DIR = test_upload_dir
    
    yield
    
    # Teardown
    Base.metadata.drop_all(bind=engine)
    if test_upload_dir.exists():
        shutil.rmtree(test_upload_dir)
    storage.UPLOAD_DIR = original_upload_dir

client = TestClient(app)

def test_upload_and_get_attachment():
    # 1. Create a NurseryInfo
    response = client.post(
        "/api/info/",
        json={
            "title": "Test Info",
            "info_type": "行事",
            "content": "Test content"
        }
    )
    assert response.status_code == 200
    info_id = response.json()["id"]

    # 2. Upload a file
    file_content = b"fake image content"
    response = client.post(
        f"/api/info/{info_id}/attachments",
        files={"file": ("test.png", file_content, "image/png")}
    )
    assert response.status_code == 200
    att_data = response.json()
    assert att_data["original_filename"] == "test.png"
    assert att_data["mime_type"] == "image/png"
    assert "stored_filename" not in att_data
    assert "ocr_text" not in att_data
    att_id = att_data["id"]

    # 3. Get info and check attachments
    response = client.get(f"/api/info/{info_id}")
    assert response.status_code == 200
    assert len(response.json()["attachments"]) == 1
    assert response.json()["attachments"][0]["id"] == att_id

    # 4. Download file
    response = client.get(f"/api/attachments/{att_id}/file")
    assert response.status_code == 200
    assert response.content == file_content
    assert response.headers["content-type"] == "image/png"
    # SOT-1275: served inline so clicking an image opens (not downloads) in the browser
    assert response.headers["content-disposition"].startswith("inline")

def test_get_attachment_file_gcs_streams_inline(monkeypatch):
    """SOT-1282: GCS-backed attachments must be streamed inline by the backend.

    On Cloud Run the default compute service-account credentials have no private
    key, so generating a V4 signed URL raises and the endpoint 500s -> broken
    image. The GCS branch must instead download the bytes and serve them inline.
    """
    # 1. Create info + upload an image (stored locally by default in tests)
    info_id = client.post(
        "/api/info/",
        json={"title": "T", "info_type": "行事", "content": "c"},
    ).json()["id"]
    img_bytes = b"\xff\xd8\xff fake-jpeg-bytes \xff\xd9"
    att_id = client.post(
        f"/api/info/{info_id}/attachments",
        files={"file": ("photo.jpg", img_bytes, "image/jpeg")},
    ).json()["id"]

    # 2. Mark the stored attachment as GCS-backed
    db = TestingSessionLocal()
    att = db.query(models.Attachment).filter(models.Attachment.id == att_id).first()
    att.storage_backend = "gcs"
    att.object_key = "uploads/photo.jpg"
    db.commit()
    db.close()

    # 3. Fake GCS storage that returns bytes without touching real GCS / signing
    fake = storage.GCSStorage()
    monkeypatch.setattr(fake, "read", lambda object_key: img_bytes)
    monkeypatch.setattr(storage, "get_storage", lambda: fake)

    resp = client.get(f"/api/attachments/{att_id}/file")
    assert resp.status_code == 200
    assert resp.content == img_bytes
    assert resp.headers["content-type"] == "image/jpeg"
    assert resp.headers["content-disposition"].startswith("inline")


def test_upload_unsupported_type():
    # 1. Create a NurseryInfo
    response = client.post(
        "/api/info/",
        json={"title": "Test", "info_type": "行事", "content": "Test"}
    )
    info_id = response.json()["id"]

    # 2. Upload text file
    response = client.post(
        f"/api/info/{info_id}/attachments",
        files={"file": ("test.txt", b"hello", "text/plain")}
    )
    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]

def test_upload_oversized_file():
    # 1. Create a NurseryInfo
    response = client.post(
        "/api/info/",
        json={"title": "Test", "info_type": "行事", "content": "Test"}
    )
    info_id = response.json()["id"]

    # 2. Upload large file (11MB)
    large_content = b"a" * (11 * 1024 * 1024)
    response = client.post(
        f"/api/info/{info_id}/attachments",
        files={"file": ("large.png", large_content, "image/png")}
    )
    assert response.status_code == 413

def test_upload_allows_any_image_content_type():
    response = client.post(
        "/api/info/",
        json={"title": "Test", "info_type": "行事", "content": "Test"}
    )
    info_id = response.json()["id"]

    response = client.post(
        f"/api/info/{info_id}/attachments",
        files={"file": ("test.webp", b"image", "image/webp")}
    )
    assert response.status_code == 200

def test_delete_attachment():
    # 1. Create info and upload
    response = client.post("/api/info/", json={"title": "T", "info_type": "行事", "content": "C"})
    info_id = response.json()["id"]
    response = client.post(
        f"/api/info/{info_id}/attachments",
        files={"file": ("test.png", b"data", "image/png")}
    )
    att_id = response.json()["id"]
    stored_filename = models.Attachment.stored_filename
    
    # Check file exists
    db = next(override_get_db())
    att = db.query(models.Attachment).filter(models.Attachment.id == att_id).first()
    file_path = storage.get_file_path(att.stored_filename)
    assert file_path.exists()

    # 2. Delete attachment
    response = client.delete(f"/api/attachments/{att_id}")
    assert response.status_code == 200
    
    # 3. Verify deleted
    assert not file_path.exists()
    response = client.get(f"/api/attachments/{att_id}/file")
    assert response.status_code == 404

def test_delete_info_removes_attachments():
    # 1. Create info and upload
    response = client.post("/api/info/", json={"title": "T", "info_type": "行事", "content": "C"})
    info_id = response.json()["id"]
    response = client.post(
        f"/api/info/{info_id}/attachments",
        files={"file": ("test.png", b"data", "image/png")}
    )
    att_id = response.json()["id"]
    db = next(override_get_db())
    att = db.query(models.Attachment).filter(models.Attachment.id == att_id).first()
    file_path = storage.get_file_path(att.stored_filename)
    
    # 2. Delete info
    response = client.delete(f"/api/info/{info_id}")
    assert response.status_code == 200
    
    # 3. Verify attachment and file are gone
    assert not file_path.exists()
    db = next(override_get_db())
    assert db.query(models.Attachment).filter(models.Attachment.id == att_id).first() is None

def test_create_info_without_file():
    response = client.post(
        "/api/info/",
        json={
            "title": "Test Info",
            "info_type": "行事",
            "content": "Test content"
        }
    )
    assert response.status_code == 200
    assert response.json()["attachments"] == []


def test_list_include_attachments_param():
    """SOT-1240: include_attachments=false でタイトル一覧の添付取得(N+1)をスキップする。"""
    # 本登録 info + 添付を用意
    info_id = client.post(
        "/api/info/", json={"title": "with-att", "info_type": "行事", "content": "C"}
    ).json()["id"]
    client.post(
        f"/api/info/{info_id}/attachments",
        files={"file": ("test.png", b"data", "image/png")},
    )

    # 仮登録(draft) は一覧に出ない（軽量モードでも除外維持）
    client.post(
        "/api/info/",
        json={"title": "draft-x", "info_type": "行事", "content": "C",
              "registration_state": "draft"},
    )

    # 既定（include_attachments 省略）: 添付が従来どおり返る
    default_items = client.get("/api/info/").json()
    target = next(i for i in default_items if i["id"] == info_id)
    assert len(target["attachments"]) == 1
    assert "draft-x" not in {i["title"] for i in default_items}

    # 軽量モード: 同じ本登録データが返るが添付は空配列
    light_items = client.get("/api/info/", params={"include_attachments": "false"}).json()
    light_target = next(i for i in light_items if i["id"] == info_id)
    assert light_target["title"] == "with-att"
    assert light_target["attachments"] == []
    assert "draft-x" not in {i["title"] for i in light_items}


# --- SOT-1325: 文字起こし(OCR原文)を設定言語で表示するための翻訳・エンドポイント ---

def test_translate_text_fallbacks(monkeypatch):
    from app import extraction, ai_client

    # 空テキストはそのまま空を返す（LLM を呼ばない）
    assert extraction.translate_text("", "en") == ""
    assert extraction.translate_text("   ", "ja") == "   "

    # LLM 不可のときは原文をそのまま返す（決して例外を投げない）
    monkeypatch.setattr(ai_client, "gemini_available", lambda: False)
    assert extraction.translate_text("今月の給食は和食中心です。", "en") == "今月の給食は和食中心です。"


def test_get_attachment_transcription(monkeypatch):
    from app import extraction

    # 翻訳はモック化して内容を決定的にする（言語のみ変換のイメージ）
    monkeypatch.setattr(
        extraction, "translate_text", lambda text, language: f"[{language}] {text}"
    )

    info_id = client.post(
        "/api/info/",
        json={"title": "T", "info_type": "行事", "content": "c"},
    ).json()["id"]
    att_id = client.post(
        f"/api/info/{info_id}/attachments",
        files={"file": ("photo.png", b"img", "image/png")},
    ).json()["id"]

    # OCR 原文を直接保存（process_ocr 相当）
    db = TestingSessionLocal()
    att = db.query(models.Attachment).filter(models.Attachment.id == att_id).first()
    att.ocr_text = "今月の給食は和食中心です。"
    att.ocr_status = "done"
    db.commit()
    db.close()

    resp = client.get(f"/api/attachments/{att_id}/transcription", params={"language": "en"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"] == "[en] 今月の給食は和食中心です。"
    assert body["ocr_status"] == "done"
    assert body["language"] == "en"

    # 不正な言語は ja にフォールバックする
    resp_bad = client.get(f"/api/attachments/{att_id}/transcription", params={"language": "fr"})
    assert resp_bad.json()["language"] == "ja"


def test_transcription_translation_is_cached(monkeypatch):
    """SOT-1330: 同一(添付, 言語)への複数回アクセスでも翻訳は一度きり（読み込みの度に翻訳しない）。"""
    from app import extraction

    calls = {"n": 0}

    def fake_translate(text, language):
        calls["n"] += 1
        return f"[{language}] {text}"

    monkeypatch.setattr(extraction, "translate_text", fake_translate)

    info_id = client.post(
        "/api/info/",
        json={"title": "T", "info_type": "行事", "content": "c"},
    ).json()["id"]
    att_id = client.post(
        f"/api/info/{info_id}/attachments",
        files={"file": ("photo.png", b"img", "image/png")},
    ).json()["id"]

    db = TestingSessionLocal()
    att = db.query(models.Attachment).filter(models.Attachment.id == att_id).first()
    att.ocr_text = "今月の給食は和食中心です。"
    att.ocr_status = "done"
    db.commit()
    db.close()

    r1 = client.get(f"/api/attachments/{att_id}/transcription", params={"language": "en"})
    r2 = client.get(f"/api/attachments/{att_id}/transcription", params={"language": "en"})
    assert r1.json()["text"] == "[en] 今月の給食は和食中心です。"
    assert r2.json()["text"] == "[en] 今月の給食は和食中心です。"
    # 2回目はキャッシュ再利用 → 翻訳呼び出しは1回のみ
    assert calls["n"] == 1


def test_get_attachment_transcription_empty_when_no_ocr():
    info_id = client.post(
        "/api/info/",
        json={"title": "T", "info_type": "行事", "content": "c"},
    ).json()["id"]
    att_id = client.post(
        f"/api/info/{info_id}/attachments",
        files={"file": ("photo.png", b"img", "image/png")},
    ).json()["id"]

    resp = client.get(f"/api/attachments/{att_id}/transcription")
    assert resp.status_code == 200
    assert resp.json()["text"] == ""


def test_get_attachment_transcription_404():
    resp = client.get("/api/attachments/999999/transcription")
    assert resp.status_code == 404


# --- SOT-1410: 要調査フラグ true のタスクで締切調査を自動実行する ---

def _make_processing_info():
    """registration_state='processing' の自動登録レコードを作成し info_id を返す。"""
    from app.repository import SqliteInfoRepository
    from app import schemas

    db = TestingSessionLocal()
    try:
        repo = SqliteInfoRepository(db)
        created = repo.create(
            schemas.NurseryInfoCreate(
                title="(processing)",
                info_type="その他",
                content="",
                registration_state="processing",
            )
        )
        return created.id
    finally:
        db.close()


def _all_infos():
    from app import models

    db = TestingSessionLocal()
    try:
        return db.query(models.NurseryInfo).all()
    finally:
        db.close()


def test_auto_deadline_investigation_runs_when_flag_true(monkeypatch):
    from app import extraction, submission_agent
    from app.routers import attachments

    info_id = _make_processing_info()

    monkeypatch.setattr(
        extraction,
        "build_draft_fields",
        lambda *a, **k: {
            "title": "写真から登録",
            "info_type": "その他",
            "content": "本文",
            "items": "",
            "date": "",
        },
    )
    # 1件は要調査フラグ true、もう1件は false。
    monkeypatch.setattr(
        extraction,
        "build_task_drafts",
        lambda *a, **k: [
            {
                "title": "就労証明書の提出",
                "info_type": "提出物",
                "content": "勤務先に依頼",
                "items": "",
                "date": "",
                "event_date": "2026-07-31",
                "needs_deadline_investigation": True,
            },
            {
                "title": "持ち物の準備",
                "info_type": "持ち物",
                "content": "",
                "items": "タオル",
                "date": "",
                "event_date": "",
                "needs_deadline_investigation": False,
            },
        ],
    )

    calls = []

    def fake_build_submission(safe_text, detected_dates=None, **kwargs):
        calls.append({"safe_text": safe_text, "kwargs": kwargs})
        return [
            {
                "title": "就労証明書の準備",
                "info_type": "提出物",
                "content": "手順1",
                "items": "",
                "date": "",
                "event_date": "2026-07-20",
                "due_date": "2026-07-31",
                "tags": submission_agent.SUBMISSION_TAG,
            }
        ]

    monkeypatch.setattr(
        submission_agent, "build_submission_task_drafts", fake_build_submission
    )
    # RAG index は副作用なので無効化。
    monkeypatch.setattr(
        "app.rag.indexing.index_info_id", lambda *a, **k: None, raising=False
    )

    attachments._promote_processing_draft(info_id, "OCRテキスト", None, language="ja")

    # 締切調査はフラグ true のタスクに対して 1 回だけ実行される。
    assert len(calls) == 1
    # タイトル+本文が調査入力に渡る。
    assert "就労証明書の提出" in calls[0]["safe_text"]
    assert "勤務先に依頼" in calls[0]["safe_text"]
    # タスク自身の締切が逆算アンカーとして渡る。
    assert calls[0]["kwargs"].get("final_due_iso") == "2026-07-31"
    # 市町村未指定(空)のときは None が渡り、リンクは付与されない（従来どおり）。
    assert calls[0]["kwargs"].get("municipality") is None

    # 生成された提出準備タスクが draft として永続化される。
    titles = [i.title for i in _all_infos()]
    assert "就労証明書の準備" in titles


def test_auto_deadline_investigation_passes_municipality(monkeypatch):
    """SOT-1405 回帰: 自動締切調査に、アップロード時の設定済み市町村が貫通すること。

    これが無いと `build_submission_task_drafts(municipality=None)` 固定となり、
    市町村のGoogle検索ダウンロードリンクが生成タスクに付与されない（退行の原因）。
    """
    from app import extraction, submission_agent
    from app.routers import attachments

    info_id = _make_processing_info()

    monkeypatch.setattr(
        extraction,
        "build_draft_fields",
        lambda *a, **k: {
            "title": "写真から登録",
            "info_type": "その他",
            "content": "本文",
            "items": "",
            "date": "",
        },
    )
    monkeypatch.setattr(
        extraction,
        "build_task_drafts",
        lambda *a, **k: [
            {
                "title": "就労証明書の提出",
                "info_type": "提出物",
                "content": "勤務先に依頼",
                "items": "",
                "date": "",
                "event_date": "2026-07-31",
                "needs_deadline_investigation": True,
            },
        ],
    )

    calls = []

    def fake_build_submission(safe_text, detected_dates=None, **kwargs):
        calls.append({"safe_text": safe_text, "kwargs": kwargs})
        return []

    monkeypatch.setattr(
        submission_agent, "build_submission_task_drafts", fake_build_submission
    )
    monkeypatch.setattr(
        "app.rag.indexing.index_info_id", lambda *a, **k: None, raising=False
    )

    attachments._promote_processing_draft(
        info_id, "OCRテキスト", None, language="ja", municipality="渋谷区"
    )

    assert len(calls) == 1
    assert calls[0]["kwargs"].get("municipality") == "渋谷区"


def test_auto_deadline_investigation_persists_group_fields(monkeypatch):
    """SOT-1411 回帰: 自動締切調査で生成した提出タスクにも締切グループ情報
    (deadline_group_id / deadline_offset_days / deadline_base_date) が永続化されること。
    これが無いと自動生成されたやることリストは基準日変更で付随タスクをずらせない。"""
    from app import extraction, submission_agent
    from app.routers import attachments

    info_id = _make_processing_info()

    monkeypatch.setattr(
        extraction,
        "build_draft_fields",
        lambda *a, **k: {
            "title": "写真から登録",
            "info_type": "その他",
            "content": "本文",
            "items": "",
            "date": "",
        },
    )
    monkeypatch.setattr(
        extraction,
        "build_task_drafts",
        lambda *a, **k: [
            {
                "title": "就労証明書の提出",
                "info_type": "提出物",
                "content": "勤務先に依頼",
                "items": "",
                "date": "",
                "event_date": "2026-07-31",
                "needs_deadline_investigation": True,
            }
        ],
    )

    # 2 手順の提出準備タスク（同一グループ・基準日あり・オフセットあり）を返す。
    def fake_build_submission(safe_text, detected_dates=None, **kwargs):
        return [
            {
                "title": "就労証明書(1/2) 依頼",
                "info_type": "提出物",
                "content": "手順1",
                "items": "",
                "date": "",
                "event_date": "2026-07-20",
                "due_date": "2026-07-20",
                "tags": submission_agent.SUBMISSION_TAG,
                "deadline_group_id": "grp-1411",
                "deadline_offset_days": 11,
                "deadline_base_date": "2026-07-31",
            },
            {
                "title": "就労証明書(2/2) 提出",
                "info_type": "提出物",
                "content": "手順2",
                "items": "",
                "date": "",
                "event_date": "2026-07-31",
                "due_date": "2026-07-31",
                "tags": submission_agent.SUBMISSION_TAG,
                "deadline_group_id": "grp-1411",
                "deadline_offset_days": 0,
                "deadline_base_date": "2026-07-31",
            },
        ]

    monkeypatch.setattr(
        submission_agent, "build_submission_task_drafts", fake_build_submission
    )
    monkeypatch.setattr(
        "app.rag.indexing.index_info_id", lambda *a, **k: None, raising=False
    )

    attachments._promote_processing_draft(info_id, "OCRテキスト", None, language="ja")

    subs = [i for i in _all_infos() if (i.tags or "") and submission_agent.SUBMISSION_TAG in i.tags]
    assert len(subs) == 2, [i.title for i in _all_infos()]
    # SOT-1411 再オープン: 付随タスク(子)は1つのアンカーグループに束ねられ、基準日(元タスクの期限
    # 2026-07-31)を基準にオフセットが再計算される。group_id は per-doc 値ではなく統一された値。
    gids = {i.deadline_group_id for i in subs}
    assert len(gids) == 1 and next(iter(gids)), gids
    gid = next(iter(gids))
    assert {i.deadline_offset_days for i in subs} == {0, 11}
    assert all(i.deadline_base_date == datetime.date(2026, 7, 31) for i in subs)

    # 元タスク(親=締切調査の実行対象)が同じグループのアンカー(offset 0)になっていること。
    source = next(i for i in _all_infos() if i.title == "就労証明書の提出")
    assert source.deadline_group_id == gid
    assert source.deadline_offset_days == 0
    assert source.deadline_base_date == datetime.date(2026, 7, 31)


def test_auto_deadline_investigation_skipped_when_no_flag(monkeypatch):
    from app import extraction, submission_agent
    from app.routers import attachments

    info_id = _make_processing_info()

    monkeypatch.setattr(
        extraction,
        "build_draft_fields",
        lambda *a, **k: {
            "title": "写真から登録",
            "info_type": "その他",
            "content": "本文",
            "items": "",
            "date": "",
        },
    )
    monkeypatch.setattr(
        extraction,
        "build_task_drafts",
        lambda *a, **k: [
            {
                "title": "持ち物の準備",
                "info_type": "持ち物",
                "content": "",
                "items": "タオル",
                "date": "",
                "event_date": "",
                "needs_deadline_investigation": False,
            }
        ],
    )

    calls = []
    monkeypatch.setattr(
        submission_agent,
        "build_submission_task_drafts",
        lambda *a, **k: calls.append(1) or [],
    )
    monkeypatch.setattr(
        "app.rag.indexing.index_info_id", lambda *a, **k: None, raising=False
    )

    attachments._promote_processing_draft(info_id, "OCRテキスト", None, language="ja")

    # フラグ true のタスクが無ければ締切調査は呼ばれない。
    assert calls == []
