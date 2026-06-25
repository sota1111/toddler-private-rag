from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.responses import FileResponse, RedirectResponse
import os
import logging
from .. import schemas, storage, ocr
from ..privacy import redact_pii
from ..repository import AttachmentRepository, get_attachment_repository, get_attachment_repo_standalone, SqliteAttachmentRepository
from ..routers.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["attachments"],
)

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
ALLOWED_CONTENT_TYPES = ["image/*", "application/pdf"]

async def process_ocr(
    att_id: int, 
    ocr_path: str, 
    content_type: str, 
    cleanup_local: bool = False
):
    repo = get_attachment_repo_standalone()
    try:
        ocr_text = ocr.extract_text(ocr_path, content_type)
        # 構造化抽出を生成（将来的に detected_dates 等を活用可能にするため）
        structured = ocr.build_extraction(ocr_text)
        
        # PIIをマスクしてから保存
        safe_text = redact_pii(structured.raw_text)
        repo.set_ocr_result(att_id, ocr_text=safe_text, ocr_status="done")
    except Exception as e:
        logger.error(f"OCR failed for attachment {att_id}: {str(e)}")
        repo.set_ocr_result(att_id, ocr_text=None, ocr_status="failed")
    finally:
        if cleanup_local and os.path.exists(ocr_path):
            os.remove(ocr_path)
        
        # Close session if SQLite
        if isinstance(repo, SqliteAttachmentRepository):
            repo.db.close()

@router.post("/info/{info_id}/attachments", response_model=schemas.AttachmentResponse)
async def upload_attachment(
    info_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    repo: AttachmentRepository = Depends(get_attachment_repository),
    current_user: str = Depends(get_current_user)
):
    # Verify NurseryInfo exists
    if not repo.info_exists(info_id):
        raise HTTPException(status_code=404, detail="NurseryInfo not found")

    # Validate content type
    content_type = file.content_type or ""
    if content_type != "application/pdf" and not content_type.startswith("image/"):
        raise HTTPException(
            status_code=400, 
            detail=f"Unsupported file type. Allowed types: {', '.join(ALLOWED_CONTENT_TYPES)}"
        )

    # Read file and check size
    content = await file.read()
    file_size = len(content)
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413, 
            detail=f"File too large. Maximum size is {MAX_FILE_SIZE / (1024*1024)}MB"
        )

    # Save to storage
    backend = storage.get_storage()
    stored_filename = storage.generate_stored_filename(file.filename)
    object_key = storage.build_object_key(stored_filename)
    
    backend.save(object_key, content, content_type)

    # Create Attachment row FIRST (pending)
    db_attachment = repo.create(
        info_id=info_id,
        stored_filename=stored_filename,
        original_filename=file.filename,
        mime_type=content_type,
        file_size=file_size,
        storage_backend=backend.name,
        object_key=object_key,
        ocr_text=None,
        ocr_status="pending"
    )

    # Prepare OCR (but don't run it yet)
    ocr_path = backend.local_path_for_ocr(object_key, content)
    
    # Schedule OCR as background task
    # If backend is GCS, ocr_path is a temp file that should be cleaned up
    cleanup_local = (backend.name == "gcs")
    background_tasks.add_task(
        process_ocr, 
        db_attachment.id, 
        str(ocr_path), 
        content_type, 
        cleanup_local
    )

    return db_attachment

@router.get("/attachments/{att_id}/file")
def get_attachment_file(
    att_id: int,
    repo: AttachmentRepository = Depends(get_attachment_repository),
    current_user: str = Depends(get_current_user)
):
    db_attachment = repo.get(att_id)
    if not db_attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")

    if db_attachment.storage_backend == "gcs":
        backend = storage.get_storage()
        # Ensure we are using GCSStorage
        if isinstance(backend, storage.GCSStorage):
            url = backend.generate_signed_url(db_attachment.object_key, db_attachment.mime_type)
            return RedirectResponse(url=url)
        else:
            # Fallback if config is inconsistent, though unlikely
            raise HTTPException(status_code=500, detail="Storage configuration mismatch")

    # Local storage (default)
    file_path = storage.get_file_path(db_attachment.stored_filename or db_attachment.object_key)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found on disk")

    # SOT-1275: serve inline so clicking an image opens it in the browser instead of
    # forcing a download (passing filename= alone sets Content-Disposition: attachment,
    # which makes window.open(..., '_blank') show a blank tab).
    return FileResponse(
        path=file_path,
        media_type=db_attachment.mime_type,
        filename=db_attachment.original_filename,
        content_disposition_type="inline",
    )

@router.delete("/attachments/{att_id}")
def delete_attachment(
    att_id: int,
    repo: AttachmentRepository = Depends(get_attachment_repository),
    current_user: str = Depends(get_current_user)
):
    db_attachment = repo.get(att_id)
    if not db_attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")

    # Delete physical file
    backend = storage.get_storage()
    backend.delete(db_attachment.object_key or db_attachment.stored_filename)

    # Delete DB row
    repo.delete(att_id)

    return {"message": "Successfully deleted"}
