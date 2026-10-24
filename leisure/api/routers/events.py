from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from leisure import settings
from leisure.core.timeutil import weekend_days, weekend_iso

from .. import services
from ..deps import get_session
from ..schemas import EventOut

router = APIRouter(prefix="/api/events", tags=["события"])


@router.get("", response_model=list[EventOut])
def list_events(city: str = settings.DEFAULT_CITY, today: date | None = None, day: str | None = None,
                category: str | None = None, free: bool = False, horizon: bool | None = None,
                session: Session = Depends(get_session)) -> list[dict]:
    today = today or date.today()
    weekend = weekend_iso(today)
    out = []
    for ev in services.upcoming_events(session, city, today):
        v = services.event_view(ev)
        if day and day not in v["dates"]:
            continue
        if category and v["category"] != category:
            continue
        if free and not v["free"]:
            continue
        if horizon is True and weekend_days(v, weekend):
            continue
        if horizon is False and not weekend_days(v, weekend):
            continue
        out.append(v)
    return out


@router.get("/{key}", response_model=EventOut)
def get_event(key: str, session: Session = Depends(get_session)) -> dict:
    ev = services.get_event(session, key)
    if ev is None or ev.status != "published":
        raise HTTPException(404, "событие не найдено")
    return services.event_view(ev.as_core())


@router.get("/{key}/ics")
def event_ics(key: str, day: str | None = Query(default=None), session: Session = Depends(get_session)) -> Response:
    ev = services.get_event(session, key)
    if ev is None or ev.status != "published":
        raise HTTPException(404, "событие не найдено")
    body = services.ics_for(ev.as_core(), day)
    return Response(body, media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{ev.slug}.ics"'})
