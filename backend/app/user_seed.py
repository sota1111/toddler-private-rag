"""SOT-1507: 新規ユーザー／既存の未シードユーザーへの初期データ配布（案B）。

現在の既定オーナー（sota.moro@gmail.com）のデータを「初期データの正」とし、そのデータ
（やることタスク ``NurseryInfo`` と子ども ``Child``）を各ユーザーの ``owner_id`` へ独立した
コピーとして配布する。コピー後は各ユーザーが自由に編集できる。

配布判定（SOT-1507 再同期対応）:
- 「一度きりのマーカー」ではなく「**そのユーザーがまだ本登録タスクを1件も持っていないか**」で
  判定する。これにより、新規ユーザーだけでなく、まだデータを持たない既存ユーザー
  （例: demo.user@example.com）も次回ログイン時に初期データを受け取る（＝再同期）。
- **すでに自分のデータを持っている（実）ユーザーは上書きしない**（各自の編集を保護する）。
  破壊的な「強制置換」は行わない。
- 既定オーナー自身にはコピーしない（そのデータが正のため）。
- SOT-1600: 写真(添付)も独立した実体コピーとして配布する。
- ``SeededOwner`` マーカーは配布実績の監査用に記録する（判定には使わない）。
- ベストエフォート: 失敗しても例外を送出せず ``False`` を返す（呼び出し側のログインを止めない）。
- SQLite / Firestore の両バックエンドに対応する。

デモアカウントの再配布（SOT-1600 再オープン対応）:
- 環境変数 ``SEED_REFRESH_EMAILS``（既定 ``demo.user@example.com``、カンマ区切り）で指定した
  「デモアカウント」は、**常に既定オーナーの最新データを映す鏡**として扱う。ログインのたびに
  既存のシード済みデータ（やることタスク・子ども・写真の実体）を一旦クリアして、既定オーナーの
  現在のデータを再コピーする（＝既定オーナーが変更したら次回ログインで反映）。
- この強制リフレッシュは ``SEED_REFRESH_EMAILS`` に列挙されたアカウント **のみ** に適用され、
  実ユーザーの編集保護（上書きしない）には一切影響しない。既定オーナー自身は対象外。
"""
import logging
import os
from typing import Dict, Optional, Set

from . import database, models
from .identity import DEFAULT_OWNER_ID, owner_id_for_email
from .repository import get_database_type

logger = logging.getLogger(__name__)

# SOT-1600: 「デモアカウント」= 常に既定オーナーの最新初期データを映す鏡として扱うアカウント。
# ここに列挙されたメールの owner_id は、ログイン毎に既存データをクリアして再配布(refresh)する。
_DEFAULT_REFRESH_EMAILS = "demo.user@example.com"


def _refresh_owner_ids() -> Set[str]:
    """再配布(refresh)対象＝デモアカウントの owner_id 集合を環境変数から解決する。

    ``SEED_REFRESH_EMAILS`` はカンマ区切りのメール一覧（既定 ``demo.user@example.com``）。
    空文字を設定すれば「デモ再配布なし＝従来どおり全ユーザー上書きしない」に戻せる。既定オーナー
    自身は（誤設定されても）安全のため常に除外する。
    """
    raw = os.getenv("SEED_REFRESH_EMAILS", _DEFAULT_REFRESH_EMAILS)
    ids = {owner_id_for_email(e.strip()) for e in raw.split(",") if e.strip()}
    ids.discard(DEFAULT_OWNER_ID)
    return ids

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

    コピーしたら ``True``。既定オーナー自身・すでにデータを持つ（実）オーナー・空の owner_id は
    スキップして ``False`` を返す（既存データは上書きしない）。ただし ``SEED_REFRESH_EMAILS`` で
    指定された**デモアカウント**は例外で、既存データがあってもクリアして最新を再配布する
    （SOT-1600）。ベストエフォートのため、いかなる失敗でも例外を送出しない。
    """
    if not owner_id or owner_id == DEFAULT_OWNER_ID:
        return False
    force_refresh = owner_id in _refresh_owner_ids()
    try:
        if get_database_type() == "firestore":
            return _seed_firestore(owner_id, force_refresh)
        return _seed_sqlite(owner_id, force_refresh)
    except Exception:  # pragma: no cover - best-effort（ログインを止めない）
        logger.exception("initial-data seeding failed for owner")
        return False


def _seed_sqlite(owner_id: str, force_refresh: bool = False) -> bool:
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
            if not force_refresh:
                return False
            # SOT-1600: デモアカウントは最新を映す鏡。既存のシード済みデータをクリアして再配布する。
            _clear_owner_data_sqlite(db, owner_id)

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


def _clear_owner_data_sqlite(db, owner_id: str) -> None:
    """SOT-1600: デモアカウントの再配布前に、そのオーナーの既存データを実体ごとクリアする。

    やることタスク・子ども・写真の実体ファイルを削除する（DBの添付行は cascade で消える）。
    実ユーザーには呼ばれない（``SEED_REFRESH_EMAILS`` のデモアカウント限定）。実体削除は
    best-effort（失敗しても DB クリアと再配布は続行する）。
    """
    from .repository import _sqlite_owner_filter

    infos = (
        db.query(models.NurseryInfo)
        .filter(_sqlite_owner_filter(models.NurseryInfo, owner_id))
        .all()
    )
    backend = None
    for info in infos:
        for att in info.attachments:
            if backend is None:
                from . import storage as storage_mod

                backend = storage_mod.get_storage()
            try:
                backend.delete(att.object_key or att.stored_filename)
            except Exception:  # pragma: no cover - best-effort（実体が無い等）
                logger.warning("skip deleting attachment blob during refresh (owner)")
        db.delete(info)  # attachments は cascade で削除される
    for child in (
        db.query(models.Child)
        .filter(_sqlite_owner_filter(models.Child, owner_id))
        .all()
    ):
        db.delete(child)
    db.flush()


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


def _seed_firestore(owner_id: str, force_refresh: bool = False) -> bool:
    from google.cloud import firestore

    from .repository import _is_registered_data, _owner_of

    client = firestore.Client(
        project=os.getenv("GOOGLE_CLOUD_PROJECT"),
        database=os.getenv("FIRESTORE_DATABASE", "(default)"),
    )

    # 再同期対応(SOT-1507): マーカーではなく「本登録タスクを既に持っているか」で判定する。
    # 既にデータを持つ（実）ユーザーは上書きしない（各自の編集を保護）。ただしデモアカウント
    # (SOT-1600) は既存データをクリアして最新を再配布する。
    marker_ref = client.collection("seeded_owners").document(owner_id)
    for doc in client.collection("nursery_info").stream():
        data = doc.to_dict()
        if _owner_of(data) == owner_id and _is_registered_data(data):
            if not force_refresh:
                return False
            _clear_owner_data_firestore(client, owner_id)
            break

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


def _clear_owner_data_firestore(client, owner_id: str) -> None:
    """SOT-1600: デモアカウントの再配布前に、そのオーナーの既存データを実体ごとクリアする。

    やることタスク(doc)・紐づく添付(doc)と実体 blob・子ども(doc) を削除する。実ユーザーには
    呼ばれない（``SEED_REFRESH_EMAILS`` のデモアカウント限定）。実体削除は best-effort。
    """
    from .repository import _owner_of

    backend = None
    for doc in client.collection("nursery_info").stream():
        data = doc.to_dict()
        if _owner_of(data) != owner_id:
            continue
        for att in (
            client.collection("attachments").where("info_id", "==", str(doc.id)).stream()
        ):
            adata = att.to_dict() or {}
            key = adata.get("object_key") or adata.get("stored_filename")
            if key:
                if backend is None:
                    from . import storage as storage_mod

                    backend = storage_mod.get_storage()
                try:
                    backend.delete(key)
                except Exception:  # pragma: no cover - best-effort（実体が無い等）
                    logger.warning("skip deleting attachment blob during refresh (owner)")
            att.reference.delete()
        doc.reference.delete()
    for child in client.collection("children").stream():
        if _owner_of(child.to_dict()) == owner_id:
            child.reference.delete()


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
