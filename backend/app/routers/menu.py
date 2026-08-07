"""献立カレンダー API（menu-calendar 機能）。

登録写真レコード（nursery_info）の ``menu_json`` を owner スコープで集約し、指定年月の
献立を ISO 日付キーで返す。献立は予定/タスク（event_date 付き）を作らないため、この
エンドポイントだけが献立データの参照経路になる（タスク/予定一覧には出ない）。
"""
import logging
from fastapi import APIRouter, Depends, Query

from .. import schemas
from ..repository import InfoRepository, get_info_repository
from ..routers.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["menu"])


def _coerce_day(raw: dict) -> schemas.MenuDay | None:
    """保存された1日分 dict を MenuDay へ寛容に変換する（壊れた要素は None）。"""
    if not isinstance(raw, dict) or not raw.get("date"):
        return None
    try:
        return schemas.MenuDay.model_validate(raw)
    except Exception:  # noqa: BLE001 - 壊れた1件で月全体を落とさない
        return None


@router.get("/menu/calendar", response_model=schemas.MenuCalendarResponse)
def get_menu_calendar(
    year: int = Query(..., ge=1900, le=2200),
    month: int = Query(..., ge=1, le=12),
    repo: InfoRepository = Depends(get_info_repository),
    current_user: str = Depends(get_current_user),
):
    """指定年月の献立を ISO 日付キーで返す。該当が無ければ空 ``days``。"""
    prefix = f"{year:04d}-{month:02d}-"
    days: dict[str, schemas.MenuDay] = {}
    # owner スコープ済みの登録一覧から menu_json を持つレコードだけ拾う。
    for info in repo.list(include_attachments=False):
        menu = getattr(info, "menu_json", None)
        if not isinstance(menu, dict):
            continue
        for raw in menu.get("days") or []:
            day = _coerce_day(raw)
            if day is None or not day.date.startswith(prefix):
                continue
            # 同じ日付が複数レコードに跨る場合は、より情報量の多い方を残す。
            existing = days.get(day.date)
            if existing is None or _richness(day) >= _richness(existing):
                days[day.date] = day
    return schemas.MenuCalendarResponse(year=year, month=month, days=days)


def _richness(day: schemas.MenuDay) -> int:
    mi = day.main_ingredients
    return (
        len(day.lunch) * 2
        + len(day.morning_snack)
        + len(day.afternoon_snack)
        + len(mi.red) + len(mi.yellow) + len(mi.green) + len(mi.other)
    )
