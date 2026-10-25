"""Несколько профилей на аккаунт (docs/PIVOT-PWA.md, версия 2): «я», «мама», «ребёнок». Аккаунт — это сессия веба; основной
профиль («я») имеет user_id = id аккаунта, дополнительные — свои user_id из той же последовательности. Со всеми этими id работают
/api/profile/{id}, /api/decisions, /api/plan, /api/feed, /api/invites; активный профиль выбирает веб и передаёт его id."""
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .. import services
from ..deps import get_session, require_api_key, resolve_user_id
from ..schemas import ProfileCreateIn, ProfilesOut

router = APIRouter(prefix="/api/profiles", tags=["профили аккаунта"], dependencies=[Depends(require_api_key)])

MAX_PROFILES = 6


def _account(session: Session, uid: int):
    p = services.get_profile(session, uid)
    if p is None:
        raise HTTPException(404, "профиль не найден")
    return p.account


def _view(session: Session, account) -> dict:
    return {"account_id": account.id, "email": account.email,
            "profiles": [{"user_id": p.user_id, "name": p.name, "kind": p.kind, "onboarded": p.onboarded_at is not None,
                          "is_main": p.user_id == account.id} for p in services.account_profiles(session, account.id)]}


@router.get("", response_model=ProfilesOut)
def list_profiles(user_id: int | None = None, x_user_id: str | None = Header(default=None), session: Session = Depends(get_session)) -> dict:
    """Все профили аккаунта по id любого из них."""
    return _view(session, _account(session, resolve_user_id(None, x_user_id, user_id)))


@router.post("", response_model=ProfilesOut)
def create_profile(body: ProfileCreateIn, x_user_id: str | None = Header(default=None), session: Session = Depends(get_session)) -> dict:
    """Добавить профиль (name, kind: self/parent/child/other). Нужно согласие владельца (409 consent_required); не больше шести.
    Новый профиль наследует согласие, онбординг проходит отдельно (свои ценности, интересы, бюджет, решения)."""
    uid = resolve_user_id(body.user_id, x_user_id)
    owner = services.get_profile(session, uid)
    if owner is None:
        raise HTTPException(404, "профиль не найден")
    if owner.consent_at is None:
        raise HTTPException(409, "consent_required")
    if len(services.account_profiles(session, owner.account_id)) >= MAX_PROFILES:
        raise HTTPException(409, f"не больше {MAX_PROFILES} профилей в аккаунте")
    services.create_profile(session, owner.account_id, body.name, body.kind)
    return _view(session, owner.account)


@router.delete("/{profile_id}", response_model=ProfilesOut)
def delete_profile(profile_id: int, user_id: int | None = None, x_user_id: str | None = Header(default=None),
                   session: Session = Depends(get_session)) -> dict:
    """Убрать дополнительный профиль вместе с его решениями. Основной («я») так не удаляется: весь аккаунт стирает
    DELETE /api/profile/{id}."""
    acc = _account(session, resolve_user_id(None, x_user_id, user_id))
    target = services.get_profile(session, profile_id)
    if target is None or target.account_id != acc.id:
        raise HTTPException(404, "профиль не найден")
    if target.user_id == acc.id:
        raise HTTPException(400, "основной профиль удаляется вместе с аккаунтом: DELETE /api/profile/{id}")
    services.delete_profile(session, profile_id)
    return _view(session, acc)
