from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
import os
from .. import models, schemas, storage
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
    storage.ensure_upload_dir()
    stored_filename = storage.generate_stored_filename(file.filename)
    file_path = storage.get_file_path(stored_filename)
    
    with open(file_path, "wb") as f:
        f.write(content)

    # Create Attachment row
    db_attachment = models.Attachment(
        info_id=info_id,
        stored_filename=stored_filename,
        original_filename=file.filename,
        mime_type=content_type,
        file_size=file_size
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

    file_path = storage.get_file_path(db_attachment.stored_filename)
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
    storage.delete_file(db_attachment.stored_filename)

    # Delete DB row
    db.delete(db_attachment)
    db.commit()

    return {"message": "Successfully deleted"}
