from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import services
from ..deps import get_session, require_api_key
from ..schemas import ProfileIn, ProfileOut

router = APIRouter(prefix="/api/profile", tags=["профиль"], dependencies=[Depends(require_api_key)])


@router.get("/{user_id}", response_model=ProfileOut)
def get_profile(user_id: int, session: Session = Depends(get_session)) -> dict:
    p = services.get_profile(session, user_id)
    if p is None:
        raise HTTPException(404, "профиль не найден — создаётся первым PUT с согласием")
    return services.profile_view(p, services.user_decisions(session, user_id))


@router.put("/{user_id}", response_model=ProfileOut)
def put_profile(user_id: int, body: ProfileIn, session: Session = Depends(get_session)) -> dict:
    p = services.get_or_create_profile(session, user_id)   # профиль создаёт веб (гостевая сессия, первый PUT)
    had_consent = p.consent_at is not None
    p = services.update_profile(session, p, body.model_dump(exclude_none=True))
    from .. import invites
    if body.ref_code:
        invites.apply_ref_code(session, p, body.ref_code)
    if body.consent and not had_consent:
        invites.mark_ref_joined(session, p.user_id)     # пришёл по ссылке-рекомендации и дал согласие: считаем принятым
    return services.profile_view(p, services.user_decisions(session, user_id))


@router.delete("/{user_id}")
def delete_profile(user_id: int, session: Session = Depends(get_session)) -> dict:
    """Отзыв согласия (152-ФЗ): основной профиль — удаляется весь аккаунт (все профили, решения, журнал, токены входа);
    дополнительный — только он."""
    return {"removed": services.delete_profile(session, user_id)}
