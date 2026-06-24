import abc
import os
import datetime
import logging
from typing import List, Optional, Union, Any
from dataclasses import dataclass, field
from sqlalchemy.orm import Session
from sqlalchemy import or_
from fastapi import Depends

from . import models, schemas, database

logger = logging.getLogger(__name__)

# --- Interfaces ---

class InfoRepository(abc.ABC):
    @abc.abstractmethod
    def create(self, data: schemas.NurseryInfoCreate) -> Any:
        pass

    @abc.abstractmethod
    def get(self, id: Union[int, str]) -> Optional[Any]:
        pass

    @abc.abstractmethod
    def list(self, q: Optional[str] = None, info_type: Optional[str] = None,
             status: Optional[str] = None, priority: Optional[str] = None,
             tag: Optional[str] = None, include_attachments: bool = True) -> List[Any]:
        pass

    @abc.abstractmethod
    def list_today(self) -> List[Any]:
        pass

    @abc.abstractmethod
    def list_tomorrow(self) -> List[Any]:
        pass

    @abc.abstractmethod
    def list_weekly(self) -> List[Any]:
        pass

    @abc.abstractmethod
    def list_pending(self) -> List[Any]:
        pass

    @abc.abstractmethod
    def list_drafts(self) -> List[Any]:
        pass

    @abc.abstractmethod
    def finalize(self, id: Union[int, str]) -> Optional[Any]:
        pass

    @abc.abstractmethod
    def update(self, id: Union[int, str], data: schemas.NurseryInfoUpdate) -> Optional[Any]:
        pass

    @abc.abstractmethod
    def list_attachments_for_info(self, id: Union[int, str]) -> List[Any]:
        pass

    @abc.abstractmethod
    def delete(self, id: Union[int, str]) -> bool:
        pass


class AttachmentRepository(abc.ABC):
    @abc.abstractmethod
    def info_exists(self, info_id: Union[int, str]) -> bool:
        pass

    @abc.abstractmethod
    def create(self, *, info_id: Union[int, str], stored_filename: str, 
               original_filename: str, mime_type: str, file_size: int, 
               storage_backend: str, object_key: Optional[str], 
               ocr_text: Optional[str], ocr_status: str = "pending") -> Any:
        pass

    @abc.abstractmethod
    def get(self, att_id: Union[int, str]) -> Optional[Any]:
        pass

    @abc.abstractmethod
    def set_ocr_result(self, att_id: Union[int, str], *, ocr_text: Optional[str], ocr_status: str) -> None:
        pass

    @abc.abstractmethod
    def delete(self, att_id: Union[int, str]) -> bool:
        pass


# --- SQLite Implementation ---

def _sqlite_registered_only():
    """本登録(registered)のみを対象にする SQLAlchemy フィルタ。
    未設定(旧データ)は registered 扱いで残し、draft だけを除外する。"""
    return or_(
        models.NurseryInfo.registration_state == "registered",
        models.NurseryInfo.registration_state.is_(None),
    )


class SqliteInfoRepository(InfoRepository):
    def __init__(self, db: Session):
        self.db = db

    def create(self, data: schemas.NurseryInfoCreate) -> models.NurseryInfo:
        db_info = models.NurseryInfo(**data.model_dump())
        self.db.add(db_info)
        self.db.commit()
        self.db.refresh(db_info)
        return db_info

    def get(self, id: Union[int, str]) -> Optional[models.NurseryInfo]:
        return self.db.query(models.NurseryInfo).filter(models.NurseryInfo.id == int(id)).first()

    def list(self, q: Optional[str] = None, info_type: Optional[str] = None,
             status: Optional[str] = None, priority: Optional[str] = None,
             tag: Optional[str] = None, include_attachments: bool = True) -> List[models.NurseryInfo]:
        query = self.db.query(models.NurseryInfo).filter(_sqlite_registered_only())

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

        results = query.all()
        if not include_attachments:
            # タイトルのみのデータ一覧（SOT-1240）向け: 添付の lazy-load (N+1) を発生させない
            for info in results:
                info.attachments = []
        return results

    def list_today(self) -> List[models.NurseryInfo]:
        # 今日やること: 本日が日付/行事日/提出期限のいずれかに該当する情報 (SOT-1093)
        today = datetime.date.today()
        return self.db.query(models.NurseryInfo).filter(
            _sqlite_registered_only(),
            or_(
                models.NurseryInfo.date == today,
                models.NurseryInfo.event_date == today,
                models.NurseryInfo.due_date == today,
            )
        ).all()

    def list_tomorrow(self) -> List[models.NurseryInfo]:
        tomorrow = datetime.date.today() + datetime.timedelta(days=1)
        return self.db.query(models.NurseryInfo).filter(
            _sqlite_registered_only(),
            or_(
                models.NurseryInfo.event_date == tomorrow,
                (models.NurseryInfo.info_type == "持ち物") & (models.NurseryInfo.date == tomorrow)
            )
        ).all()

    def list_weekly(self) -> List[models.NurseryInfo]:
        today = datetime.date.today()
        next_week = today + datetime.timedelta(days=7)
        return self.db.query(models.NurseryInfo).filter(
            _sqlite_registered_only(),
            models.NurseryInfo.info_type == "行事",
            models.NurseryInfo.event_date >= today,
            models.NurseryInfo.event_date <= next_week
        ).all()

    def list_pending(self) -> List[models.NurseryInfo]:
        # 未対応のタスク: 提出物に限らず全カテゴリ横断で status=="未対応" (SOT-1093)
        return self.db.query(models.NurseryInfo).filter(
            _sqlite_registered_only(),
            models.NurseryInfo.status == "未対応"
        ).all()

    def list_drafts(self) -> List[models.NurseryInfo]:
        # 仮登録(draft)のみ。新しい順で返す。
        return self.db.query(models.NurseryInfo).filter(
            models.NurseryInfo.registration_state == "draft"
        ).order_by(models.NurseryInfo.created_at.desc()).all()

    def finalize(self, id: Union[int, str]) -> Optional[models.NurseryInfo]:
        db_info = self.get(id)
        if not db_info:
            return None
        db_info.registration_state = "registered"
        self.db.commit()
        self.db.refresh(db_info)
        return db_info

    def update(self, id: Union[int, str], data: schemas.NurseryInfoUpdate) -> Optional[models.NurseryInfo]:
        db_info = self.get(id)
        if not db_info:
            return None
        
        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(db_info, key, value)
        
        self.db.commit()
        self.db.refresh(db_info)
        return db_info

    def list_attachments_for_info(self, id: Union[int, str]) -> List[models.Attachment]:
        db_info = self.get(id)
        if not db_info:
            return []
        return db_info.attachments

    def delete(self, id: Union[int, str]) -> bool:
        db_info = self.get(id)
        if not db_info:
            return False
        
        self.db.delete(db_info)
        self.db.commit()
        return True


class SqliteAttachmentRepository(AttachmentRepository):
    def __init__(self, db: Session):
        self.db = db

    def info_exists(self, info_id: Union[int, str]) -> bool:
        return self.db.query(models.NurseryInfo).filter(models.NurseryInfo.id == int(info_id)).first() is not None

    def create(self, *, info_id: Union[int, str], stored_filename: str, 
               original_filename: str, mime_type: str, file_size: int, 
               storage_backend: str, object_key: Optional[str], 
               ocr_text: Optional[str], ocr_status: str = "pending") -> models.Attachment:
        db_attachment = models.Attachment(
            info_id=int(info_id),
            stored_filename=stored_filename,
            original_filename=original_filename,
            mime_type=mime_type,
            file_size=file_size,
            storage_backend=storage_backend,
            object_key=object_key,
            ocr_text=ocr_text,
            ocr_status=ocr_status
        )
        self.db.add(db_attachment)
        self.db.commit()
        self.db.refresh(db_attachment)
        return db_attachment

    def get(self, att_id: Union[int, str]) -> Optional[models.Attachment]:
        return self.db.query(models.Attachment).filter(models.Attachment.id == int(att_id)).first()

    def set_ocr_result(self, att_id: Union[int, str], *, ocr_text: Optional[str], ocr_status: str) -> None:
        db_attachment = self.get(att_id)
        if db_attachment:
            db_attachment.ocr_text = ocr_text
            db_attachment.ocr_status = ocr_status
            self.db.commit()

    def delete(self, att_id: Union[int, str]) -> bool:
        db_attachment = self.get(att_id)
        if not db_attachment:
            return False
        
        self.db.delete(db_attachment)
        self.db.commit()
        return True


# --- Firestore Implementation ---

@dataclass
class FirestoreAttachment:
    id: str
    info_id: str
    stored_filename: str
    original_filename: str
    mime_type: str
    file_size: int
    storage_backend: str
    object_key: Optional[str]
    ocr_text: Optional[str]
    ocr_status: str
    created_at: datetime.datetime

@dataclass
class FirestoreNurseryInfo:
    id: str
    title: str
    info_type: str
    content: str
    date: Optional[datetime.date]
    event_date: Optional[datetime.date]
    due_date: Optional[datetime.date]
    items: Optional[str]
    status: str
    priority: str
    tags: Optional[str]
    memo: Optional[str]
    created_at: datetime.datetime
    updated_at: datetime.datetime
    registration_state: str = "registered"
    attachments: List[FirestoreAttachment] = field(default_factory=list)

# Firestore helper functions

def _tags_str_to_array(tags_str: Optional[str]) -> List[str]:
    if not tags_str:
        return []
    return [t.strip() for t in tags_str.split(",") if t.strip()]

def _tags_array_to_str(tags_array: Optional[List[str]]) -> Optional[str]:
    if not tags_array:
        return None
    return ",".join(tags_array)

def _to_date(val: Optional[str]) -> Optional[datetime.date]:
    if not val:
        return None
    try:
        return datetime.date.fromisoformat(val)
    except ValueError:
        return None

def _from_date(val: Optional[datetime.date]) -> Optional[str]:
    if not val:
        return None
    return val.isoformat()

def _info_doc_to_obj(doc_id: str, data: dict, attachments: List[FirestoreAttachment] = None) -> FirestoreNurseryInfo:
    return FirestoreNurseryInfo(
        id=doc_id,
        title=data.get("title", ""),
        info_type=data.get("info_type", ""),
        content=data.get("content", ""),
        date=_to_date(data.get("date")),
        event_date=_to_date(data.get("event_date")),
        due_date=_to_date(data.get("due_date")),
        items=data.get("items"),
        status=data.get("status", "未対応"),
        priority=data.get("priority", "普通"),
        tags=_tags_array_to_str(data.get("tags")),
        memo=data.get("memo"),
        registration_state=data.get("registration_state") or "registered",
        created_at=data.get("created_at") or datetime.datetime.now(),
        updated_at=data.get("updated_at") or datetime.datetime.now(),
        attachments=attachments or []
    )

def _att_doc_to_obj(doc_id: str, data: dict) -> FirestoreAttachment:
    return FirestoreAttachment(
        id=doc_id,
        info_id=data.get("info_id", ""),
        stored_filename=data.get("stored_filename", ""),
        original_filename=data.get("original_filename", ""),
        mime_type=data.get("mime_type", ""),
        file_size=data.get("file_size", 0),
        storage_backend=data.get("storage_backend", "local"),
        object_key=data.get("object_key"),
        ocr_text=data.get("ocr_text"),
        ocr_status=data.get("ocr_status", "pending"),
        created_at=data.get("created_at") or datetime.datetime.now()
    )

def _is_registered_data(data: dict) -> bool:
    """Firestore ドキュメントが本登録(registered)かどうか。
    未設定(旧データ)は registered 扱い。draft のみ False。"""
    return (data.get("registration_state") or "registered") == "registered"


def _matches_query(info: FirestoreNurseryInfo, q: Optional[str], tag: Optional[str]) -> bool:
    if tag:
        info_tags = _tags_str_to_array(info.tags)
        if tag not in info_tags:
            return False
            
    if q:
        q = q.lower()
        # Title, Content, Tags
        if q in info.title.lower() or q in info.content.lower():
            return True
        if info.tags and q in info.tags.lower():
            return True
        # OCR text in attachments
        for att in info.attachments:
            if att.ocr_text and q in att.ocr_text.lower():
                return True
        return False
        
    return True

class FirestoreInfoRepository(InfoRepository):
    def __init__(self):
        self.project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        self.database_id = os.getenv("FIRESTORE_DATABASE", "(default)")
        self._db = None

    @property
    def db(self):
        if self._db is None:
            from google.cloud import firestore
            self._db = firestore.Client(project=self.project_id, database=self.database_id)
        return self._db

    def create(self, data: schemas.NurseryInfoCreate) -> FirestoreNurseryInfo:
        now = datetime.datetime.now(datetime.timezone.utc)
        doc_data = data.model_dump()
        # Convert dates and tags
        doc_data["date"] = _from_date(doc_data.get("date"))
        doc_data["event_date"] = _from_date(doc_data.get("event_date"))
        doc_data["due_date"] = _from_date(doc_data.get("due_date"))
        doc_data["tags"] = _tags_str_to_array(doc_data.get("tags"))
        doc_data["created_at"] = now
        doc_data["updated_at"] = now
        
        _, doc_ref = self.db.collection("nursery_info").add(doc_data)
        return _info_doc_to_obj(doc_ref.id, doc_data)

    def get(self, id: Union[int, str]) -> Optional[FirestoreNurseryInfo]:
        doc_ref = self.db.collection("nursery_info").document(str(id))
        doc = doc_ref.get()
        if not doc.exists:
            return None
        
        # Get attachments
        att_refs = self.db.collection("attachments").where("info_id", "==", str(id)).stream()
        attachments = [_att_doc_to_obj(att.id, att.to_dict()) for att in att_refs]
        
        return _info_doc_to_obj(doc.id, doc.to_dict(), attachments)

    def list(self, q: Optional[str] = None, info_type: Optional[str] = None,
             status: Optional[str] = None, priority: Optional[str] = None,
             tag: Optional[str] = None, include_attachments: bool = True) -> List[FirestoreNurseryInfo]:
        query = self.db.collection("nursery_info")
        
        if info_type:
            query = query.where("info_type", "==", info_type)
        if status:
            query = query.where("status", "==", status)
        if priority:
            query = query.where("priority", "==", priority)
        # Firestore tag search: if we want to use array-contains, we can do it for single tag
        if tag and not q: # If only tag is provided, use array-contains
            query = query.where("tags", "array_contains", tag)
            
        docs = query.stream()
        results = []
        for doc in docs:
            doc_data = doc.to_dict()
            # 仮登録(draft)は通常一覧に含めない (SOT-1113)
            if not _is_registered_data(doc_data):
                continue
            # Fetch attachments if q is present (needed for OCR search)
            attachments = []
            if q:
                att_refs = self.db.collection("attachments").where("info_id", "==", doc.id).stream()
                attachments = [_att_doc_to_obj(att.id, att.to_dict()) for att in att_refs]
            
            info_obj = _info_doc_to_obj(doc.id, doc_data, attachments)
            
            if _matches_query(info_obj, q, tag if q else None):
                # If q was NOT present, we still need to fetch attachments for the response model,
                # unless the caller opted out (SOT-1240: title-only data list skips the per-item
                # attachment query to avoid N+1 latency).
                if not q and include_attachments:
                    att_refs = self.db.collection("attachments").where("info_id", "==", doc.id).stream()
                    info_obj.attachments = [_att_doc_to_obj(att.id, att.to_dict()) for att in att_refs]
                results.append(info_obj)
                
        return results

    def list_today(self) -> List[FirestoreNurseryInfo]:
        # 今日やること: 本日が date/event_date/due_date のいずれかに該当 (SOT-1093)
        today_str = _from_date(datetime.date.today())

        results_dict = {}
        for field_name in ("date", "event_date", "due_date"):
            for doc in self.db.collection("nursery_info").where(field_name, "==", today_str).stream():
                results_dict[doc.id] = doc.to_dict()

        results = []
        for doc_id, data in results_dict.items():
            if not _is_registered_data(data):  # 仮登録は除外 (SOT-1113)
                continue
            att_refs = self.db.collection("attachments").where("info_id", "==", doc_id).stream()
            attachments = [_att_doc_to_obj(att.id, att.to_dict()) for att in att_refs]
            results.append(_info_doc_to_obj(doc_id, data, attachments))
        return results

    def list_tomorrow(self) -> List[FirestoreNurseryInfo]:
        tomorrow_date = datetime.date.today() + datetime.timedelta(days=1)
        tomorrow_str = _from_date(tomorrow_date)
        
        # event_date == tomorrow
        q1 = self.db.collection("nursery_info").where("event_date", "==", tomorrow_str).stream()
        # info_type == "持ち物" AND date == tomorrow
        q2 = self.db.collection("nursery_info").where("info_type", "==", "持ち物").where("date", "==", tomorrow_str).stream()
        
        results_dict = {}
        for doc in q1:
            results_dict[doc.id] = doc.to_dict()
        for doc in q2:
            results_dict[doc.id] = doc.to_dict()
            
        results = []
        for doc_id, data in results_dict.items():
            if not _is_registered_data(data):  # 仮登録は除外 (SOT-1113)
                continue
            att_refs = self.db.collection("attachments").where("info_id", "==", doc_id).stream()
            attachments = [_att_doc_to_obj(att.id, att.to_dict()) for att in att_refs]
            results.append(_info_doc_to_obj(doc_id, data, attachments))

        return results

    def list_weekly(self) -> List[FirestoreNurseryInfo]:
        today = datetime.date.today()
        today_str = _from_date(today)
        next_week_str = _from_date(today + datetime.timedelta(days=7))
        
        docs = self.db.collection("nursery_info") \
            .where("info_type", "==", "行事") \
            .where("event_date", ">=", today_str) \
            .where("event_date", "<=", next_week_str) \
            .stream()
            
        results = []
        for doc in docs:
            if not _is_registered_data(doc.to_dict()):  # 仮登録は除外 (SOT-1113)
                continue
            att_refs = self.db.collection("attachments").where("info_id", "==", doc.id).stream()
            attachments = [_att_doc_to_obj(att.id, att.to_dict()) for att in att_refs]
            results.append(_info_doc_to_obj(doc.id, doc.to_dict(), attachments))
        return results

    def list_pending(self) -> List[FirestoreNurseryInfo]:
        # 未対応のタスク: 全カテゴリ横断で status=="未対応" (SOT-1093)
        docs = self.db.collection("nursery_info") \
            .where("status", "==", "未対応") \
            .stream()

        results = []
        for doc in docs:
            if not _is_registered_data(doc.to_dict()):  # 仮登録は除外 (SOT-1113)
                continue
            att_refs = self.db.collection("attachments").where("info_id", "==", doc.id).stream()
            attachments = [_att_doc_to_obj(att.id, att.to_dict()) for att in att_refs]
            results.append(_info_doc_to_obj(doc.id, doc.to_dict(), attachments))
        return results

    def list_drafts(self) -> List[FirestoreNurseryInfo]:
        # 仮登録(draft)のみ返す (SOT-1113)。
        docs = self.db.collection("nursery_info").stream()
        results = []
        for doc in docs:
            doc_data = doc.to_dict()
            if (doc_data.get("registration_state") or "registered") != "draft":
                continue
            att_refs = self.db.collection("attachments").where("info_id", "==", doc.id).stream()
            attachments = [_att_doc_to_obj(att.id, att.to_dict()) for att in att_refs]
            results.append(_info_doc_to_obj(doc.id, doc_data, attachments))
        results.sort(key=lambda i: i.created_at, reverse=True)
        return results

    def finalize(self, id: Union[int, str]) -> Optional[FirestoreNurseryInfo]:
        doc_ref = self.db.collection("nursery_info").document(str(id))
        if not doc_ref.get().exists:
            return None
        doc_ref.update({
            "registration_state": "registered",
            "updated_at": datetime.datetime.now(datetime.timezone.utc),
        })
        return self.get(id)

    def update(self, id: Union[int, str], data: schemas.NurseryInfoUpdate) -> Optional[FirestoreNurseryInfo]:
        doc_ref = self.db.collection("nursery_info").document(str(id))
        doc = doc_ref.get()
        if not doc.exists:
            return None
            
        update_data = data.model_dump(exclude_unset=True)
        # Convert dates and tags
        if "date" in update_data:
            update_data["date"] = _from_date(update_data["date"])
        if "event_date" in update_data:
            update_data["event_date"] = _from_date(update_data["event_date"])
        if "due_date" in update_data:
            update_data["due_date"] = _from_date(update_data["due_date"])
        if "tags" in update_data:
            update_data["tags"] = _tags_str_to_array(update_data["tags"])
        
        update_data["updated_at"] = datetime.datetime.now(datetime.timezone.utc)
        
        doc_ref.update(update_data)
        return self.get(id)

    def list_attachments_for_info(self, id: Union[int, str]) -> List[FirestoreAttachment]:
        att_refs = self.db.collection("attachments").where("info_id", "==", str(id)).stream()
        return [_att_doc_to_obj(att.id, att.to_dict()) for att in att_refs]

    def delete(self, id: Union[int, str]) -> bool:
        doc_ref = self.db.collection("nursery_info").document(str(id))
        if not doc_ref.get().exists:
            return False
            
        # Delete attachments first
        att_refs = self.db.collection("attachments").where("info_id", "==", str(id)).stream()
        for att in att_refs:
            self.db.collection("attachments").document(att.id).delete()
            
        doc_ref.delete()
        return True


class FirestoreAttachmentRepository(AttachmentRepository):
    def __init__(self):
        self.project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        self.database_id = os.getenv("FIRESTORE_DATABASE", "(default)")
        self._db = None

    @property
    def db(self):
        if self._db is None:
            from google.cloud import firestore
            self._db = firestore.Client(project=self.project_id, database=self.database_id)
        return self._db

    def info_exists(self, info_id: Union[int, str]) -> bool:
        return self.db.collection("nursery_info").document(str(info_id)).get().exists

    def create(self, *, info_id: Union[int, str], stored_filename: str, 
               original_filename: str, mime_type: str, file_size: int, 
               storage_backend: str, object_key: Optional[str], 
               ocr_text: Optional[str], ocr_status: str = "pending") -> FirestoreAttachment:
        now = datetime.datetime.now(datetime.timezone.utc)
        doc_data = {
            "info_id": str(info_id),
            "stored_filename": stored_filename,
            "original_filename": original_filename,
            "mime_type": mime_type,
            "file_size": file_size,
            "storage_backend": storage_backend,
            "object_key": object_key,
            "ocr_text": ocr_text,
            "ocr_status": ocr_status,
            "created_at": now
        }
        _, doc_ref = self.db.collection("attachments").add(doc_data)
        return _att_doc_to_obj(doc_ref.id, doc_data)

    def get(self, att_id: Union[int, str]) -> Optional[FirestoreAttachment]:
        doc_ref = self.db.collection("attachments").document(str(att_id))
        doc = doc_ref.get()
        if not doc.exists:
            return None
        return _att_doc_to_obj(doc.id, doc.to_dict())

    def set_ocr_result(self, att_id: Union[int, str], *, ocr_text: Optional[str], ocr_status: str) -> None:
        doc_ref = self.db.collection("attachments").document(str(att_id))
        if doc_ref.get().exists:
            doc_ref.update({
                "ocr_text": ocr_text,
                "ocr_status": ocr_status
            })

    def delete(self, att_id: Union[int, str]) -> bool:
        doc_ref = self.db.collection("attachments").document(str(att_id))
        if not doc_ref.get().exists:
            return False
        doc_ref.delete()
        return True


# --- Factory functions ---

def get_database_type() -> str:
    return os.getenv("DATABASE_TYPE", "sqlite").lower()

def get_info_repository(db: Session = Depends(database.get_db)) -> InfoRepository:
    if get_database_type() == "firestore":
        return FirestoreInfoRepository()
    return SqliteInfoRepository(db)

def get_attachment_repository(db: Session = Depends(database.get_db)) -> AttachmentRepository:
    if get_database_type() == "firestore":
        return FirestoreAttachmentRepository()
    return SqliteAttachmentRepository(db)

def get_attachment_repo_standalone() -> Any:
    """Helper for background tasks where Depends() cannot be used."""
    if get_database_type() == "firestore":
        return FirestoreAttachmentRepository()
    
    # For SQLite, we need a session
    db = database.SessionLocal()
    return SqliteAttachmentRepository(db)
