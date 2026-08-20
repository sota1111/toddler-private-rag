from sqlalchemy.engine import Engine

from . import models
from .identity import DEFAULT_OWNER_ID


def _nursery_info_column_sql(column) -> str:
    if column.name == "registration_state":
        return "registration_state VARCHAR(20) NOT NULL DEFAULT 'registered'"

    column_type = column.type.compile()
    parts = [column.name, column_type]

    if not column.nullable and column.server_default is not None:
        parts.append("NOT NULL")

    return " ".join(parts)


def ensure_sqlite_schema(engine: Engine) -> None:
    """Patch existing SQLite tables that predate model columns."""
    with engine.begin() as conn:
        table_exists = conn.exec_driver_sql(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'nursery_info'"
        ).scalar()
        if not table_exists:
            return

        existing_columns = {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(nursery_info)")
        }

        for column in models.NurseryInfo.__table__.columns:
            if column.primary_key or column.name in existing_columns:
                continue
            conn.exec_driver_sql(
                f"ALTER TABLE nursery_info ADD COLUMN {_nursery_info_column_sql(column)}"
            )

        # SOT-1377: patch the attachments table for columns added after creation
        # (e.g. `language`, used to carry the request language through async
        # GCS-finalize OCR). Only additive, nullable columns are handled here.
        attachments_exists = conn.exec_driver_sql(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'attachments'"
        ).scalar()
        if attachments_exists:
            att_columns = {
                row[1] for row in conn.exec_driver_sql("PRAGMA table_info(attachments)")
            }
            for column in models.Attachment.__table__.columns:
                if column.primary_key or column.name in att_columns:
                    continue
                conn.exec_driver_sql(
                    f"ALTER TABLE attachments ADD COLUMN {column.name} {column.type.compile()}"
                )

        # SOT-1431: children テーブルも additive/nullable カラム(owner_id)を追記する。
        children_exists = conn.exec_driver_sql(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'children'"
        ).scalar()
        if children_exists:
            child_columns = {
                row[1] for row in conn.exec_driver_sql("PRAGMA table_info(children)")
            }
            for column in models.Child.__table__.columns:
                if column.primary_key or column.name in child_columns:
                    continue
                conn.exec_driver_sql(
                    f"ALTER TABLE children ADD COLUMN {column.name} {column.type.compile()}"
                )

        # SOT-2729: care_profile は新規テーブルなので通常は create_all で作成されるが、
        # 既存デプロイに後からカラムを足す場合に備えて additive/nullable カラムを追記する
        # (children/attachments と同方式)。既存 children 行には一切触れない(非破壊)。
        care_profile_exists = conn.exec_driver_sql(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'care_profile'"
        ).scalar()
        if care_profile_exists:
            cp_columns = {
                row[1] for row in conn.exec_driver_sql("PRAGMA table_info(care_profile)")
            }
            for column in models.CareProfile.__table__.columns:
                if column.primary_key or column.name in cp_columns:
                    continue
                conn.exec_driver_sql(
                    f"ALTER TABLE care_profile ADD COLUMN {column.name} {column.type.compile()}"
                )

        # SOT-2734: attention_item は新規テーブルなので通常は create_all で作成されるが、
        # 既存デプロイに後からカラムを足す場合に備えて additive/nullable カラムを追記する
        # (care_profile と同方式)。
        attention_item_exists = conn.exec_driver_sql(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'attention_item'"
        ).scalar()
        if attention_item_exists:
            ai_columns = {
                row[1] for row in conn.exec_driver_sql("PRAGMA table_info(attention_item)")
            }
            for column in models.AttentionItem.__table__.columns:
                if column.primary_key or column.name in ai_columns:
                    continue
                conn.exec_driver_sql(
                    f"ALTER TABLE attention_item ADD COLUMN {column.name} {column.type.compile()}"
                )

        # SOT-1431: 既存(owner 未設定)データを現行の主ユーザー(既定 owner)に一括割当する。
        # 非破壊(NULL 行のみ更新)。マルチテナント分離導入前のデータが主ユーザーのものとして残る。
        conn.exec_driver_sql(
            "UPDATE nursery_info SET owner_id = ? WHERE owner_id IS NULL",
            (DEFAULT_OWNER_ID,),
        )
        if children_exists:
            conn.exec_driver_sql(
                "UPDATE children SET owner_id = ? WHERE owner_id IS NULL",
                (DEFAULT_OWNER_ID,),
            )
