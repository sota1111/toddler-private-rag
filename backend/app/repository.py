import abc
import os
import datetime
import logging
from typing import List, Optional, Tuple, Union, Any
from dataclasses import dataclass, field
from sqlalchemy.orm import Session
from sqlalchemy import or_
from fastapi import Depends

from . import models, schemas, database, clock
from .identity import DEFAULT_OWNER_ID

logger = logging.getLogger(__name__)


# --- SOT-1431: マルチテナント owner 絞り込みヘルパー ---

def _normalize_owner(owner_id) -> Optional[str]:
    """コンストラクタに渡された owner_id を正規化する。

    FastAPI の未解決 Depends センチネルや非文字列が渡ってきた場合は None (=無絞り/system) に倒す。
    これにより、テストや背景タスクがリポジトリを直接構築しても後方互換で全件が見える。
    """
    return owner_id if isinstance(owner_id, str) else None


def _sqlite_owner_filter(model, owner_id: str):
    """owner_id 所有行にマッチする SQLAlchemy 条件。NULL は既定 owner(主ユーザー)扱い。"""
    if owner_id == DEFAULT_OWNER_ID:
        return or_(model.owner_id == owner_id, model.owner_id.is_(None))
    return model.owner_id == owner_id


def _owner_of(data: dict) -> str:
    """Firestore ドキュメントの実効 owner。未設定(NULL)は既定 owner 扱い。"""
    return data.get("owner_id") or DEFAULT_OWNER_ID


def _calendar_week_bounds(today: datetime.date) -> Tuple[datetime.date, datetime.date, datetime.date]:
    """カレンダー週（月曜始まり）の境界を返す (SOT-1424)。

    掲示板の「今週/来週の予定」を本日起点のローリング窓ではなくカレンダー週で集計するための共通ヘルパ。
    ローリング窓だと、カレンダー上「来週」の予定でも本日から7日以内なら「今週」枠に入り、
    「来週」枠が空白になる不具合があった。

    返り値:
    - this_week_end : 本日が属する週の日曜（今週末）
    - next_week_start: 翌週の月曜
    - next_week_end  : 翌週の日曜
    ``weekday()`` は 月=0 .. 日=6。
    """
    this_week_end = today + datetime.timedelta(days=(6 - today.weekday()))
    next_week_start = this_week_end + datetime.timedelta(days=1)
    next_week_end = next_week_start + datetime.timedelta(days=6)
    return this_week_end, next_week_start, next_week_end


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
             tag: Optional[str] = None, include_attachments: bool = True,
             include_archived: bool = False) -> List[Any]:
        pass

    @abc.abstractmethod
    def list_archived(self) -> List[Any]:
        """SOT-1500: アーカイブ済み(is_archived=True)の本登録項目のみを返す。"""
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
    def list_next_week(self) -> List[Any]:
        pass

    @abc.abstractmethod
    def list_pending(self) -> List[Any]:
        pass

    @abc.abstractmethod
    def list_drafts(self) -> List[Any]:
        pass

    @abc.abstractmethod
    def count_processing(self) -> int:
        pass

    @abc.abstractmethod
    def list_processing(self) -> List[Any]:
        pass

    @abc.abstractmethod
    def finalize(self, id: Union[int, str]) -> Optional[Any]:
        pass

    @abc.abstractmethod
    def update(self, id: Union[int, str], data: schemas.NurseryInfoUpdate) -> Optional[Any]:
        pass

    @abc.abstractmethod
    def list_by_deadline_group(self, group_id: str) -> List[Any]:
        """SOT-1411: 同じ deadline_group_id を持つ締切調査タスク群（付随タスク）を返す。
        group_id が falsy のときは空リスト。"""
        pass

    @abc.abstractmethod
    def list_attachments_for_info(self, id: Union[int, str]) -> List[Any]:
        pass

    @abc.abstractmethod
    def delete(self, id: Union[int, str]) -> bool:
        pass

    @abc.abstractmethod
    def delete_all(self) -> Tuple[int, List[str]]:
        """全データ削除 (SOT-1356)。全 NurseryInfo（登録済み/draft/pending 区別なく全件）と
        その全 Attachment を削除し、(削除した info 件数, ストレージ blob の object_key 一覧) を返す。
        blob 実体の削除は呼び出し側（ルーター）が返り値の object_key で行う。"""
        pass


class AttachmentRepository(abc.ABC):
    @abc.abstractmethod
    def info_exists(self, info_id: Union[int, str]) -> bool:
        pass

    @abc.abstractmethod
    def create(self, *, info_id: Union[int, str], stored_filename: str,
               original_filename: str, mime_type: str, file_size: int,
               storage_backend: str, object_key: Optional[str],
               ocr_text: Optional[str], ocr_status: str = "pending",
               language: Optional[str] = None,
               municipality: Optional[str] = None) -> Any:
        pass

    @abc.abstractmethod
    def get(self, att_id: Union[int, str]) -> Optional[Any]:
        pass

    @abc.abstractmethod
    def get_by_object_key(self, object_key: str) -> Optional[Any]:
        """SOT-1377: GCS finalize イベントから object_key で添付を逆引きする。"""
        pass

    @abc.abstractmethod
    def begin_ocr_if_pending(self, att_id: Union[int, str]) -> bool:
        """SOT-1377: ocr_status を pending → processing に CAS 遷移する。

        遷移できた(=この呼び出しが OCR を起動する責務を獲得した)場合のみ True。
        既に processing/done/failed なら False を返し、重複 finalize 配送を吸収する。
        """
        pass

    @abc.abstractmethod
    def set_ocr_result(self, att_id: Union[int, str], *, ocr_text: Optional[str], ocr_status: str) -> None:
        pass

    @abc.abstractmethod
    def set_translation(self, att_id: Union[int, str], *, language: str, text: str) -> None:
        """文字起こしの翻訳を言語ごとに保存する (SOT-1330)。読み込みの度に翻訳しないためのキャッシュ。"""
        pass

    @abc.abstractmethod
    def delete(self, att_id: Union[int, str]) -> bool:
        pass


class ChildRepository(abc.ABC):
    """SOT-1368: 子供(option A) の登録・一覧・削除。"""

    @abc.abstractmethod
    def list(self) -> List[Any]:
        pass

    @abc.abstractmethod
    def create(self, data: schemas.ChildCreate) -> Any:
        pass

    @abc.abstractmethod
    def delete(self, child_id: Union[int, str]) -> bool:
        pass


# --- SQLite Implementation ---

def _sqlite_registered_only():
    """本登録(registered)のみを対象にする SQLAlchemy フィルタ。
    未設定(旧データ)は registered 扱いで残し、draft だけを除外する。"""
    return or_(
        models.NurseryInfo.registration_state == "registered",
        models.NurseryInfo.registration_state.is_(None),
    )


def _sqlite_not_archived():
    """SOT-1500: 非アーカイブ(is_archived が False/NULL)のみを対象にする SQLAlchemy フィルタ。
    既存(未設定)データは NULL = 非アーカイブ扱いで残す。"""
    return or_(
        models.NurseryInfo.is_archived == False,  # noqa: E712 (SQLAlchemy 列比較)
        models.NurseryInfo.is_archived.is_(None),
    )


class SqliteInfoRepository(InfoRepository):
    def __init__(self, db: Session, owner_id: Optional[str] = None):
        self.db = db
        # SOT-1431: owner_id None = 無絞り(system/背景タスク/直接構築の単体テスト)。
        self.owner_id = _normalize_owner(owner_id)

    def _scoped(self, query):
        """SOT-1431: owner が設定されていれば owner 絞り込みを適用する。"""
        if self.owner_id is not None:
            query = query.filter(_sqlite_owner_filter(models.NurseryInfo, self.owner_id))
        return query

    def create(self, data: schemas.NurseryInfoCreate) -> models.NurseryInfo:
        payload = data.model_dump()
        # SOT-1431: リクエスト経路では current user の owner を強制する(ボディのなりすまし無効化)。
        # 背景経路(owner None)ではスキーマ由来の owner_id(親写真から継承)をそのまま使う。
        if self.owner_id is not None:
            payload["owner_id"] = self.owner_id
        db_info = models.NurseryInfo(**payload)
        self.db.add(db_info)
        self.db.commit()
        self.db.refresh(db_info)
        return db_info

    def get(self, id: Union[int, str]) -> Optional[models.NurseryInfo]:
        # SOT-1431: owner スコープ付き get。他 owner の ID を指定しても None を返す
        # （update/delete/finalize/list_attachments_for_info は self.get を経由するため一律に保護される）。
        query = self.db.query(models.NurseryInfo).filter(models.NurseryInfo.id == int(id))
        return self._scoped(query).first()

    def list(self, q: Optional[str] = None, info_type: Optional[str] = None,
             status: Optional[str] = None, priority: Optional[str] = None,
             tag: Optional[str] = None, include_attachments: bool = True,
             include_archived: bool = False) -> List[models.NurseryInfo]:
        query = self._scoped(self.db.query(models.NurseryInfo).filter(_sqlite_registered_only()))

        # SOT-1500: 既定ではアーカイブ済みを一覧から除外する（NULL/False は非アーカイブ扱い）。
        if not include_archived:
            query = query.filter(_sqlite_not_archived())

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

    def list_archived(self) -> List[models.NurseryInfo]:
        # SOT-1500: アーカイブ済みの本登録項目のみ。やることリストと同様に扱えるよう新しい順で返す。
        return self._scoped(self.db.query(models.NurseryInfo).filter(
            _sqlite_registered_only(),
            models.NurseryInfo.is_archived == True,  # noqa: E712
        )).order_by(models.NurseryInfo.created_at.desc()).all()

    def list_today(self) -> List[models.NurseryInfo]:
        # 今日やること: 本日が日付/行事日/提出期限のいずれかに該当する情報 (SOT-1093)
        today = clock.today()
        return self._scoped(self.db.query(models.NurseryInfo).filter(
            _sqlite_registered_only(),
            or_(
                models.NurseryInfo.date == today,
                models.NurseryInfo.event_date == today,
                models.NurseryInfo.due_date == today,
            )
        )).all()

    def list_tomorrow(self) -> List[models.NurseryInfo]:
        tomorrow = clock.today() + datetime.timedelta(days=1)
        return self._scoped(self.db.query(models.NurseryInfo).filter(
            _sqlite_registered_only(),
            or_(
                models.NurseryInfo.event_date == tomorrow,
                (models.NurseryInfo.info_type == "持ち物") & (models.NurseryInfo.date == tomorrow)
            )
        )).all()

    def list_weekly(self) -> List[models.NurseryInfo]:
        # 今週の予定 (SOT-1424): 本日から今週末(日曜)までのカレンダー週に event_date を持つ予定。
        # 種別(info_type)で絞らない: 行事だけに限定すると、写真OCRから分割された
        # 持ち物/提出物等のタスク(event_date を持つ)が「予定」枠から落ち、「一部は載るが
        # 一部は載らない」状態になっていた。今日/明日の枠と同じく種別を問わず日付で集計する。
        today = clock.today()
        this_week_end, _, _ = _calendar_week_bounds(today)
        return self._scoped(self.db.query(models.NurseryInfo).filter(
            _sqlite_registered_only(),
            models.NurseryInfo.event_date >= today,
            models.NurseryInfo.event_date <= this_week_end
        )).order_by(models.NurseryInfo.event_date.asc()).all()

    def list_next_week(self) -> List[models.NurseryInfo]:
        # 来週の予定 (SOT-1296 / SOT-1424): 翌カレンダー週(月〜日)に event_date を持つ予定。
        # 本日起点のローリング窓だと、カレンダー上「来週」でも本日から7日以内の予定は
        # 「今週」枠に入り「来週」枠が空白になっていた。カレンダー週境界に揃える。
        # また種別(info_type)では絞らない(list_weekly と同じ理由)。
        today = clock.today()
        _, next_week_start, next_week_end = _calendar_week_bounds(today)
        return self._scoped(self.db.query(models.NurseryInfo).filter(
            _sqlite_registered_only(),
            models.NurseryInfo.event_date >= next_week_start,
            models.NurseryInfo.event_date <= next_week_end
        )).order_by(models.NurseryInfo.event_date.asc()).all()

    def list_pending(self) -> List[models.NurseryInfo]:
        # 未対応のタスク: 提出物に限らず全カテゴリ横断で status=="未対応" (SOT-1093)
        return self._scoped(self.db.query(models.NurseryInfo).filter(
            _sqlite_registered_only(),
            models.NurseryInfo.status == "未対応"
        )).all()

    def list_drafts(self) -> List[models.NurseryInfo]:
        # 仮登録(draft)のみ。新しい順で返す。
        return self._scoped(self.db.query(models.NurseryInfo).filter(
            models.NurseryInfo.registration_state == "draft"
        )).order_by(models.NurseryInfo.created_at.desc()).all()

    def count_processing(self) -> int:
        # SOT-1380: 文字起こし中(processing)の件数。仮登録画面のインジケータ用。
        return self._scoped(self.db.query(models.NurseryInfo).filter(
            models.NurseryInfo.registration_state == "processing"
        )).count()

    def list_processing(self) -> List[models.NurseryInfo]:
        # SOT-1499: 文字起こし(読み取り)中の項目。追加で自動登録した写真を、
        # 完了を待たず仮登録画面に「読み取り中」カードとして表示するため、写真付きで新しい順に返す。
        return self._scoped(self.db.query(models.NurseryInfo).filter(
            models.NurseryInfo.registration_state == "processing"
        )).order_by(models.NurseryInfo.created_at.desc()).all()

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

    def list_by_deadline_group(self, group_id: str) -> List[models.NurseryInfo]:
        if not group_id:
            return []
        return self._scoped(self.db.query(models.NurseryInfo).filter(
            models.NurseryInfo.deadline_group_id == group_id
        )).all()

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

    def delete_all(self) -> Tuple[int, List[str]]:
        # SOT-1431: owner が設定されていれば、その owner のデータ(と写真)のみを削除する。
        # 「全データ削除」ボタンは押したユーザー自身のデータだけを消す。
        # blob 削除用に対象 attachment の object_key を先に集める。
        object_keys: List[str] = []
        att_query = self.db.query(models.Attachment)
        if self.owner_id is not None:
            att_query = att_query.join(
                models.NurseryInfo, models.Attachment.info_id == models.NurseryInfo.id
            ).filter(_sqlite_owner_filter(models.NurseryInfo, self.owner_id))
        for att in att_query.all():
            key = att.object_key or att.stored_filename
            if key:
                object_keys.append(key)
        infos = self._scoped(self.db.query(models.NurseryInfo)).all()
        count = len(infos)
        for info in infos:
            # relationship cascade="all, delete-orphan" で attachment も削除される
            self.db.delete(info)
        self.db.commit()
        return count, object_keys


class SqliteAttachmentRepository(AttachmentRepository):
    def __init__(self, db: Session, owner_id: Optional[str] = None):
        self.db = db
        # SOT-1431: owner None = 無絞り(背景OCRタスク/直接構築の単体テスト)。
        self.owner_id = _normalize_owner(owner_id)

    def info_exists(self, info_id: Union[int, str]) -> bool:
        # SOT-1431: owner が設定されていれば、その owner の info だけを存在扱いにする
        # （他 owner の info への添付アップロードを防ぐ）。
        query = self.db.query(models.NurseryInfo).filter(models.NurseryInfo.id == int(info_id))
        if self.owner_id is not None:
            query = query.filter(_sqlite_owner_filter(models.NurseryInfo, self.owner_id))
        return query.first() is not None

    def create(self, *, info_id: Union[int, str], stored_filename: str,
               original_filename: str, mime_type: str, file_size: int,
               storage_backend: str, object_key: Optional[str],
               ocr_text: Optional[str], ocr_status: str = "pending",
               language: Optional[str] = None,
               municipality: Optional[str] = None) -> models.Attachment:
        db_attachment = models.Attachment(
            info_id=int(info_id),
            stored_filename=stored_filename,
            original_filename=original_filename,
            mime_type=mime_type,
            file_size=file_size,
            storage_backend=storage_backend,
            object_key=object_key,
            ocr_text=ocr_text,
            ocr_status=ocr_status,
            language=language,
            municipality=municipality,
        )
        self.db.add(db_attachment)
        self.db.commit()
        self.db.refresh(db_attachment)
        return db_attachment

    def get(self, att_id: Union[int, str]) -> Optional[models.Attachment]:
        # SOT-1431: owner が設定されていれば、親 info が current owner のものである添付だけを返す。
        # これで GET /attachments/{id}/file・/transcription・DELETE・finalize が横断アクセスから守られる。
        query = self.db.query(models.Attachment).filter(models.Attachment.id == int(att_id))
        if self.owner_id is not None:
            query = query.join(
                models.NurseryInfo, models.Attachment.info_id == models.NurseryInfo.id
            ).filter(_sqlite_owner_filter(models.NurseryInfo, self.owner_id))
        return query.first()

    def get_by_object_key(self, object_key: str) -> Optional[models.Attachment]:
        return (
            self.db.query(models.Attachment)
            .filter(models.Attachment.object_key == object_key)
            .order_by(models.Attachment.id.desc())
            .first()
        )

    def begin_ocr_if_pending(self, att_id: Union[int, str]) -> bool:
        # 条件付き UPDATE による CAS: pending の行だけ processing に遷移させ、
        # 更新行数が 1 のときだけ True（=このプロセスが OCR 起動権を獲得）。
        updated = (
            self.db.query(models.Attachment)
            .filter(
                models.Attachment.id == int(att_id),
                models.Attachment.ocr_status == "pending",
            )
            .update({models.Attachment.ocr_status: "processing"})
        )
        self.db.commit()
        return updated == 1

    def set_ocr_result(self, att_id: Union[int, str], *, ocr_text: Optional[str], ocr_status: str) -> None:
        db_attachment = self.get(att_id)
        if db_attachment:
            db_attachment.ocr_text = ocr_text
            db_attachment.ocr_status = ocr_status
            self.db.commit()

    def set_translation(self, att_id: Union[int, str], *, language: str, text: str) -> None:
        db_attachment = self.get(att_id)
        if db_attachment:
            # SQLAlchemy の JSON 変更検知のため、新しい dict を代入する
            current = dict(db_attachment.translations or {})
            current[language] = text
            db_attachment.translations = current
            self.db.commit()

    def delete(self, att_id: Union[int, str]) -> bool:
        db_attachment = self.get(att_id)
        if not db_attachment:
            return False

        self.db.delete(db_attachment)
        self.db.commit()
        return True


class SqliteChildRepository(ChildRepository):
    def __init__(self, db: Session, owner_id: Optional[str] = None):
        self.db = db
        self.owner_id = _normalize_owner(owner_id)

    def list(self) -> List[models.Child]:
        query = self.db.query(models.Child)
        if self.owner_id is not None:
            query = query.filter(_sqlite_owner_filter(models.Child, self.owner_id))
        return query.order_by(models.Child.created_at.asc()).all()

    def create(self, data: schemas.ChildCreate) -> models.Child:
        # SOT-1431: 作成時に current owner を付与する(リクエスト経路)。owner None(背景)は未設定のまま。
        # SOT-1552: 所属する組/クラス（任意）。空文字は None に正規化する。
        db_child = models.Child(
            name=data.name,
            owner_id=self.owner_id,
            group_name=(data.group_name or None),
        )
        self.db.add(db_child)
        self.db.commit()
        self.db.refresh(db_child)
        return db_child

    def delete(self, child_id: Union[int, str]) -> bool:
        query = self.db.query(models.Child).filter(models.Child.id == int(child_id))
        if self.owner_id is not None:
            query = query.filter(_sqlite_owner_filter(models.Child, self.owner_id))
        db_child = query.first()
        if not db_child:
            return False
        self.db.delete(db_child)
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
    translations: Optional[dict] = None
    language: Optional[str] = None
    municipality: Optional[str] = None

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
    # SOT-1431: データ所有者(マルチテナント分離)。未設定は既定 owner 扱い。
    owner_id: Optional[str] = None
    child_id: Optional[str] = None
    # SOT-1562: 基になった登録写真レコードへの参照。未設定は参照なし(手動追加/既存タスク)。
    source_info_id: Optional[str] = None
    # SOT-1407: 締め切り調査が必要なタスクか。
    needs_deadline_investigation: bool = False
    # SOT-1428: お気に入りフラグ。
    is_favorite: bool = False
    # SOT-1500: アーカイブフラグ。
    is_archived: bool = False
    # SOT-1411: 締切調査タスク群のグループ識別子・基準日からの日数オフセット・基準日。
    deadline_group_id: Optional[str] = None
    deadline_offset_days: Optional[int] = None
    deadline_base_date: Optional[datetime.date] = None
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
        status=data.get("status", "未確認"),
        priority=data.get("priority", "普通"),
        tags=_tags_array_to_str(data.get("tags")),
        memo=data.get("memo"),
        registration_state=data.get("registration_state") or "registered",
        owner_id=data.get("owner_id"),
        child_id=data.get("child_id"),
        source_info_id=data.get("source_info_id"),
        needs_deadline_investigation=bool(data.get("needs_deadline_investigation")),
        is_favorite=bool(data.get("is_favorite")),
        is_archived=bool(data.get("is_archived")),
        deadline_group_id=data.get("deadline_group_id"),
        deadline_offset_days=data.get("deadline_offset_days"),
        deadline_base_date=_to_date(data.get("deadline_base_date")),
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
        created_at=data.get("created_at") or datetime.datetime.now(),
        translations=data.get("translations") or {},
        language=data.get("language"),
        municipality=data.get("municipality"),
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
    def __init__(self, owner_id: Optional[str] = None):
        self.project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        self.database_id = os.getenv("FIRESTORE_DATABASE", "(default)")
        self._db = None
        # SOT-1431: owner None = 無絞り(system/背景タスク)。
        self.owner_id = _normalize_owner(owner_id)

    @property
    def db(self):
        if self._db is None:
            from google.cloud import firestore
            self._db = firestore.Client(project=self.project_id, database=self.database_id)
        return self._db

    def _owner_ok(self, data: dict) -> bool:
        """SOT-1431: owner が設定されていれば、ドキュメントが current owner のものか判定する。

        owner 絞りは Firestore の `.where` に載せない（複合インデックス要求を避ける。SOT-1285 の教訓）。
        全件 stream 後にアプリ側でこの判定を適用する。
        """
        if self.owner_id is None:
            return True
        return _owner_of(data) == self.owner_id

    def create(self, data: schemas.NurseryInfoCreate) -> FirestoreNurseryInfo:
        now = datetime.datetime.now(datetime.timezone.utc)
        doc_data = data.model_dump()
        # SOT-1431: リクエスト経路では current owner を強制。背景経路(owner None)はスキーマ由来
        # (親写真から継承した owner_id)をそのまま使う。
        if self.owner_id is not None:
            doc_data["owner_id"] = self.owner_id
        # Convert dates and tags
        doc_data["date"] = _from_date(doc_data.get("date"))
        doc_data["event_date"] = _from_date(doc_data.get("event_date"))
        doc_data["due_date"] = _from_date(doc_data.get("due_date"))
        doc_data["deadline_base_date"] = _from_date(doc_data.get("deadline_base_date"))
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
        # SOT-1431: 他 owner の ID を指定しても None を返す。
        if not self._owner_ok(doc.to_dict()):
            return None

        # Get attachments
        att_refs = self.db.collection("attachments").where("info_id", "==", str(id)).stream()
        attachments = [_att_doc_to_obj(att.id, att.to_dict()) for att in att_refs]

        return _info_doc_to_obj(doc.id, doc.to_dict(), attachments)

    def list(self, q: Optional[str] = None, info_type: Optional[str] = None,
             status: Optional[str] = None, priority: Optional[str] = None,
             tag: Optional[str] = None, include_attachments: bool = True,
             include_archived: bool = False) -> List[FirestoreNurseryInfo]:
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
            # SOT-1431: owner 絞り(アプリ側)。
            if not self._owner_ok(doc_data):
                continue
            # 仮登録(draft)は通常一覧に含めない (SOT-1113)
            if not _is_registered_data(doc_data):
                continue
            # SOT-1500: 既定ではアーカイブ済みを一覧から除外する。
            if not include_archived and bool(doc_data.get("is_archived")):
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

    def list_archived(self) -> List[FirestoreNurseryInfo]:
        # SOT-1500: アーカイブ済みの本登録項目のみ。owner 絞り(アプリ側)は list と同方式。
        results: List[FirestoreNurseryInfo] = []
        for doc in self.db.collection("nursery_info").stream():
            doc_data = doc.to_dict()
            if not self._owner_ok(doc_data):
                continue
            if not _is_registered_data(doc_data):
                continue
            if not bool(doc_data.get("is_archived")):
                continue
            att_refs = self.db.collection("attachments").where("info_id", "==", doc.id).stream()
            attachments = [_att_doc_to_obj(att.id, att.to_dict()) for att in att_refs]
            results.append(_info_doc_to_obj(doc.id, doc_data, attachments))
        # 新しい順（created_at 降順）で返す。
        results.sort(key=lambda r: r.created_at, reverse=True)
        return results

    def list_today(self) -> List[FirestoreNurseryInfo]:
        # 今日やること: 本日が date/event_date/due_date のいずれかに該当 (SOT-1093)
        today_str = _from_date(clock.today())

        results_dict = {}
        for field_name in ("date", "event_date", "due_date"):
            for doc in self.db.collection("nursery_info").where(field_name, "==", today_str).stream():
                results_dict[doc.id] = doc.to_dict()

        results = []
        for doc_id, data in results_dict.items():
            if not self._owner_ok(data):  # SOT-1431: owner 絞り
                continue
            if not _is_registered_data(data):  # 仮登録は除外 (SOT-1113)
                continue
            att_refs = self.db.collection("attachments").where("info_id", "==", doc_id).stream()
            attachments = [_att_doc_to_obj(att.id, att.to_dict()) for att in att_refs]
            results.append(_info_doc_to_obj(doc_id, data, attachments))
        return results

    def list_tomorrow(self) -> List[FirestoreNurseryInfo]:
        tomorrow_date = clock.today() + datetime.timedelta(days=1)
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
            if not self._owner_ok(data):  # SOT-1431: owner 絞り
                continue
            if not _is_registered_data(data):  # 仮登録は除外 (SOT-1113)
                continue
            att_refs = self.db.collection("attachments").where("info_id", "==", doc_id).stream()
            attachments = [_att_doc_to_obj(att.id, att.to_dict()) for att in att_refs]
            results.append(_info_doc_to_obj(doc_id, data, attachments))

        return results

    def list_weekly(self) -> List[FirestoreNurseryInfo]:
        # 今週の予定 (SOT-1424): 本日から今週末(日曜)までのカレンダー週に event_date を持つ予定。
        # 種別(info_type)で絞らない: 行事だけに限定すると、写真OCRから分割された
        # 持ち物/提出物等のタスク(event_date を持つ)が「予定」枠から落ちていた。
        today = clock.today()
        this_week_end, _, _ = _calendar_week_bounds(today)
        today_str = _from_date(today)
        week_end_str = _from_date(this_week_end)

        # SOT-1285 の教訓: 範囲条件(event_date)を Firestore 側に投げると複合インデックスや
        # 単一インデックスを要求し、未作成だと「予定」欄が読み込み中のまま固まる。
        # 全 nursery_info を取得し event_date の範囲はアプリ側でフィルタする
        # (event_date は ISO 文字列 YYYY-MM-DD なので辞書順=日付順)。
        docs = self.db.collection("nursery_info").stream()

        results = []
        for doc in docs:
            data = doc.to_dict()
            if not self._owner_ok(data):  # SOT-1431: owner 絞り
                continue
            if not _is_registered_data(data):  # 仮登録は除外 (SOT-1113)
                continue
            event_date = data.get("event_date")
            if not event_date or not (today_str <= event_date <= week_end_str):
                continue
            att_refs = self.db.collection("attachments").where("info_id", "==", doc.id).stream()
            attachments = [_att_doc_to_obj(att.id, att.to_dict()) for att in att_refs]
            results.append(_info_doc_to_obj(doc.id, data, attachments))
        results.sort(key=lambda r: r.event_date or "")
        return results

    def list_next_week(self) -> List[FirestoreNurseryInfo]:
        # 来週の予定 (SOT-1296 / SOT-1424): 翌カレンダー週(月〜日)に event_date を持つ予定。
        # 本日起点のローリング窓だと、カレンダー上「来週」でも本日から7日以内の予定は
        # 「今週」枠に入り「来週」枠が空白になっていた。カレンダー週境界に揃える。
        # また種別(info_type)では絞らない(list_weekly と同じ理由)。
        today = clock.today()
        _, next_week_start, next_week_end = _calendar_week_bounds(today)
        next_week_start_str = _from_date(next_week_start)
        next_week_end_str = _from_date(next_week_end)

        # SOT-1285 の教訓: 範囲条件(event_date)は Firestore に投げず、全件取得後に
        # アプリ側でフィルタする(インデックス未作成による読み込み固着を回避)。
        # event_date は ISO 文字列 YYYY-MM-DD なので辞書順=日付順。
        docs = self.db.collection("nursery_info").stream()

        results = []
        for doc in docs:
            data = doc.to_dict()
            if not self._owner_ok(data):  # SOT-1431: owner 絞り
                continue
            if not _is_registered_data(data):  # 仮登録は除外 (SOT-1113)
                continue
            event_date = data.get("event_date")
            if not event_date or not (next_week_start_str <= event_date <= next_week_end_str):
                continue
            att_refs = self.db.collection("attachments").where("info_id", "==", doc.id).stream()
            attachments = [_att_doc_to_obj(att.id, att.to_dict()) for att in att_refs]
            results.append(_info_doc_to_obj(doc.id, data, attachments))
        results.sort(key=lambda r: r.event_date or "")
        return results

    def list_pending(self) -> List[FirestoreNurseryInfo]:
        # 未対応のタスク: 全カテゴリ横断で status=="未対応" (SOT-1093)
        docs = self.db.collection("nursery_info") \
            .where("status", "==", "未対応") \
            .stream()

        results = []
        for doc in docs:
            if not self._owner_ok(doc.to_dict()):  # SOT-1431: owner 絞り
                continue
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
            if not self._owner_ok(doc_data):  # SOT-1431: owner 絞り
                continue
            if (doc_data.get("registration_state") or "registered") != "draft":
                continue
            att_refs = self.db.collection("attachments").where("info_id", "==", doc.id).stream()
            attachments = [_att_doc_to_obj(att.id, att.to_dict()) for att in att_refs]
            results.append(_info_doc_to_obj(doc.id, doc_data, attachments))
        results.sort(key=lambda i: i.created_at, reverse=True)
        return results

    def count_processing(self) -> int:
        # SOT-1380: 文字起こし中(processing)の件数。件数のみ集計し attachments は読まない。
        count = 0
        for doc in self.db.collection("nursery_info").stream():
            data = doc.to_dict()
            if not self._owner_ok(data):  # SOT-1431: owner 絞り
                continue
            if (data.get("registration_state") or "registered") == "processing":
                count += 1
        return count

    def list_processing(self) -> List[FirestoreNurseryInfo]:
        # SOT-1499: 文字起こし(読み取り)中の項目を写真付きで返す。仮登録画面に「読み取り中」
        # カードとして表示するため、attachments も読み込む（list_drafts と同形）。
        docs = self.db.collection("nursery_info").stream()
        results = []
        for doc in docs:
            doc_data = doc.to_dict()
            if not self._owner_ok(doc_data):  # SOT-1431: owner 絞り
                continue
            if (doc_data.get("registration_state") or "registered") != "processing":
                continue
            att_refs = self.db.collection("attachments").where("info_id", "==", doc.id).stream()
            attachments = [_att_doc_to_obj(att.id, att.to_dict()) for att in att_refs]
            results.append(_info_doc_to_obj(doc.id, doc_data, attachments))
        results.sort(key=lambda i: i.created_at, reverse=True)
        return results

    def finalize(self, id: Union[int, str]) -> Optional[FirestoreNurseryInfo]:
        doc_ref = self.db.collection("nursery_info").document(str(id))
        snap = doc_ref.get()
        if not snap.exists or not self._owner_ok(snap.to_dict()):  # SOT-1431: owner 絞り
            return None
        doc_ref.update({
            "registration_state": "registered",
            "updated_at": datetime.datetime.now(datetime.timezone.utc),
        })
        return self.get(id)

    def update(self, id: Union[int, str], data: schemas.NurseryInfoUpdate) -> Optional[FirestoreNurseryInfo]:
        doc_ref = self.db.collection("nursery_info").document(str(id))
        doc = doc_ref.get()
        if not doc.exists or not self._owner_ok(doc.to_dict()):  # SOT-1431: owner 絞り
            return None

        update_data = data.model_dump(exclude_unset=True)
        # SOT-1431: 更新で owner_id を書き換えさせない(なりすまし防止)。
        update_data.pop("owner_id", None)
        # Convert dates and tags
        if "date" in update_data:
            update_data["date"] = _from_date(update_data["date"])
        if "event_date" in update_data:
            update_data["event_date"] = _from_date(update_data["event_date"])
        if "due_date" in update_data:
            update_data["due_date"] = _from_date(update_data["due_date"])
        if "deadline_base_date" in update_data:
            update_data["deadline_base_date"] = _from_date(update_data["deadline_base_date"])
        if "tags" in update_data:
            update_data["tags"] = _tags_str_to_array(update_data["tags"])
        
        update_data["updated_at"] = datetime.datetime.now(datetime.timezone.utc)
        
        doc_ref.update(update_data)
        return self.get(id)

    def list_by_deadline_group(self, group_id: str) -> List[FirestoreNurseryInfo]:
        if not group_id:
            return []
        docs = self.db.collection("nursery_info").where(
            "deadline_group_id", "==", group_id
        ).stream()
        return [
            _info_doc_to_obj(doc.id, doc.to_dict())
            for doc in docs
            if self._owner_ok(doc.to_dict())  # SOT-1431: owner 絞り
        ]

    def list_attachments_for_info(self, id: Union[int, str]) -> List[FirestoreAttachment]:
        # SOT-1431: 親 info が current owner のものでなければ添付を返さない
        # （delete_info が blob 削除前にこれを呼ぶため、横断的な blob 削除を防ぐ）。
        if self.owner_id is not None:
            info_doc = self.db.collection("nursery_info").document(str(id)).get()
            if not info_doc.exists or not self._owner_ok(info_doc.to_dict()):
                return []
        att_refs = self.db.collection("attachments").where("info_id", "==", str(id)).stream()
        return [_att_doc_to_obj(att.id, att.to_dict()) for att in att_refs]

    def delete(self, id: Union[int, str]) -> bool:
        doc_ref = self.db.collection("nursery_info").document(str(id))
        snap = doc_ref.get()
        if not snap.exists or not self._owner_ok(snap.to_dict()):  # SOT-1431: owner 絞り
            return False

        # Delete attachments first
        att_refs = self.db.collection("attachments").where("info_id", "==", str(id)).stream()
        for att in att_refs:
            self.db.collection("attachments").document(att.id).delete()
            
        doc_ref.delete()
        return True

    def delete_all(self) -> Tuple[int, List[str]]:
        # SOT-1431: owner が設定されていれば、その owner のデータ(と写真)のみ削除する。
        # まず削除対象の info id 集合を確定し、その info に属する attachment だけを削除する。
        owned_info_ids = None  # None = 全件(system/owner 未設定)
        if self.owner_id is not None:
            owned_info_ids = set()
            for doc in self.db.collection("nursery_info").stream():
                if self._owner_ok(doc.to_dict()):
                    owned_info_ids.add(doc.id)

        object_keys: List[str] = []
        for att in self.db.collection("attachments").stream():
            data = att.to_dict() or {}
            if owned_info_ids is not None and str(data.get("info_id")) not in owned_info_ids:
                continue
            key = data.get("object_key") or data.get("stored_filename")
            if key:
                object_keys.append(key)
            self.db.collection("attachments").document(att.id).delete()

        # 対象 nursery_info ドキュメントを削除
        count = 0
        for doc in self.db.collection("nursery_info").stream():
            if owned_info_ids is not None and doc.id not in owned_info_ids:
                continue
            self.db.collection("nursery_info").document(doc.id).delete()
            count += 1
        return count, object_keys


class FirestoreAttachmentRepository(AttachmentRepository):
    def __init__(self, owner_id: Optional[str] = None):
        self.project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        self.database_id = os.getenv("FIRESTORE_DATABASE", "(default)")
        self._db = None
        # SOT-1431: owner None = 無絞り(背景OCRタスク)。
        self.owner_id = _normalize_owner(owner_id)

    @property
    def db(self):
        if self._db is None:
            from google.cloud import firestore
            self._db = firestore.Client(project=self.project_id, database=self.database_id)
        return self._db

    def _info_owner_ok(self, info_id) -> bool:
        """SOT-1431: 添付の親 info が current owner のものか判定する。owner 未設定なら常に True。"""
        if self.owner_id is None:
            return True
        doc = self.db.collection("nursery_info").document(str(info_id)).get()
        return doc.exists and _owner_of(doc.to_dict()) == self.owner_id

    def info_exists(self, info_id: Union[int, str]) -> bool:
        doc = self.db.collection("nursery_info").document(str(info_id)).get()
        if not doc.exists:
            return False
        # SOT-1431: 他 owner の info への添付を防ぐ。
        if self.owner_id is not None and _owner_of(doc.to_dict()) != self.owner_id:
            return False
        return True

    def create(self, *, info_id: Union[int, str], stored_filename: str,
               original_filename: str, mime_type: str, file_size: int,
               storage_backend: str, object_key: Optional[str],
               ocr_text: Optional[str], ocr_status: str = "pending",
               language: Optional[str] = None,
               municipality: Optional[str] = None) -> FirestoreAttachment:
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
            "language": language,
            "municipality": municipality,
            "created_at": now
        }
        _, doc_ref = self.db.collection("attachments").add(doc_data)
        return _att_doc_to_obj(doc_ref.id, doc_data)

    def get(self, att_id: Union[int, str]) -> Optional[FirestoreAttachment]:
        doc_ref = self.db.collection("attachments").document(str(att_id))
        doc = doc_ref.get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        # SOT-1431: 親 info が current owner のものでなければ None（横断アクセス遮断）。
        if self.owner_id is not None and not self._info_owner_ok(data.get("info_id")):
            return None
        return _att_doc_to_obj(doc.id, data)

    def get_by_object_key(self, object_key: str) -> Optional[FirestoreAttachment]:
        docs = list(
            self.db.collection("attachments")
            .where("object_key", "==", object_key)
            .limit(1)
            .stream()
        )
        if not docs:
            return None
        return _att_doc_to_obj(docs[0].id, docs[0].to_dict())

    def begin_ocr_if_pending(self, att_id: Union[int, str]) -> bool:
        from google.cloud import firestore

        doc_ref = self.db.collection("attachments").document(str(att_id))

        @firestore.transactional
        def _txn(transaction):
            snap = doc_ref.get(transaction=transaction)
            if not snap.exists:
                return False
            if (snap.to_dict() or {}).get("ocr_status") != "pending":
                return False
            transaction.update(doc_ref, {"ocr_status": "processing"})
            return True

        return _txn(self.db.transaction())

    def set_ocr_result(self, att_id: Union[int, str], *, ocr_text: Optional[str], ocr_status: str) -> None:
        doc_ref = self.db.collection("attachments").document(str(att_id))
        if doc_ref.get().exists:
            doc_ref.update({
                "ocr_text": ocr_text,
                "ocr_status": ocr_status
            })

    def set_translation(self, att_id: Union[int, str], *, language: str, text: str) -> None:
        doc_ref = self.db.collection("attachments").document(str(att_id))
        if doc_ref.get().exists:
            # ドット記法でネストフィールドを更新（translations マップが無ければ作成される）
            doc_ref.update({f"translations.{language}": text})

    def delete(self, att_id: Union[int, str]) -> bool:
        doc_ref = self.db.collection("attachments").document(str(att_id))
        snap = doc_ref.get()
        if not snap.exists:
            return False
        # SOT-1528(L2): owner スコープを delete 内でも強制（多層防御）。親 info が current owner の
        # 添付でなければ削除しない。ルータ側チェックが将来変わっても越境削除を防ぐ。
        if self.owner_id is not None and not self._info_owner_ok(
            (snap.to_dict() or {}).get("info_id")
        ):
            return False
        doc_ref.delete()
        return True


@dataclass
class FirestoreChild:
    id: str
    name: str
    created_at: datetime.datetime
    # SOT-1552: 所属する組/クラス（任意）。
    group_name: Optional[str] = None


class FirestoreChildRepository(ChildRepository):
    def __init__(self, owner_id: Optional[str] = None):
        self.project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        self.database_id = os.getenv("FIRESTORE_DATABASE", "(default)")
        self._db = None
        self.owner_id = _normalize_owner(owner_id)

    @property
    def db(self):
        if self._db is None:
            from google.cloud import firestore
            self._db = firestore.Client(project=self.project_id, database=self.database_id)
        return self._db

    def list(self) -> List[FirestoreChild]:
        children = [
            FirestoreChild(
                id=doc.id,
                name=doc.to_dict().get("name", ""),
                created_at=doc.to_dict().get("created_at") or datetime.datetime.now(),
                group_name=doc.to_dict().get("group_name"),  # SOT-1552
            )
            for doc in self.db.collection("children").stream()
            if self.owner_id is None or _owner_of(doc.to_dict()) == self.owner_id  # SOT-1431
        ]
        children.sort(key=lambda c: c.created_at)
        return children

    def create(self, data: schemas.ChildCreate) -> FirestoreChild:
        now = datetime.datetime.now(datetime.timezone.utc)
        # SOT-1431: 作成時に current owner を付与する(owner None=背景は未設定)。
        # SOT-1552: 所属する組/クラス（任意）。空文字は None に正規化する。
        group_name = data.group_name or None
        doc_data = {
            "name": data.name,
            "created_at": now,
            "owner_id": self.owner_id,
            "group_name": group_name,
        }
        _, doc_ref = self.db.collection("children").add(doc_data)
        return FirestoreChild(
            id=doc_ref.id, name=data.name, created_at=now, group_name=group_name
        )

    def delete(self, child_id: Union[int, str]) -> bool:
        doc_ref = self.db.collection("children").document(str(child_id))
        snap = doc_ref.get()
        if not snap.exists:
            return False
        # SOT-1431: 他 owner の子供を削除できない。
        if self.owner_id is not None and _owner_of(snap.to_dict()) != self.owner_id:
            return False
        doc_ref.delete()
        return True


# --- Factory functions ---

def get_database_type() -> str:
    return os.getenv("DATABASE_TYPE", "sqlite").lower()


# SOT-1431: リクエストスコープの repo は current user の owner_id で絞り込む。
# get_current_user は署名付きセッションから owner_id を返す。import はここ(関数外)で行うと
# routers.auth → (何も) の依存だけなので循環しない。
from .routers.auth import get_current_user  # noqa: E402


def get_info_repository(
    db: Session = Depends(database.get_db),
    owner_id: str = Depends(get_current_user),
) -> InfoRepository:
    if get_database_type() == "firestore":
        return FirestoreInfoRepository(owner_id=owner_id)
    return SqliteInfoRepository(db, owner_id=owner_id)

def get_attachment_repository(
    db: Session = Depends(database.get_db),
    owner_id: str = Depends(get_current_user),
) -> AttachmentRepository:
    if get_database_type() == "firestore":
        return FirestoreAttachmentRepository(owner_id=owner_id)
    return SqliteAttachmentRepository(db, owner_id=owner_id)

def get_child_repository(
    db: Session = Depends(database.get_db),
    owner_id: str = Depends(get_current_user),
) -> ChildRepository:
    if get_database_type() == "firestore":
        return FirestoreChildRepository(owner_id=owner_id)
    return SqliteChildRepository(db, owner_id=owner_id)

def get_attachment_repo_standalone() -> Any:
    """Helper for background tasks where Depends() cannot be used."""
    if get_database_type() == "firestore":
        return FirestoreAttachmentRepository()

    # For SQLite, we need a session
    db = database.SessionLocal()
    return SqliteAttachmentRepository(db)


def get_info_repo_standalone() -> Any:
    """Helper for background tasks where Depends() cannot be used (SOT-1293)."""
    if get_database_type() == "firestore":
        return FirestoreInfoRepository()

    # For SQLite, we need a session
    db = database.SessionLocal()
    return SqliteInfoRepository(db)
