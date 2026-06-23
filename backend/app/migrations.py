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
