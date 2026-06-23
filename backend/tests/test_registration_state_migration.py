from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import database, models
from app.database import Base, get_db
from app.main import app
from app.migrations import ensure_sqlite_schema
from app.routers.auth import get_current_user


def _create_old_nursery_info_table(engine):
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE nursery_info (
                id INTEGER NOT NULL PRIMARY KEY,
                title VARCHAR(200) NOT NULL,
                info_type VARCHAR(50) NOT NULL,
                content TEXT NOT NULL,
                date DATE,
                event_date DATE,
                due_date DATE,
                items TEXT,
                status VARCHAR(20),
                priority VARCHAR(10),
                tags TEXT,
                memo TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def _column_names(engine):
    with engine.begin() as conn:
        return [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(nursery_info)")]


def test_registration_state_migration_allows_draft_create_on_old_schema(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'old.db'}",
        connect_args={"check_same_thread": False},
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    _create_old_nursery_info_table(engine)
    Base.metadata.create_all(bind=engine)
    ensure_sqlite_schema(engine)

    def override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(database, "SessionLocal", testing_session_local)
    monkeypatch.setitem(app.dependency_overrides, get_db, override_get_db)
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: "test_user")

    client = TestClient(app)
    response = client.post(
        "/api/info/",
        json={
            "title": "draft from old schema",
            "info_type": "お知らせ",
            "content": "photo draft",
            "registration_state": "draft",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["registration_state"] == "draft"

    with testing_session_local() as db:
        row = db.execute(
            models.NurseryInfo.__table__.select().where(
                models.NurseryInfo.id == body["id"]
            )
        ).one()
        assert row._mapping["registration_state"] == "draft"


def test_registration_state_migration_is_idempotent(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'idempotent.db'}",
        connect_args={"check_same_thread": False},
    )

    _create_old_nursery_info_table(engine)
    Base.metadata.create_all(bind=engine)

    ensure_sqlite_schema(engine)
    columns_after_first_run = _column_names(engine)

    ensure_sqlite_schema(engine)
    columns_after_second_run = _column_names(engine)

    assert columns_after_first_run == columns_after_second_run
    assert columns_after_second_run.count("registration_state") == 1
