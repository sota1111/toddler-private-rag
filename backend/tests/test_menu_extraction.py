"""menu-calendar 機能のテスト: 発火判定・日付分解・マージ・/menu/calendar API。

Gemini 呼び出しは monkeypatch でスタブ化する（外部ネットワークに出ない）。
"""
import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.routers.auth import get_current_user
from app import database, models, menu_extraction

SQLALCHEMY_DATABASE_URL = "sqlite://"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def override_get_current_user():
    return "test_user"


@pytest.fixture(autouse=True)
def setup_and_teardown(monkeypatch):
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(database, "SessionLocal", TestingSessionLocal)
    monkeypatch.setitem(app.dependency_overrides, get_db, override_get_db)
    monkeypatch.setitem(app.dependency_overrides, get_current_user, override_get_current_user)
    yield
    Base.metadata.drop_all(bind=engine)


client = TestClient(app)


# --- 発火判定 --------------------------------------------------------------------
def test_detect_menu_table_positive():
    text = "8月の献立表\n1 土 カレーうどん 391kcal\n主要食材 体をつくる エネルギーのもとになる"
    assert menu_extraction.detect_menu_table(text) is True


def test_detect_menu_table_rejects_prose_notice():
    # 「給食だより」の文章（表シグナルなし）は分解対象にしない。
    text = "給食だよりです。今月から新しい献立になります。よろしくお願いします。"
    assert menu_extraction.detect_menu_table(text) is False


def test_detect_menu_table_rejects_non_menu():
    assert menu_extraction.detect_menu_table("運動会のお知らせ 5月10日") is False
    assert menu_extraction.detect_menu_table("") is False


def test_enabled_flag(monkeypatch):
    monkeypatch.delenv("MENU_TABLE_EXTRACTION_ENABLED", raising=False)
    assert menu_extraction.menu_extraction_enabled() is False
    monkeypatch.setenv("MENU_TABLE_EXTRACTION_ENABLED", "true")
    assert menu_extraction.menu_extraction_enabled() is True
    monkeypatch.setenv("MENU_TABLE_EXTRACTION_ENABLED", "0")
    assert menu_extraction.menu_extraction_enabled() is False


# --- 年月解決・マージ・変換 -------------------------------------------------------
def test_resolve_year_month_from_title():
    assert menu_extraction._resolve_year_month("8月の献立表", 2026, None) == (2026, 8)
    # タイトルが月を持てば発行月より優先。
    assert menu_extraction._resolve_year_month("8月の献立", 2026, 3) == (2026, 8)


def test_merge_prefers_more_complete():
    best = {}
    sparse = {"date": 5, "lunch": []}
    rich = {
        "date": 5,
        "lunch": ["ごはん", "焼き魚"],
        "main_ingredients": {"red": ["さけ"], "yellow": ["米"], "green": [], "other": []},
        "nutrition": {"over3": {"energy_kcal": 500}},
    }
    menu_extraction._merge(best, [sparse])
    menu_extraction._merge(best, [rich])
    assert best[5]["lunch"] == ["ごはん", "焼き魚"]


def _complete_day(day: int) -> dict:
    return {
        "date": day,
        "weekday": "水",
        "morning_snack": ["牛乳"],
        "lunch": ["ごはん", "焼き魚"],
        "afternoon_snack": ["牛乳"],
        "main_ingredients": {"red": ["さけ"], "yellow": ["米"], "green": ["にんじん"], "other": ["塩"]},
        "nutrition": {
            "under3": {"energy_kcal": 470, "protein_g": 20, "fat_g": 14},
            "over3": {"energy_kcal": 500, "protein_g": 22, "fat_g": 13},
        },
    }


def _tiny_jpeg(tmp_path):
    from PIL import Image

    p = tmp_path / "menu.jpg"
    Image.new("RGB", (400, 600), "white").save(p, format="JPEG")
    return p


def test_extract_menu_by_date_builds_iso(monkeypatch, tmp_path):
    monkeypatch.setattr(
        menu_extraction, "_call_gemini_menu", lambda *a, **k: [_complete_day(1), _complete_day(5)]
    )
    path = _tiny_jpeg(tmp_path)
    result = menu_extraction.extract_menu_by_date(path, "image/jpeg", "8月の献立表", issue_year=2026)
    assert result is not None
    assert result["month"] == "2026-08"
    dates = [d["date"] for d in result["days"]]
    assert dates == ["2026-08-01", "2026-08-05"]
    assert result["days"][1]["lunch"] == ["ごはん", "焼き魚"]


def test_extract_menu_returns_none_when_no_rows(monkeypatch, tmp_path):
    monkeypatch.setattr(menu_extraction, "_call_gemini_menu", lambda *a, **k: [])
    path = _tiny_jpeg(tmp_path)
    assert menu_extraction.extract_menu_by_date(path, "image/jpeg", "8月の献立表", issue_year=2026) is None


def test_parse_rows_handles_fenced_json():
    rows = menu_extraction._parse_rows('```json\n[{"date": 3}]\n```')
    assert rows == [{"date": 3}]


# --- /menu/calendar API ----------------------------------------------------------
def _seed_menu_info(menu_json, owner_id="test_user"):
    db = TestingSessionLocal()
    try:
        info = models.NurseryInfo(
            owner_id=owner_id,
            title="8月の献立表",
            info_type="給食",
            content="",
            registration_state="registered",
            menu_json=menu_json,
        )
        db.add(info)
        db.commit()
        db.refresh(info)
        return info.id
    finally:
        db.close()


def test_menu_calendar_returns_month_days():
    _seed_menu_info(
        {
            "month": "2026-08",
            "days": [
                {"date": "2026-08-05", "lunch": ["ごはん"], "main_ingredients": {"red": ["さけ"], "yellow": [], "green": [], "other": []}},
                {"date": "2026-09-01", "lunch": ["カレー"]},  # 別月は返らない
            ],
        }
    )
    resp = client.get("/api/menu/calendar", params={"year": 2026, "month": 8})
    assert resp.status_code == 200
    body = resp.json()
    assert body["year"] == 2026 and body["month"] == 8
    assert set(body["days"].keys()) == {"2026-08-05"}
    assert body["days"]["2026-08-05"]["lunch"] == ["ごはん"]


def test_menu_calendar_empty_when_no_menu():
    resp = client.get("/api/menu/calendar", params={"year": 2026, "month": 8})
    assert resp.status_code == 200
    assert resp.json()["days"] == {}


def test_menu_calendar_owner_isolation():
    _seed_menu_info(
        {"month": "2026-08", "days": [{"date": "2026-08-05", "lunch": ["ごはん"]}]},
        owner_id="someone_else",
    )
    resp = client.get("/api/menu/calendar", params={"year": 2026, "month": 8})
    assert resp.status_code == 200
    assert resp.json()["days"] == {}
