from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import services
from ..deps import get_session, require_api_key
from ..schemas import DecisionIn, DecisionOut, DecisionPostOut

router = APIRouter(prefix="/api/decisions", tags=["решения"], dependencies=[Depends(require_api_key)])


@router.get("/{user_id}", response_model=list[DecisionOut])
def list_decisions(user_id: int, session: Session = Depends(get_session)) -> list[dict]:
    return [services.decision_view(d) for d in services.user_decisions(session, user_id)]


@router.post("", response_model=DecisionPostOut)
def post_decision(body: DecisionIn, session: Session = Depends(get_session)) -> dict:
    """Записать решение или оценку. В ответе при оценке: 4–5 — ref_ask (экран рекомендации, не чаще раза в 14 дней; показ
    пишется в журнал роста), 1–2 — ask_reason (спросить, что было не так: причина уходит повторным POST с reason)."""
    ev = services.get_event(session, body.event)
    if ev is None:
        raise HTTPException(404, "событие не найдено")
    try:
        d = services.set_decision(session, body.user_id, ev, body.status, body.reason, body.day, body.rating)
    except services.ProfileMissing:
        raise HTTPException(404, "профиль не найден — решения пишутся только в существующий профиль")
    except ValueError as e:
        raise HTTPException(400, str(e))
    out = services.decision_view(d)
    if body.rating is not None:
        from .. import invites
        if body.rating >= 4 and invites.ref_ask_due(session, body.user_id):
            ref = invites.create_for_api(session, body.user_id, None, None, "ref")
            invites.log_growth(session, body.user_id, "ref_ask")
            out["ref_ask"] = {"url": ref["url"], "share_text": ref["share_text"]}
        elif body.rating <= 2:
            out["ask_reason"] = True
    return out


@router.delete("/{user_id}/{event}")
def delete_decision(user_id: int, event: str, session: Session = Depends(get_session)) -> dict:
    ev = services.get_event(session, event)
    if ev is None:
        raise HTTPException(404, "событие не найдено")
    return {"removed": services.remove_decision(session, user_id, ev)}
