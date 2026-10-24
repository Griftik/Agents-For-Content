"""Приглашения друзей и метрики роста: контракт docs/GROWTH.md §6. Приглашают и принимают в Mini App; бот только доставляет
уведомления, план и «Как прошло?». user_id приходит из сессии Mini App (initData проверяет веб): в теле или заголовком X-User-Id."""
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .. import invites as inv_service
from .. import services
from ..deps import get_session, require_api_key
from ..schemas import (InviteAcceptIn, InviteAcceptOut, InviteCreatedOut, InviteCreateIn, InviteOpenIn, InviteOut)

router = APIRouter(prefix="/api", tags=["приглашения и рост"], dependencies=[Depends(require_api_key)])


def _uid(body_uid: int | None, header_uid: str | None) -> int:
    if body_uid is not None:
        return body_uid
    if header_uid and header_uid.lstrip("-").isdigit():
        return int(header_uid)
    raise HTTPException(422, "нужен user_id (в теле или заголовком X-User-Id)")


def _invite(session: Session, code: str):
    inv = inv_service.get_invite(session, code)
    if inv is None:
        raise HTTPException(404, "приглашение не найдено (или пригласивший удалил профиль)")
    return inv


@router.post("/invites", response_model=InviteCreatedOut)
def create_invite(body: InviteCreateIn, x_user_id: str | None = Header(default=None), session: Session = Depends(get_session)) -> dict:
    """Создать приглашение (одно на человека, событие и день: повтор возвращает тот же код) или ref-ссылку (kind=ref)."""
    uid = _uid(body.user_id, x_user_id)
    ev = None
    if body.kind == "event":
        if not body.event_slug:
            raise HTTPException(422, "для приглашения на событие нужен event_slug")
        ev = services.get_event(session, body.event_slug)
        if ev is None:
            raise HTTPException(404, "событие не найдено")
        if ev.status != "published":
            raise HTTPException(410, "событие снято с публикации")
    try:
        return inv_service.create_for_api(session, uid, ev, body.day, body.kind)
    except services.ProfileMissing:
        raise HTTPException(404, "профиль не найден")


@router.get("/invites/{code}", response_model=InviteOut)
def get_invite(code: str, user_id: int | None = None, session: Session = Depends(get_session)) -> dict:
    """Приглашение для страницы события: карточка, день, имя пригласившего (если не скрыто), статус, число принявших."""
    return inv_service.view(session, _invite(session, code), user_id)


@router.post("/invites/{code}/open", response_model=InviteOut)
def open_invite(code: str, body: InviteOpenIn, x_user_id: str | None = Header(default=None),
                session: Session = Depends(get_session)) -> dict:
    """Первый вход по ссылке в Mini App (inv_ или ref_): учёт открытия, профиль-заготовка; ref-ссылка новому человеку ставит
    source=ref и referred_by. Повтор безвреден."""
    uid = _uid(body.user_id, x_user_id)
    inv = _invite(session, code)
    try:
        inv_service.web_open(session, inv, uid, body.name, body.username)
    except inv_service.OwnInvite:
        pass                                    # открыл своё приглашение — не считаем
    return inv_service.view(session, inv, uid)


@router.post("/invites/{code}/accept", response_model=InviteAcceptOut)
def accept_invite(code: str, body: InviteAcceptIn, x_user_id: str | None = Header(default=None),
                  session: Session = Depends(get_session)) -> dict:
    """«Иду» (going), «Может быть» (maybe) или declined («Другие выходные под меня»: запись без решения, согласие не нужно; без согласия профиль не создаётся, отказ пишется в growth_events).
    Первое касание без профиля: consent=true, иначе 409 consent_required.
    410 — событие прошло, снято с публикации или удалено; 400 — своё приглашение. Повтор идемпотентен."""
    uid = _uid(body.user_id, x_user_id)
    inv = _invite(session, code)
    try:
        d, _ = inv_service.web_accept(session, inv, uid, body.status, body.name, body.username, body.consent)
    except inv_service.ConsentRequired:
        raise HTTPException(409, "consent_required")
    except inv_service.InviteUnavailable as e:
        raise HTTPException(410, e.status)
    except inv_service.OwnInvite:
        raise HTTPException(400, "своё приглашение принять нельзя")
    except ValueError as e:
        raise HTTPException(400, str(e))
    if body.status == "going" and d is not None:
        inv_service.notify_inviter(session, inv, uid)   # один раз: повтор и «может» → «иду» не дублируют уведомление
    return inv_service.accept_result(session, inv, uid, d)


@router.get("/metrics/growth")
def growth_metrics(since: datetime | None = None, session: Session = Depends(get_session)) -> dict:
    """Все строки таблицы §4 одним запросом: {since, metrics: {имя: {value, numerator, denominator, target}}, counts}."""
    return inv_service.growth_metrics(session, since)
