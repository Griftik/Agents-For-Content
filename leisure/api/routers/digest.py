from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import services
from ..deps import get_session, require_api_key
from ..schemas import DigestOut, PlanOut, ScoredEventOut

router = APIRouter(prefix="/api", tags=["дайджест и план"], dependencies=[Depends(require_api_key)])


@router.get("/digest/{user_id}/preview", response_model=DigestOut)
def digest_preview(user_id: int, today: date | None = None, session: Session = Depends(get_session)) -> dict:
    """Состав дайджеста на ближайший уикенд: 5 слотов + до 2 «на горизонте». Ничего не сохраняет."""
    return services.digest_preview(session, user_id, today or date.today())


@router.get("/digest/{user_id}/all", response_model=list[ScoredEventOut])
def digest_all(user_id: int, today: date | None = None, session: Session = Depends(get_session)) -> list[dict]:
    """Полный список предстоящих событий с баллом совпадения — для веба с фильтрами."""
    return services.scored_events(session, user_id, today or date.today())


@router.get("/plan/{user_id}", response_model=PlanOut)
def plan(user_id: int, today: date | None = None, session: Session = Depends(get_session)) -> dict:
    return services.plan(session, user_id, today or date.today())
