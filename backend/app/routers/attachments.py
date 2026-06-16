from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session
import os
from .. import models, schemas, storage, ocr
from ..database import get_db
from ..routers.auth import get_current_user

router = APIRouter(
    tags=["attachments"],
)

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
ALLOWED_CONTENT_TYPES = ["image/*", "application/pdf"]

@router.post("/info/{info_id}/attachments", response_model=schemas.AttachmentResponse)
async def upload_attachment(
    info_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user)
):
    # Verify NurseryInfo exists
    db_info = db.query(models.NurseryInfo).filter(models.NurseryInfo.id == info_id).first()
    if not db_info:
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

    # Extract OCR text
    ocr_path = backend.local_path_for_ocr(object_key, content)
    try:
        ocr_text = ocr.extract_text(ocr_path, content_type)
    finally:
        # If GCS, local_path_for_ocr creates a temp file that should be deleted
        if backend.name == "gcs" and ocr_path.exists():
            os.remove(ocr_path)

    # Create Attachment row
    db_attachment = models.Attachment(
        info_id=info_id,
        stored_filename=stored_filename,
        object_key=object_key,
        storage_backend=backend.name,
        original_filename=file.filename,
        mime_type=content_type,
        file_size=file_size,
        ocr_text=ocr_text
    )
    db.add(db_attachment)
    db.commit()
    db.refresh(db_attachment)

    return db_attachment

@router.get("/attachments/{att_id}/file")
def get_attachment_file(
    att_id: int,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user)
):
    db_attachment = db.query(models.Attachment).filter(models.Attachment.id == att_id).first()
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

    return FileResponse(
        path=file_path,
        media_type=db_attachment.mime_type,
        filename=db_attachment.original_filename
    )

@router.delete("/attachments/{att_id}")
def delete_attachment(
    att_id: int,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user)
):
    db_attachment = db.query(models.Attachment).filter(models.Attachment.id == att_id).first()
    if not db_attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")

    # Delete physical file
    backend = storage.get_storage()
    backend.delete(db_attachment.object_key or db_attachment.stored_filename)

    # Delete DB row
    db.delete(db_attachment)
    db.commit()

    return {"message": "Successfully deleted"}
