"""Живая лента (docs/PIVOT-PWA.md, версия 2): GET /api/feed — события на день или период, ранжированные под профиль."""
from datetime import date, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from leisure.core.feed import SEGMENTS

from .. import services
from ..deps import get_session, require_api_key, resolve_user_id
from ..schemas import FeedOut

router = APIRouter(prefix="/api", tags=["лента"], dependencies=[Depends(require_api_key)])


@router.get("/feed", response_model=FeedOut)
def feed(user_id: int | None = None, date_: str = Query(default="today", alias="date"), segment: str = "all",
         limit: int | None = None, today: date | None = None, now: datetime | None = None, include_missed: bool = False,
         x_user_id: str | None = Header(default=None), session: Session = Depends(get_session)) -> dict:
    """date: today | tomorrow | week | YYYY-MM-DD; segment: leisure | business | all. Для сегодня исключается всё, что начинается
    раньше now + params.travel_minutes профиля (по умолчанию 40); include_missed=true добавляет такие события в конец с
    can_make_it=false. today и now (местное время без пояса) — для тестов и симулятора; без них берётся время профиля.
    Профиль должен быть настроен (онбординг), иначе 409 not_onboarded."""
    uid = resolve_user_id(None, x_user_id, user_id)
    p = services.get_profile(session, uid)
    if p is None:
        raise HTTPException(404, "профиль не найден")
    if p.onboarded_at is None:
        raise HTTPException(409, "not_onboarded")
    if segment not in SEGMENTS:
        raise HTTPException(422, f"segment: одно из {', '.join(SEGMENTS)}")
    try:
        return services.feed(session, p, date_, segment, limit, today=today, now=now, include_missed=include_missed)
    except ValueError as e:
        raise HTTPException(422, str(e))
