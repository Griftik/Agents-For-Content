from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import services
from ..deps import get_session, require_api_key
from ..schemas import DecisionIn, DecisionOut

router = APIRouter(prefix="/api/decisions", tags=["решения"], dependencies=[Depends(require_api_key)])


@router.get("/{user_id}", response_model=list[DecisionOut])
def list_decisions(user_id: int, session: Session = Depends(get_session)) -> list[dict]:
    return [services.decision_view(d) for d in services.user_decisions(session, user_id)]


@router.post("", response_model=DecisionOut)
def post_decision(body: DecisionIn, session: Session = Depends(get_session)) -> dict:
    try:
        body.check()
    except ValueError as e:
        raise HTTPException(422, str(e))
    ev = services.get_event(session, body.event)
    if ev is None:
        raise HTTPException(404, "событие не найдено")
    d = services.set_decision(session, body.user_id, ev, body.status, body.reason, body.day, body.rating)
    return services.decision_view(d)


@router.delete("/{user_id}/{event}")
def delete_decision(user_id: int, event: str, session: Session = Depends(get_session)) -> dict:
    ev = services.get_event(session, event)
    if ev is None:
        raise HTTPException(404, "событие не найдено")
    return {"removed": services.remove_decision(session, user_id, ev)}
