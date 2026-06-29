from sqlalchemy.engine import Engine

from . import models


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
