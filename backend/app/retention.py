import os
import datetime
import logging
from typing import Optional, Any
from . import models, storage, repository, database

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

if __name__ == "__main__":
    # シンプルな実行用エントリポイント
    logging.basicConfig(level=logging.INFO)
    print("Starting expired attachments purge...")
    count = purge_expired_attachments()
    print(f"Done. Purged {count} attachments.")
