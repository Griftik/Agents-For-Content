"""Гостевая сессия (docs/PIVOT-PWA.md §2.1): сервер выдаёт user_id, профиль появится первым PUT /api/profile с согласием."""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..deps import get_session, require_api_key
from ..schemas import SessionOut

router = APIRouter(prefix="/api", tags=["сессия"], dependencies=[Depends(require_api_key)])


@router.post("/session", response_model=SessionOut)
def create_session(session: Session = Depends(get_session)) -> dict:
    """Новый user_id из последовательности (с 10^12, не Telegram id). Ничего о человеке не сохраняется: ни профиля, ни cookie —
    подписанную cookie на 180 дней ставит сервер веба."""
    uid = session.execute(text("select nextval('guest_user_id_seq')")).scalar_one()
    session.commit()
    return {"user_id": int(uid)}
