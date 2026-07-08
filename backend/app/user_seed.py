"""SOT-1507: 新規ユーザー／既存の未シードユーザーへの初期データ配布（案B）。

現在の既定オーナー（sota.moro@gmail.com）のデータを「初期データの正」とし、そのデータ
（やることタスク ``NurseryInfo`` と子ども ``Child``）を各ユーザーの ``owner_id`` へ独立した
コピーとして配布する。コピー後は各ユーザーが自由に編集できる。

配布判定（SOT-1507 再同期対応）:
- 「一度きりのマーカー」ではなく「**そのユーザーがまだ本登録タスクを1件も持っていないか**」で
  判定する。これにより、新規ユーザーだけでなく、まだデータを持たない既存ユーザー
  （例: demo.user@example.com）も次回ログイン時に初期データを受け取る（＝再同期）。
- **すでに自分のデータを持っているユーザーは上書きしない**（各自の編集を保護する）。破壊的な
  「強制置換」は行わない。
- 既定オーナー自身にはコピーしない（そのデータが正のため）。
- 添付ファイルのバイナリはコピーしない（タスク本体のスカラー項目と子ども情報のみ配布する）。
- ``SeededOwner`` マーカーは配布実績の監査用に記録する（判定には使わない）。
- ベストエフォート: 失敗しても例外を送出せず ``False`` を返す（呼び出し側のログインを止めない）。
- SQLite / Firestore の両バックエンドに対応する。
"""
import logging
import os
from typing import Dict, Optional

from . import database, models
from .identity import DEFAULT_OWNER_ID
from .repository import get_database_type

logger = logging.getLogger(__name__)

# コピー対象の NurseryInfo スカラー列。id / owner_id / created_at / updated_at と
# リレーション attachments は除外する。child_id は別途リマップするためここには含めない。
_INFO_COPY_FIELDS = (
    "title",
    "info_type",
    "content",
    "date",
    "event_date",
    "due_date",
    "items",
    "status",
    "registration_state",
    "needs_deadline_investigation",
    "is_favorite",
    "is_archived",
    "deadline_group_id",
    "deadline_offset_days",
    "deadline_base_date",
    "priority",
    "tags",
    "memo",
)

# SOT-1600: 写真(添付)のうちコピーするスカラー列。id / info_id / created_at と、
# 実体ファイルを指す stored_filename / object_key は別途（新しい実体コピーとして）作り直すため除外。
_ATTACHMENT_COPY_FIELDS = (
    "original_filename",
    "mime_type",
    "file_size",
    "storage_backend",
    "ocr_text",
    "ocr_status",
    "translations",
    "language",
    "municipality",
)


def _copy_attachment_blob(
    src_stored_filename: str, src_object_key: Optional[str], original_filename: str, mime_type: str
) -> tuple:
    """SOT-1600: 既定オーナーの写真実体を読み出し、新しいキーで独立した実体コピーを保存する。

    元データを削除しても配布先の写真が壊れないよう、参照(共有)ではなく実体を複製する。
    返り値は新しい ``(stored_filename, object_key)``。読み出せない場合は例外を送出する
    （呼び出し側が best-effort でスキップする）。
    """
    from . import storage as storage_mod

    backend = storage_mod.get_storage()
    src_key = src_object_key or src_stored_filename
    if backend.name == "gcs":
        content = backend.read(src_key)
    else:
        content = storage_mod.get_file_path(src_key).read_bytes()

    new_stored = storage_mod.generate_stored_filename(original_filename)
    new_key = storage_mod.build_object_key(new_stored)
    backend.save(new_key, content, mime_type)
    return new_stored, new_key


def ensure_user_seeded(owner_id: str) -> bool:
    """``owner_id`` がまだ本登録タスクを持たなければ既定オーナーの初期データをコピーする。

    コピーしたら ``True``。既定オーナー自身・すでにデータを持つオーナー・空の owner_id は
    スキップして ``False`` を返す（既存データは上書きしない）。ベストエフォートのため、
    いかなる失敗でも例外を送出しない。
    """
    if not owner_id or owner_id == DEFAULT_OWNER_ID:
        return False
    try:
        if get_database_type() == "firestore":
            return _seed_firestore(owner_id)
        return _seed_sqlite(owner_id)
    except Exception:  # pragma: no cover - best-effort（ログインを止めない）
        logger.exception("initial-data seeding failed for owner")
        return False


def _seed_sqlite(owner_id: str) -> bool:
    from .repository import _sqlite_owner_filter, _sqlite_registered_only

    db = database.SessionLocal()
    try:
        # 再同期対応(SOT-1507): マーカーではなく「本登録タスクを既に持っているか」で判定する。
        # 既にデータを持つユーザーは上書きしない（各自の編集を保護）。データを持たないユーザー
        # （新規ユーザー および 既存の未シードユーザー = demo.user 等）にのみ配布する。
        has_data = (
            db.query(models.NurseryInfo)
            .filter(
                _sqlite_owner_filter(models.NurseryInfo, owner_id),
                _sqlite_registered_only(),
            )
            .first()
        )
        if has_data is not None:
            return False

        # 子ども: 既定オーナーの Child を新オーナーへコピーし、旧 id → 新 Child のマップを作る。
        child_id_map: Dict[str, models.Child] = {}
        src_children = (
            db.query(models.Child)
            .filter(_sqlite_owner_filter(models.Child, DEFAULT_OWNER_ID))
            .order_by(models.Child.id)
            .all()
        )
        for child in src_children:
            new_child = models.Child(
                owner_id=owner_id,
                name=child.name,
                group_name=getattr(child, "group_name", None),  # SOT-1552: 組/クラスも複製
            )
            db.add(new_child)
            db.flush()  # new_child.id を確定させる
            child_id_map[str(child.id)] = new_child

        # やることタスク: 既定オーナーの本登録データ（draft は除外）をコピーする。
        src_infos = (
            db.query(models.NurseryInfo)
            .filter(
                _sqlite_owner_filter(models.NurseryInfo, DEFAULT_OWNER_ID),
                _sqlite_registered_only(),
            )
            .order_by(models.NurseryInfo.id)
            .all()
        )
        copied_attachments = 0
        for info in src_infos:
            payload = {field: getattr(info, field) for field in _INFO_COPY_FIELDS}
            # child_id を新オーナーの Child.id にリマップ（対応が無ければ紐付け無し）。
            mapped = child_id_map.get(str(info.child_id)) if info.child_id else None
            payload["child_id"] = str(mapped.id) if mapped else None
            new_info = models.NurseryInfo(owner_id=owner_id, **payload)
            db.add(new_info)
            db.flush()  # new_info.id を確定させる（添付の info_id に使う）
            # SOT-1600: 写真(添付)も独立した実体コピーとして配布する。
            copied_attachments += _copy_sqlite_attachments(db, info, new_info.id)

        # 配布実績マーカー（監査用）。再同期で既に存在する場合があるため重複挿入を避ける。
        marker_exists = (
            db.query(models.SeededOwner)
            .filter(models.SeededOwner.owner_id == owner_id)
            .first()
        )
        if marker_exists is None:
            db.add(models.SeededOwner(owner_id=owner_id))
        db.commit()
        logger.info(
            "seeded initial data: %d infos, %d children, %d attachments",
            len(src_infos),
            len(src_children),
            copied_attachments,
        )
        return True
    finally:
        db.close()


def _copy_sqlite_attachments(db, src_info, new_info_id: int) -> int:
    """SOT-1600: 既定オーナーの info に紐づく写真(添付)を新 info へ独立コピーする。

    実体ファイルの読み出しに失敗した添付は best-effort でスキップし（配布を止めない）、
    実際にコピーできた件数を返す。
    """
    count = 0
    for att in src_info.attachments:
        try:
            new_stored, new_key = _copy_attachment_blob(
                att.stored_filename, att.object_key, att.original_filename, att.mime_type
            )
        except Exception:  # pragma: no cover - best-effort（実体が無い等）
            logger.warning("skip copying attachment blob during seeding (info_id=%s)", new_info_id)
            continue
        payload = {field: getattr(att, field) for field in _ATTACHMENT_COPY_FIELDS}
        db.add(
            models.Attachment(
                info_id=new_info_id,
                stored_filename=new_stored,
                object_key=new_key,
                **payload,
            )
        )
        count += 1
    return count


def _seed_firestore(owner_id: str) -> bool:
    from google.cloud import firestore

    from .repository import _is_registered_data, _owner_of

    client = firestore.Client(
        project=os.getenv("GOOGLE_CLOUD_PROJECT"),
        database=os.getenv("FIRESTORE_DATABASE", "(default)"),
    )

    # 再同期対応(SOT-1507): マーカーではなく「本登録タスクを既に持っているか」で判定する。
    # 既にデータを持つユーザーは上書きしない（各自の編集を保護）。
    marker_ref = client.collection("seeded_owners").document(owner_id)
    for doc in client.collection("nursery_info").stream():
        data = doc.to_dict()
        if _owner_of(data) == owner_id and _is_registered_data(data):
            return False

    # 子ども: 既定オーナーの Child をコピーし、旧 doc.id → 新 doc.id マップを作る。
    child_id_map: Dict[str, str] = {}
    for doc in client.collection("children").stream():
        data = doc.to_dict()
        if _owner_of(data) != DEFAULT_OWNER_ID:
            continue
        _, new_ref = client.collection("children").add(
            {
                "name": data.get("name", ""),
                "owner_id": owner_id,
                "group_name": data.get("group_name"),  # SOT-1552: 組/クラスも複製
                "created_at": firestore.SERVER_TIMESTAMP,
            }
        )
        child_id_map[doc.id] = new_ref.id

    # やることタスク: 既定オーナーの本登録データ（draft は除外）をコピーする。
    for doc in client.collection("nursery_info").stream():
        data = doc.to_dict()
        if _owner_of(data) != DEFAULT_OWNER_ID:
            continue
        if not _is_registered_data(data):
            continue
        new_data = {
            key: value
            for key, value in data.items()
            if key not in ("owner_id", "created_at", "updated_at")
        }
        new_data["owner_id"] = owner_id
        # child_id を新オーナーの Child doc.id にリマップ（対応が無ければ紐付け無し）。
        old_child: Optional[str] = data.get("child_id")
        new_data["child_id"] = child_id_map.get(str(old_child)) if old_child else None
        _, new_info_ref = client.collection("nursery_info").add(new_data)
        # SOT-1600: 写真(添付)も独立した実体コピーとして配布する。
        _copy_firestore_attachments(client, doc.id, new_info_ref.id)

    marker_ref.set({"owner_id": owner_id, "created_at": firestore.SERVER_TIMESTAMP})
    return True


def _copy_firestore_attachments(client, src_info_id: str, new_info_id: str) -> int:
    """SOT-1600: 既定オーナーの info(doc) に紐づく写真(添付)を新 info へ独立コピーする。

    実体 blob の読み出し/保存に失敗した添付は best-effort でスキップする（配布を止めない）。
    """
    count = 0
    for att in (
        client.collection("attachments").where("info_id", "==", str(src_info_id)).stream()
    ):
        data = att.to_dict() or {}
        try:
            new_stored, new_key = _copy_attachment_blob(
                data.get("stored_filename", ""),
                data.get("object_key"),
                data.get("original_filename", ""),
                data.get("mime_type", ""),
            )
        except Exception:  # pragma: no cover - best-effort（実体が無い等）
            logger.warning(
                "skip copying attachment blob during seeding (info_id=%s)", new_info_id
            )
            continue
        new_att = {
            key: value
            for key, value in data.items()
            if key not in ("info_id", "stored_filename", "object_key", "created_at")
        }
        new_att["info_id"] = str(new_info_id)
        new_att["stored_filename"] = new_stored
        new_att["object_key"] = new_key
        client.collection("attachments").add(new_att)
        count += 1
    return count
