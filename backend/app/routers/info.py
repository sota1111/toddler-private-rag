from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import List, Optional
from datetime import date, timedelta
from .. import models, schemas, storage
from ..database import get_db
from ..routers.auth import get_current_user

router = APIRouter(
    prefix="/info",
    tags=["info"],
)

@router.post("/", response_model=schemas.NurseryInfoResponse)
def create_info(info: schemas.NurseryInfoCreate, db: Session = Depends(get_db), current_user: str = Depends(get_current_user)):
    db_info = models.NurseryInfo(**info.model_dump())
    db.add(db_info)
    db.commit()
    db.refresh(db_info)
    return db_info

@router.get("/tomorrow", response_model=List[schemas.NurseryInfoResponse])
def get_tomorrow_info(db: Session = Depends(get_db), current_user: str = Depends(get_current_user)):
    tomorrow = date.today() + timedelta(days=1)
    return db.query(models.NurseryInfo).filter(
        or_(
            models.NurseryInfo.event_date == tomorrow,
            (models.NurseryInfo.info_type == "持ち物") & (models.NurseryInfo.date == tomorrow)
        )
    ).all()

@router.get("/weekly", response_model=List[schemas.NurseryInfoResponse])
def get_weekly_info(db: Session = Depends(get_db), current_user: str = Depends(get_current_user)):
    today = date.today()
    next_week = today + timedelta(days=7)
    return db.query(models.NurseryInfo).filter(
        models.NurseryInfo.info_type == "行事",
        models.NurseryInfo.event_date >= today,
        models.NurseryInfo.event_date <= next_week
    ).all()

@router.get("/pending", response_model=List[schemas.NurseryInfoResponse])
def get_pending_info(db: Session = Depends(get_db), current_user: str = Depends(get_current_user)):
    return db.query(models.NurseryInfo).filter(
        models.NurseryInfo.info_type == "提出物",
        models.NurseryInfo.status == "未対応"
    ).all()

@router.get("/", response_model=List[schemas.NurseryInfoResponse])
def list_info(
    q: Optional[str] = None,
    info_type: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    tag: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user)
):
    query = db.query(models.NurseryInfo)
    
    if q:
        search = f"%{q}%"
        query = query.filter(
            or_(
                models.NurseryInfo.title.ilike(search),
                models.NurseryInfo.content.ilike(search),
                models.NurseryInfo.tags.ilike(search),
                models.NurseryInfo.attachments.any(models.Attachment.ocr_text.ilike(search))
            )
        )
    
    if info_type:
        query = query.filter(models.NurseryInfo.info_type == info_type)
    
    if status:
        query = query.filter(models.NurseryInfo.status == status)
        
    if priority:
        query = query.filter(models.NurseryInfo.priority == priority)
        
    if tag:
        query = query.filter(models.NurseryInfo.tags.ilike(f"%{tag}%"))
        
    return query.all()

@router.get("/{id}", response_model=schemas.NurseryInfoResponse)
def get_info(id: int, db: Session = Depends(get_db), current_user: str = Depends(get_current_user)):
    db_info = db.query(models.NurseryInfo).filter(models.NurseryInfo.id == id).first()
    if db_info is None:
        raise HTTPException(status_code=404, detail="Info not found")
    return db_info

@router.put("/{id}", response_model=schemas.NurseryInfoResponse)
def update_info(id: int, info: schemas.NurseryInfoUpdate, db: Session = Depends(get_db), current_user: str = Depends(get_current_user)):
    db_info = db.query(models.NurseryInfo).filter(models.NurseryInfo.id == id).first()
    if db_info is None:
        raise HTTPException(status_code=404, detail="Info not found")
    
    update_data = info.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_info, key, value)
    
    db.commit()
    db.refresh(db_info)
    return db_info

@router.delete("/{id}")
def delete_info(id: int, db: Session = Depends(get_db), current_user: str = Depends(get_current_user)):
    db_info = db.query(models.NurseryInfo).filter(models.NurseryInfo.id == id).first()
    if db_info is None:
        raise HTTPException(status_code=404, detail="Info not found")
    
    # Delete physical files
    backend = storage.get_storage()
    for attachment in db_info.attachments:
        backend.delete(attachment.object_key or attachment.stored_filename)

    db.delete(db_info)
    db.commit()
    return {"message": "Successfully deleted"}
