import os
import datetime
import logging
from typing import Optional, Any
from . import models, storage, repository

logger = logging.getLogger(__name__)

def get_retention_days() -> int:
    """
    環境変数 ATTACHMENT_RETENTION_DAYS から保持日数を取得する。
    未設定または0以下の場合は無期限（パージ無効）。
    """
    try:
        days = int(os.getenv("ATTACHMENT_RETENTION_DAYS", "0"))
        return days if days > 0 else 0
    except ValueError:
        return 0

def purge_expired_attachments(repo: Optional[Any] = None, now: Optional[datetime.datetime] = None) -> int:
    """
    保持期限を超えた添付ファイルを削除し、削除件数を返す。
    """
    retention_days = get_retention_days()
    if retention_days <= 0:
        logger.info("Retention policy is disabled (days <= 0).")
        return 0

    if now is None:
        now = datetime.datetime.now(datetime.timezone.utc)
    
    threshold_date = now - datetime.timedelta(days=retention_days)
    
    # リポジトリが提供されない場合はスタンドアロン版を取得
    provided_repo = repo
    if repo is None:
        repo = repository.get_attachment_repo_standalone()
    
    deleted_count = 0
    try:
        # SQLite の場合は直接 SQLAlchemy クエリを使用
        if isinstance(repo, repository.SqliteAttachmentRepository):
            expired_attachments = repo.db.query(models.Attachment).filter(
                models.Attachment.created_at < threshold_date
            ).all()
            
            for att in expired_attachments:
                try:
                    # 物理ファイルの削除
                    backend = storage.get_storage()
                    backend.delete(att.object_key or att.stored_filename)
                    
                    # DBレコードの削除
                    repo.db.delete(att)
                    deleted_count += 1
                except Exception as e:
                    logger.error(f"Failed to delete attachment {att.id}: {str(e)}")
            
            repo.db.commit()
        
        # Firestore の場合はベストエフォート（現在は SQLite 既定を優先）
        elif isinstance(repo, repository.FirestoreAttachmentRepository):
            # Firestore では created_at でフィルタしてストリーム
            docs = repo.db.collection("attachments").where("created_at", "<", threshold_date).stream()
            for doc in docs:
                try:
                    att_data = doc.to_dict()
                    # 物理ファイルの削除
                    backend = storage.get_storage()
                    backend.delete(att_data.get("object_key") or att_data.get("stored_filename"))
                    
                    # DBレコードの削除
                    repo.db.collection("attachments").document(doc.id).delete()
                    deleted_count += 1
                except Exception as e:
                    logger.error(f"Failed to delete Firestore attachment {doc.id}: {str(e)}")
        
        else:
            logger.warning(f"Unsupported repository type for purge: {type(repo)}")

    finally:
        # 自分で作成したセッションのみ閉じる
        if provided_repo is None and isinstance(repo, repository.SqliteAttachmentRepository):
            repo.db.close()

    if deleted_count > 0:
        logger.info(f"Purged {deleted_count} expired attachments.")
    
    return deleted_count

# --- Orphan attachment reconciliation (SOT-1366) ---
#
# 方針: 「表示中の写真は保持し、ブラウザから削除した写真だけ消す」。
# ブラウザからの削除時には添付の GCS 実体も既に削除されるため、ここでは
# 年齢による一括削除は行わない。DB に対応レコードが無い「孤児オブジェクト」
# （アップロード途中で記録されなかった等）だけを、猶予期間を超えたものに限り
# 削除する。アップロード処理中の競合で表示中写真を消さないための保険として
# 猶予期間（ORPHAN_GRACE_DAYS, 既定1日）より新しい blob は対象外にする。

def get_orphan_grace_days() -> int:
    """環境変数 ORPHAN_GRACE_DAYS から猶予日数を取得する。
    未設定は1日。0以下は孤児削除を無効化する。"""
    try:
        days = int(os.getenv("ORPHAN_GRACE_DAYS", "1"))
        return days if days > 0 else 0
    except ValueError:
        return 1


def _add_referenced_keys(keys: set, object_key: Optional[str], stored_filename: Optional[str]) -> None:
    if object_key:
        keys.add(object_key)
    if stored_filename:
        # object_key が無い古いレコード向けに派生キーも参照集合へ入れる。
        keys.add(stored_filename)
        keys.add(storage.build_object_key(stored_filename))


def _referenced_object_keys(repo: Any) -> set:
    """DB が参照している object key の集合を返す。"""
    keys: set = set()
    if isinstance(repo, repository.SqliteAttachmentRepository):
        for att in repo.db.query(models.Attachment).all():
            _add_referenced_keys(keys, att.object_key, att.stored_filename)
    elif isinstance(repo, repository.FirestoreAttachmentRepository):
        for doc in repo.db.collection("attachments").stream():
            data = doc.to_dict() or {}
            _add_referenced_keys(keys, data.get("object_key"), data.get("stored_filename"))
    else:
        logger.warning(f"Unsupported repository type for reconcile: {type(repo)}")
    return keys


def reconcile_orphan_attachments(repo: Optional[Any] = None, now: Optional[datetime.datetime] = None) -> int:
    """DB に存在しない孤児 GCS オブジェクトのみを削除し、削除件数を返す。
    表示中（DB に存在する）写真は決して削除しない。GCS 以外のバックエンドでは何もしない。"""
    grace_days = get_orphan_grace_days()
    if grace_days <= 0:
        logger.info("Orphan reconciliation is disabled (grace days <= 0).")
        return 0

    backend = storage.get_storage()
    if backend.name != "gcs":
        logger.info("Orphan reconciliation skipped (storage backend is not gcs).")
        return 0

    if now is None:
        now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(days=grace_days)

    provided_repo = repo
    if repo is None:
        repo = repository.get_attachment_repo_standalone()

    deleted_count = 0
    try:
        referenced = _referenced_object_keys(repo)
        for key, created in backend.list_blobs(prefix="uploads/"):
            if not key or key in referenced:
                continue
            # 猶予期間より新しいオブジェクトは、まだ DB 記録前のアップロード中の
            # 可能性があるため対象外にする（表示中写真を消さない保険）。
            if created is not None and created > cutoff:
                continue
            try:
                backend.delete(key)
                deleted_count += 1
                logger.info(f"Deleted orphan attachment blob: {key}")
            except Exception as e:
                logger.error(f"Failed to delete orphan blob {key}: {str(e)}")
    finally:
        if provided_repo is None and isinstance(repo, repository.SqliteAttachmentRepository):
            repo.db.close()

    if deleted_count > 0:
        logger.info(f"Reconciled {deleted_count} orphan attachment(s).")

    return deleted_count


if __name__ == "__main__":
    # シンプルな実行用エントリポイント
    logging.basicConfig(level=logging.INFO)
    print("Starting expired attachments purge...")
    count = purge_expired_attachments()
    print(f"Done. Purged {count} attachments.")
