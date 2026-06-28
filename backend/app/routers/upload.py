"""SOT-1322: slim upload-only router for the lightweight upload Cloud Run service.

This router mirrors the public upload contract of ``attachments.upload_attachment`` but instead of
running OCR in-process it dispatches the work to the AI worker (the heavy backend). It deliberately
imports ONLY light modules (storage / repository / auth / worker_client) and must NOT import any
AI/OCR module (ocr, extraction, submission_agent, tagging, reminders, rag.*), so the upload image
stays small and boots fast.
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from typing import Union
import logging

from .. import schemas, storage, worker_client
from ..repository import AttachmentRepository, get_attachment_repository
from ..routers.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["upload"])

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


@router.post("/info/{info_id}/attachments", response_model=schemas.AttachmentResponse)
async def upload_attachment_light(
    info_id: Union[int, str],
    file: UploadFile = File(...),
    language: str = "ja",
    repo: AttachmentRepository = Depends(get_attachment_repository),
    current_user: str = Depends(get_current_user),
):
    # Verify NurseryInfo exists
    if not repo.info_exists(info_id):
        raise HTTPException(status_code=404, detail="NurseryInfo not found")

    # Validate content type
    content_type = file.content_type or ""
    if content_type != "application/pdf" and not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Unsupported file type")

    # Read file and check size
    content = await file.read()
    file_size = len(content)
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {MAX_FILE_SIZE / (1024*1024)}MB",
        )

    # Save to storage
    backend = storage.get_storage()
    stored_filename = storage.generate_stored_filename(file.filename)
    object_key = storage.build_object_key(stored_filename)
    backend.save(object_key, content, content_type)

    # Create the pending Attachment row
    db_attachment = repo.create(
        info_id=info_id,
        stored_filename=stored_filename,
        original_filename=file.filename,
        mime_type=content_type,
        file_size=file_size,
        storage_backend=backend.name,
        object_key=object_key,
        ocr_text=None,
        ocr_status="pending",
    )

    # Trigger the AI worker (heavy backend) to do OCR/enrich. Best-effort: never blocks the response.
    worker_client.dispatch_ocr(db_attachment.id, info_id, language)

    return db_attachment
