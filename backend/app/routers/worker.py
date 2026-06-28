"""SOT-1322: internal AI-worker endpoint on the heavy backend.

The lightweight upload service calls this endpoint after it has persisted the photo. The worker
downloads the file from storage (GCS) by the attachment's object key and schedules the existing
``process_ocr`` background task, then returns 202 immediately so the upload service is not blocked.

Protected by a shared secret header (``X-Worker-Token`` vs ``WORKER_INVOKE_TOKEN``). The backend is
public (allow-unauthenticated) on Cloud Run, so the token check is the access gate.
"""
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from pydantic import BaseModel
from typing import Optional, Union
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
    )
    return {"status": "accepted", "att_id": payload.att_id}
