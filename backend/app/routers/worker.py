"""SOT-1322: internal AI-worker endpoint on the heavy backend.

The lightweight upload service calls this endpoint after it has persisted the photo. The worker
downloads the file from storage (GCS) by the attachment's object key and schedules the existing
``process_ocr`` background task, then returns 202 immediately so the upload service is not blocked.

Protected by a shared secret header (``X-Worker-Token`` vs ``WORKER_INVOKE_TOKEN``). The backend is
public (allow-unauthenticated) on Cloud Run, so the token check is the access gate.
"""
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, Union
import base64
import json
import os
import logging

from .. import storage
from ..repository import get_attachment_repo_standalone, SqliteAttachmentRepository
from .attachments import process_ocr

logger = logging.getLogger(__name__)

router = APIRouter(tags=["worker"])


class ProcessOcrRequest(BaseModel):
    att_id: Union[int, str]
    info_id: Optional[Union[int, str]] = None
    language: str = "ja"


@router.post("/internal/process-ocr", status_code=202)
async def internal_process_ocr(
    payload: ProcessOcrRequest,
    background_tasks: BackgroundTasks,
    x_worker_token: Optional[str] = Header(None),
):
    expected = os.getenv("WORKER_INVOKE_TOKEN")
    if expected and x_worker_token != expected:
        raise HTTPException(status_code=403, detail="invalid worker token")

    repo = get_attachment_repo_standalone()
    try:
        att = repo.get(payload.att_id)
        if att is None:
            raise HTTPException(status_code=404, detail="Attachment not found")
        object_key = att.object_key
        mime_type = att.mime_type
        # SOT-1405: 添付に保持した設定済み市町村を自動締切調査のリンク付与に貫通させる。
        municipality = getattr(att, "municipality", None) or ""
    finally:
        # process_ocr opens its own standalone repo; release this read session for SQLite.
        if isinstance(repo, SqliteAttachmentRepository):
            repo.db.close()

    backend = storage.get_storage()
    content = backend.read(object_key)
    ocr_path = backend.local_path_for_ocr(object_key, content)
    cleanup_local = (backend.name == "gcs")

    background_tasks.add_task(
        process_ocr,
        payload.att_id,
        str(ocr_path),
        mime_type,
        cleanup_local,
        payload.info_id,
        payload.language,
        municipality,
    )
    return {"status": "accepted", "att_id": payload.att_id}


def _extract_object_name(envelope: dict) -> Optional[tuple]:
    """Pub/Sub push envelope から (object_name, event_type) を取り出す。

    GCS notification(Pub/Sub) は object 名を message.attributes.objectId に入れる。
    payload(JSON_API_V1) を使う場合は data(base64) に object metadata が入るので、
    attributes が無ければ data をデコードして name を拾う。
    """
    message = envelope.get("message") or {}
    attributes = message.get("attributes") or {}
    object_name = attributes.get("objectId")
    event_type = attributes.get("eventType")
    if not object_name:
        raw = message.get("data")
        if raw:
            try:
                data = json.loads(base64.b64decode(raw).decode("utf-8"))
                object_name = data.get("name")
            except Exception:
                object_name = None
    return (object_name, event_type) if object_name else None


@router.post("/internal/gcs-finalize", status_code=200)
async def internal_gcs_finalize(
    request: Request,
    background_tasks: BackgroundTasks,
    token: Optional[str] = None,
):
    """SOT-1377: GCS OBJECT_FINALIZE の Pub/Sub push を受け取り、OCR を冪等に起動する。

    direct upload では画像本体は backend を経由しないため、GCS への保存完了を
    Pub/Sub push で受けて OCR を起動する。Pub/Sub は同一メッセージを重複配送し得るので、
    Firestore metadata と突合し ocr_status を pending→processing に CAS 遷移できた
    ときだけ OCR を起動する（重複・不正イベントは ack して握りつぶす）。

    Pyb/Sub push は任意ヘッダを付けられないため、worker-token は query (`?token=`) で検証する。
    """
    expected = os.getenv("WORKER_INVOKE_TOKEN")
    if expected and token != expected:
        raise HTTPException(status_code=403, detail="invalid worker token")

    try:
        envelope = await request.json()
    except Exception:
        # 不正な body は ack（再配送させない）。
        return {"status": "ignored", "reason": "invalid body"}

    extracted = _extract_object_name(envelope if isinstance(envelope, dict) else {})
    if not extracted:
        return {"status": "ignored", "reason": "no object name"}
    object_name, event_type = extracted

    # finalize 以外(削除等)は対象外。eventType 不明時は finalize 相当として続行する。
    if event_type and event_type != "OBJECT_FINALIZE":
        return {"status": "ignored", "reason": f"event {event_type}"}

    repo = get_attachment_repo_standalone()
    try:
        att = repo.get_by_object_key(object_name)
        if att is None:
            # 正規 session 以外のオブジェクト（孤児）→ 起動しない。
            return {"status": "ignored", "reason": "no matching attachment"}

        att_id = att.id
        info_id = getattr(att, "info_id", None)
        mime_type = att.mime_type
        language = getattr(att, "language", None) or "ja"
        # SOT-1405: 添付に保持した設定済み市町村を自動締切調査のリンク付与に貫通させる。
        municipality = getattr(att, "municipality", None) or ""

        # CAS: pending の場合のみ processing に遷移し OCR 起動権を得る（重複配送を吸収）。
        if not repo.begin_ocr_if_pending(att_id):
            return {"status": "skipped", "reason": "already processing/done", "att_id": att_id}
    finally:
        if isinstance(repo, SqliteAttachmentRepository):
            repo.db.close()

    storage_backend = storage.get_storage()
    content = storage_backend.read(object_name)
    ocr_path = storage_backend.local_path_for_ocr(object_name, content)
    cleanup_local = (storage_backend.name == "gcs")

    background_tasks.add_task(
        process_ocr,
        att_id,
        str(ocr_path),
        mime_type,
        cleanup_local,
        info_id,
        language,
        municipality,
    )
    return {"status": "accepted", "att_id": att_id}


@router.post("/internal/purge-orphans")
async def internal_purge_orphans(
    x_worker_token: Optional[str] = Header(None),
):
    """SOT-1366: Cloud Scheduler から日次で呼ばれる孤児オブジェクト保全ジョブ。
    DB に対応レコードが無い GCS オブジェクトのみを削除する（表示中写真は保持）。
    /internal/process-ocr と同じ worker-token で保護する。"""
    expected = os.getenv("WORKER_INVOKE_TOKEN")
    if expected and x_worker_token != expected:
        raise HTTPException(status_code=403, detail="invalid worker token")

    from ..retention import reconcile_orphan_attachments

    deleted = reconcile_orphan_attachments()
    return {"deleted": deleted}
