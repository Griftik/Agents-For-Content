"""Приглашения друзей и рекомендация сервиса (docs/GROWTH.md): коды, принятие, «вдвоём с», метрики роста."""
from __future__ import annotations

import os
import secrets
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from leisure import settings
from leisure.db.models import Decision, Event, GrowthEvent, Invite, InviteAccept, Profile

from . import services

CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"   # без 0 1 I L O U: код читается и диктуется без путаницы
CODE_LEN = 8
HIDDEN_NAME = "другом"        # как называем человека, скрывшего имя («вдвоём с другом»)
REF_ASK_EVERY = timedelta(days=14)


def new_code(session: Session) -> str:
    while True:
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))
        if session.scalar(select(Invite.id).where(Invite.code == code)) is None:
            return code


def miniapp_url(code: str, kind: str = "event") -> str | None:
    """Ссылка в Mini App: https://t.me/<бот>/<app>?startapp=inv_<код> (рекомендация — ref_<код>). None, пока не заданы
    NEXT_PUBLIC_BOT_USERNAME и MINIAPP_SHORT_NAME."""
    if not settings.BOT_USERNAME or not settings.MINIAPP_SHORT_NAME:
        return None
    return f"https://t.me/{settings.BOT_USERNAME}/{settings.MINIAPP_SHORT_NAME}?startapp={'inv' if kind == 'event' else 'ref'}_{code}"


def web_url(inv: Invite) -> str:
    """Страница в вебе: /e/<slug>?inv=<код> (для рекомендации — главная с ?ref=<код>)."""
    base = settings.WEB_BASE_URL.rstrip("/")
    return f"{base}/e/{inv.event_slug}?inv={inv.code}" if inv.kind == "event" and inv.event_slug else f"{base}/?ref={inv.code}"


def page_link(event_slug: str, code: str) -> str:
    return f"{settings.WEB_BASE_URL.rstrip('/')}/e/{event_slug}?inv={code}"


def get_invite(session: Session, code: str) -> Invite | None:
    code = (code or "").strip()
    if not (0 < len(code) <= CODE_LEN):
        return None
    return session.scalar(select(Invite).where(Invite.code == code))


def create_invite(session: Session, inviter_id: int, ev: Event | None, day: date | None, kind: str = "event") -> Invite:
    """Приглашение на событие (одно на человека, событие и день — повторное нажатие даёт тот же код) или ссылка-рекомендация (одна на человека)."""
    if services.get_profile(session, inviter_id) is None:
        raise services.ProfileMissing(inviter_id)
    q = select(Invite).where(Invite.inviter_id == inviter_id, Invite.kind == kind)
    if kind == "event":
        if ev is None:
            raise ValueError("для приглашения на событие нужно событие")
        q = q.where(Invite.event_id == ev.id, Invite.day == day) if day else q.where(Invite.event_id == ev.id, Invite.day.is_(None))
    inv = session.scalar(q.order_by(Invite.id).limit(1))
    if inv is None:
        inv = Invite(code=new_code(session), inviter_id=inviter_id, kind=kind, event_id=ev.id if ev else None,
                     event_slug=ev.slug if ev else "", day=day)
        session.add(inv)
        session.commit()
    return inv


def display_name(p: Profile | None) -> str | None:
    """Имя для друзей: первое слово имени из Telegram, если человек не скрыл его; иначе None."""
    if p is None or not p.show_name or not (p.name or "").strip():
        return None
    return p.name.split()[0]


def status_of(session: Session, inv: Invite, today: date) -> str:
    """unpublished (событие снято с публикации или удалено) | past (прошло) | gone (пригласивший удалил профиль, событие доступно) |
    active. Событие важнее пригласившего: нельзя звать на то, чего нет или что уже прошло."""
    ev = inv.event
    if ev is None or ev.status != "published":
        return "unpublished"
    last = inv.day or (max(ev.dates) if ev.dates else None)
    if last is not None and last < today:
        return "past"
    return "gone" if inv.inviter_id is None else "active"


def open_invite(session: Session, inv: Invite, user_id: int) -> tuple[InviteAccept, bool]:
    """Учесть открытие приглашения человеком (профиль уже создан). Возвращает (запись, первое_ли_открытие)."""
    acc = session.scalar(select(InviteAccept).where(InviteAccept.invite_id == inv.id, InviteAccept.user_id == user_id))
    if acc is not None:
        return acc, False
    p = services.get_profile(session, user_id)
    acc = InviteAccept(invite_id=inv.id, user_id=user_id, status="opened", was_new=p is None or p.consent_at is None)
    session.add(acc)
    inv.opened += 1
    session.commit()
    return acc, True


def adopt_new_profile(session: Session, p: Profile, inv: Invite) -> None:
    """Новый человек пришёл по приглашению: источник и пригласивший (только пока профиль не настроен и источник не задан)."""
    if p.onboarded_at is None and p.source == "organic" and p.referred_by is None and inv.inviter_id != p.user_id:
        p.source = "invite" if inv.kind == "event" else "ref"
        p.referred_by = inv.inviter_id
        session.commit()


def accept_invite(session: Session, inv: Invite, user_id: int, status: str) -> Decision:
    """«Иду» или «может быть» по приглашению: решение (с invite_id и днём приглашения) и учёт принятия."""
    ev = inv.event
    if ev is None:
        raise LookupError("событие приглашения снято")
    acc, _ = open_invite(session, inv, user_id)
    decision_status = {"going": "иду", "maybe": "может"}[status]
    d = services.set_decision(session, user_id, ev, decision_status, day=inv.day, invite_id=inv.id)
    if acc.accepted_at is None:
        acc.accepted_at = datetime.now(timezone.utc)
        inv.accepted += 1
    acc.status = status
    session.commit()
    return d


def mark_ref_joined(session: Session, user_id: int) -> None:
    """Человек, пришедший по ссылке-рекомендации, дал согласие: считаем принятым."""
    rows = session.scalars(select(InviteAccept).join(Invite).where(InviteAccept.user_id == user_id, Invite.kind == "ref",
                                                                   InviteAccept.accepted_at.is_(None))).all()
    for acc in rows:
        acc.accepted_at, acc.status = datetime.now(timezone.utc), "going"
        acc.invite.accepted += 1
    if rows:
        session.commit()


def companion_names(session: Session, user_id: int, d: Decision) -> list[str]:
    """С кем человек идёт на это событие по приглашениям: пригласивший (если решение пришло по приглашению) и друзья, принявшие
    его приглашение и ещё идущие. Имя скрыто — «другом»."""
    if d.status != "иду":
        return []
    names: list[str] = []
    if d.invite_id:
        inv = session.get(Invite, d.invite_id)
        if inv is not None and inv.inviter_id is not None and inv.inviter_id != user_id:
            names.append(display_name(session.get(Profile, inv.inviter_id)) or HIDDEN_NAME)
    if d.event_id:
        rows = session.execute(
            select(InviteAccept.user_id).join(Invite).join(Decision, (Decision.user_id == InviteAccept.user_id) & (Decision.event_id == Invite.event_id))
            .where(Invite.inviter_id == user_id, Invite.event_id == d.event_id, Invite.kind == "event", InviteAccept.status == "going",
                   Decision.status == "иду").order_by(InviteAccept.accepted_at)).all()
        for (uid,) in rows:
            names.append(display_name(session.get(Profile, uid)) or HIDDEN_NAME)
    return list(dict.fromkeys(names))


# ─── момент рекомендации ───
def log_growth(session: Session, user_id: int, kind: str) -> None:
    session.add(GrowthEvent(user_id=user_id, kind=kind))
    session.commit()


def ref_ask_due(session: Session, user_id: int, now: datetime | None = None) -> bool:
    """Просить рекомендацию не чаще раза в 14 дней."""
    last = session.scalar(select(func.max(GrowthEvent.created_at)).where(GrowthEvent.user_id == user_id, GrowthEvent.kind == "ref_ask"))
    return last is None or (now or datetime.now(timezone.utc)) - last >= REF_ASK_EVERY


# ─── метрики роста (docs/GROWTH.md §4) ───
def _ratio(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def growth_metrics(session: Session, since: datetime | None = None) -> dict:
    """Метрики таблицы §4 одним словарём: {имя: {value, numerator, denominator, target}} + сырые счётчики."""
    since = since or datetime(1970, 1, 1, tzinfo=timezone.utc)
    c = lambda q: int(session.scalar(q) or 0)   # noqa: E731
    going = c(select(func.count()).select_from(Decision).where(Decision.status == "иду", Decision.created_at >= since))
    invites_made = c(select(func.count()).select_from(Invite).where(Invite.kind == "event", Invite.created_at >= since))
    opened = c(select(func.count()).select_from(InviteAccept).join(Invite).where(Invite.kind == "event", InviteAccept.opened_at >= since))
    accepted = c(select(func.count()).select_from(InviteAccept).join(Invite).where(
        Invite.kind == "event", InviteAccept.opened_at >= since, InviteAccept.status.in_(("going", "maybe"))))
    new_opened = c(select(func.count()).select_from(InviteAccept).join(Invite).where(
        Invite.kind == "event", InviteAccept.opened_at >= since, InviteAccept.was_new.is_(True)))
    new_activated = c(select(func.count()).select_from(InviteAccept).join(Invite).where(
        Invite.kind == "event", InviteAccept.opened_at >= since, InviteAccept.was_new.is_(True), InviteAccept.accepted_at.is_not(None)))
    invited_profiles = c(select(func.count()).select_from(Profile).where(Profile.source == "invite", Profile.created_at >= since))
    invited_onboarded = c(select(func.count()).select_from(Profile).where(
        Profile.source == "invite", Profile.created_at >= since, Profile.onboarded_at.is_not(None),
        Profile.onboarded_at <= Profile.created_at + timedelta(days=14)))
    new_total = c(select(func.count()).select_from(Profile).where(Profile.created_at >= since, Profile.consent_at.is_not(None)))
    new_friends = c(select(func.count()).select_from(Profile).where(Profile.created_at >= since, Profile.consent_at.is_not(None),
                                                                    Profile.source.in_(("invite", "ref", "share"))))
    active = c(select(func.count(func.distinct(Decision.user_id))).where(Decision.updated_at >= since))
    rated = c(select(func.count()).select_from(Decision).where(Decision.rating.is_not(None), Decision.updated_at >= since))
    rated_good = c(select(func.count()).select_from(Decision).where(Decision.rating >= 4, Decision.updated_at >= since))
    ref_asks = c(select(func.count()).select_from(GrowthEvent).where(GrowthEvent.kind == "ref_ask", GrowthEvent.created_at >= since))
    # «Поделиться» в T-REF-ASK — URL-кнопка, бот нажатий не видит: считаем показы, после которых по ссылке пришёл человек
    ref_shares = c(select(func.count()).select_from(Invite).where(Invite.kind == "ref", Invite.opened > 0, Invite.created_at >= since))
    together = 2 * c(select(func.count()).select_from(InviteAccept).join(Invite).where(
        Invite.kind == "event", InviteAccept.status == "going", InviteAccept.opened_at >= since))

    def m(num: int, den: int, target: str) -> dict:
        return {"value": _ratio(num, den), "numerator": num, "denominator": den, "target": target}

    return {
        "since": since.isoformat(),
        "metrics": {
            "invite_share": m(invites_made, going, "≥ 15 %"),                  # приглашений / решений «иду»
            "acceptance": m(accepted, opened, "≥ 30 %"),                        # открывших с «иду» или «может быть» / открывших
            "activation_invited": m(new_activated, new_opened, "≥ 60 %"),       # из пришедших без профиля: согласие + решение
            "onboarding_invited": m(invited_onboarded, invited_profiles, "≥ 40 %"),   # полный профиль за 2 недели / принявших
            "new_via_friends": m(new_friends, new_total, "≥ 20 %"),
            "virality": m(new_friends, active, "≥ 0,2"),
            "positive_experience": m(rated_good, rated, "≥ 70 %"),
            "recommendation": m(ref_shares, ref_asks, "≥ 10 % (ссылку открыли / показов просьбы)"),
            "together_going": m(together, going, "наблюдаем"),
        },
        "counts": {"going_decisions": going, "invites_created": invites_made, "opened": opened, "accepted": accepted,
                   "new_profiles": new_total, "new_via_friends": new_friends, "ratings": rated, "ratings_4_5": rated_good,
                   "ref_asks": ref_asks, "ref_shares": ref_shares},
    }


# ─── принятие приглашения из веба (Mini App / браузер; вход через Telegram делает веб, сюда приходит user_id) ───
class ConsentRequired(Exception):
    """У человека нет профиля или согласия, а в запросе consent=false."""


class InviteUnavailable(Exception):
    def __init__(self, status: str):
        super().__init__(status)
        self.status = status       # past | unpublished | gone


class OwnInvite(Exception):
    """Пригласивший открыл или принял собственное приглашение."""


def create_for_api(session: Session, user_id: int, ev: Event | None, day: date | None, kind: str = "event") -> dict:
    """POST /api/invites: код, ссылка в Mini App (url), страница в вебе (web_url) и текст от первого лица (share_text)."""
    from leisure.core.links import invite_text

    inv = create_invite(session, user_id, ev, day, kind)
    link = miniapp_url(inv.code, kind) or web_url(inv)
    if kind == "event":
        share = invite_text(ev.as_core(), day.isoformat() if day else None, link)
    else:
        share = ("Пользуюсь сервисом, который каждый четверг присылает 5–7 событий на выходные и объясняет, почему они мне подходят. "
                 f"Настройка занимает минуту. Попробуй: {link}")             # T-REF-SHARE
    if kind == "event":
        log_growth(session, user_id, "invite_share")
    return {"code": inv.code, "kind": kind, "url": miniapp_url(inv.code, kind), "web_url": web_url(inv), "share_text": share}


def view(session: Session, inv: Invite, user_id: int | None = None) -> dict:
    """GET /api/invites/{code}: карточка события как в дайджесте, день, имя пригласившего (если не скрыто), статус, число принявших."""
    inviter = session.get(Profile, inv.inviter_id) if inv.inviter_id else None
    p = services.get_profile(session, user_id) if user_id else None
    today = services.local_today(p)
    item = None
    if inv.event is not None:
        day = inv.day or services.first_day(inv.event, today)
        iso = day.isoformat() if day else None
        from leisure.core.timeutil import weekend_iso
        item = services.card_item(session, p, inv.event, iso, weekend_iso(day or today), scored=False)
    mine = None
    if user_id:
        acc = session.scalar(select(InviteAccept).where(InviteAccept.invite_id == inv.id, InviteAccept.user_id == user_id))
        mine = acc.status if acc else None
    return {"code": inv.code, "kind": inv.kind, "event": item, "event_slug": inv.event_slug or None,
            "day": inv.day.isoformat() if inv.day else None,
            "inviter_name": display_name(inviter), "is_own": user_id is not None and user_id == inv.inviter_id,
            "status": ("gone" if inv.inviter_id is None else "active") if inv.kind == "ref" else status_of(session, inv, today),
            "accepted": inv.accepted,
            "my_status": mine}


def web_open(session: Session, inv: Invite, user_id: int, name: str = "", username: str = "") -> InviteAccept:
    """Человек открыл приглашение или ref-ссылку в Mini App: профиль-заготовка (без согласия), учёт открытия. Для ref-ссылки
    новому человеку сразу ставится источник «ref» и пригласивший."""
    if user_id == inv.inviter_id:
        raise OwnInvite()
    p = services.get_or_create_profile(session, user_id, name, username, via_bot=False)
    acc, _ = open_invite(session, inv, user_id)
    if inv.kind == "ref":
        adopt_new_profile(session, p, inv)
    return acc


def accept_result(session: Session, inv: Invite, user_id: int, d: Decision) -> dict:
    p = services.get_profile(session, user_id)
    inviter = session.get(Profile, inv.inviter_id) if inv.inviter_id else None
    return {"decision": services.decision_view(d) if d is not None else None, "together_with": display_name(inviter),
            "profile_state": "onboarded" if p is not None and p.onboarded_at is not None else "new"}


def web_accept(session: Session, inv: Invite, user_id: int, status: str, name: str = "", username: str = "",
               consent: bool = False) -> tuple[Decision | None, bool]:
    """«Иду» / «может быть» / «declined» по приглашению из Mini App.

    going / maybe: первое касание без профиля или согласия требует consent=True — профиль получает согласие, source=invite и
    referred_by. Повтор идемпотентен (счётчики и уведомление не дублируются; смена «может» ↔ «иду» разрешена).
    declined («Другие выходные под меня»): запись в invite_accepts без решения и без согласия; уже принявшего не откатывает.
    Возвращает (решение или None, первое_ли_принятие)."""
    if inv.kind != "event":
        raise ValueError("принять можно только приглашение на событие")
    if inv.inviter_id == user_id:
        raise OwnInvite()
    if status == "declined":
        acc = web_open(session, inv, user_id, name, username)
        if acc.status in ("opened", "declined"):
            acc.status = "declined"
            session.commit()
        d = session.scalar(select(Decision).where(Decision.user_id == user_id, Decision.invite_id == inv.id))
        return d, False
    state = status_of(session, inv, services.local_today(services.get_profile(session, user_id)))
    if state not in ("active", "gone"):
        raise InviteUnavailable(state)
    web_open(session, inv, user_id, name, username)
    p = services.get_profile(session, user_id)
    if p.consent_at is None:
        if not consent:
            raise ConsentRequired()
        services.update_profile(session, p, {"consent": True}, auto_onboarded=False)
    adopt_new_profile(session, p, inv)
    first = session.scalar(select(InviteAccept.accepted_at).where(InviteAccept.invite_id == inv.id, InviteAccept.user_id == user_id)) is None
    return accept_invite(session, inv, user_id, status), first


def apply_ref_code(session: Session, p: Profile, code: str) -> bool:
    """PUT /api/profile с ref_code: новому человеку (профиль не настроен, источник не задан) ставит source и referred_by по коду
    рекомендации или приглашения; учитывает открытие. Неизвестный код и свой собственный игнорируются. True — источник проставлен."""
    inv = get_invite(session, code)
    if inv is None or inv.inviter_id == p.user_id:
        return False
    before = p.source
    open_invite(session, inv, p.user_id)
    adopt_new_profile(session, p, inv)
    return p.source != before


INDIVIDUAL_NOTICES = 3          # по одному приглашению первые три друга сообщаются отдельно, дальше — сводка раз в день


def _rank(session: Session, acc: InviteAccept) -> int:
    """Порядковый номер принявшего «иду» среди принявших это приглашение (1 — первый)."""
    return int(session.scalar(select(func.count()).select_from(InviteAccept).where(
        InviteAccept.invite_id == acc.invite_id, InviteAccept.accepted_at.is_not(None),
        (InviteAccept.accepted_at < acc.accepted_at) | ((InviteAccept.accepted_at == acc.accepted_at) & (InviteAccept.id <= acc.id)))) or 0)


def _deliver(session: Session, inviter_id: int, text: str) -> bool | None:
    """Отправить пригласившему через бота. True — ушло; False — не ушло, повторить позже; None — писать не нужно/нельзя."""
    from leisure.worker import send as send_mod

    inviter = session.get(Profile, inviter_id) if inviter_id else None
    if inviter is None or not inviter.active:
        return None
    res = send_mod.send_sync([(inviter_id, text, [[{"text": "Мой план", "callback_data": "pl:s"}]])])
    for uid in res.blocked:
        services.mark_blocked(session, uid)
    if res.blocked:
        return None
    return 0 not in res.undelivered


def notify_inviter(session: Session, inv: Invite, user_id: int) -> bool:
    """Сообщить пригласившему «Имя идёт с тобой» через бота (worker.send), сразу после принятия — только первым трём друзьям по
    приглашению; остальных (4-й и дальше) соберёт сводка раз в день (notify_many). Ошибки отправки не ломают принятие:
    уведомление остаётся неотправленным, его доберёт worker.schedules.job_invite_notifications. True — доставлено."""
    from leisure.worker.messages import invite_joined_text

    acc = session.scalar(select(InviteAccept).where(InviteAccept.invite_id == inv.id, InviteAccept.user_id == user_id))
    if acc is None or acc.status != "going" or acc.notified_at is not None or acc.accepted_at is None:
        return False
    if _rank(session, acc) > INDIVIDUAL_NOTICES:
        return False
    try:
        if inv.event is None:
            acc.notified_at = datetime.now(timezone.utc)
            session.commit()
            return False
        text = invite_joined_text(display_name(session.get(Profile, user_id)), inv.event.title, inv.day.isoformat() if inv.day else None)
        done = _deliver(session, inv.inviter_id, text)
        if done is not False:
            acc.notified_at = datetime.now(timezone.utc)
            session.commit()
        return bool(done)
    except Exception:  # noqa: BLE001
        session.rollback()
        return False


def notify_many(session: Session, now: datetime | None = None, hour: int = 10, inviter_id: int | None = None) -> int:
    """Сводка раз в день: по каждому приглашению один T-INVITE-JOINED-MANY («Ещё N идут») о принявших с четвёртого и дальше.
    Уходит после утреннего плана — когда у пригласившего (по его часовому поясу) наступил `hour`. Возвращает число сводок."""
    from leisure.worker.messages import invite_joined_many_text

    now = now or datetime.now(timezone.utc)
    rows = session.scalars(select(InviteAccept).join(Invite).where(
        Invite.kind == "event", InviteAccept.status == "going", InviteAccept.accepted_at.is_not(None),
        InviteAccept.notified_at.is_(None), *([Invite.inviter_id == inviter_id] if inviter_id else [])).order_by(InviteAccept.accepted_at)).all()
    by_invite: dict[int, list[InviteAccept]] = {}
    for acc in rows:
        if _rank(session, acc) > INDIVIDUAL_NOTICES:
            by_invite.setdefault(acc.invite_id, []).append(acc)
    sent = 0
    for invite_id, accs in by_invite.items():
        inv = session.get(Invite, invite_id)
        inviter = session.get(Profile, inv.inviter_id) if inv.inviter_id else None
        if inviter is None or inv.event is None:
            for acc in accs:
                acc.notified_at = now
            session.commit()
            continue
        if services.local_now(inviter, now).hour < hour:
            continue
        done = _deliver(session, inv.inviter_id, invite_joined_many_text(len(accs), inv.event.title, inv.day.isoformat() if inv.day else None))
        if done is not False:
            for acc in accs:
                acc.notified_at = now
            session.commit()
            sent += int(bool(done))
    return sent


def pending_notifications(session: Session) -> list[InviteAccept]:
    """Принятые «иду» по приглашениям, о которых пригласивший ещё не уведомлён."""
    return list(session.scalars(select(InviteAccept).join(Invite).where(
        Invite.kind == "event", InviteAccept.status == "going", InviteAccept.accepted_at.is_not(None),
        InviteAccept.notified_at.is_(None)).order_by(InviteAccept.accepted_at)))
