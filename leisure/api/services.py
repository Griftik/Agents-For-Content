"""Сервисный слой: БД ↔ ядро. Один модуль, чтобы бот, воркер и роутеры звали одно и то же.

«Сегодня» всегда считается по часовому поясу профиля (или города по умолчанию), а не по часам сервера.
"""
from __future__ import annotations

import uuid
import logging
from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from leisure import settings
from leisure.core.affinity import compute_affinity, describe_affinity, describe_affinity_text
from leisure.core.catalog import DECISION_ALIASES, DECISION_STATUSES, PROFILE_KINDS, default_profile
from leisure.core.config import scoring_config
from leisure.core.links import gcal_url, ics_text, outlook_url, plan_text, tg_share_url
from leisure.core.recommend import Digest as CoreDigest, build_digest
from leisure.core.scoring import ScoreResult, score_events
from leisure.core.timeutil import (event_dates, event_times, is_free, is_horizon, reco_slot, slot_of, trim_past, weekend_days,
                                   weekend_for, weekend_iso, weekend_title)
from leisure.db.models import Account, Decision, Digest, Event, Profile

log = logging.getLogger("leisure.services")


class DecisionTooEarly(ValueError):
    """«Сходил» / «не сходил» можно отметить только после дня события."""

    def __init__(self, day):
        super().__init__("отметить «сходил» или «не сходил» можно после дня события" + (f" ({day.isoformat()})" if day else ""))


class ProfileMissing(LookupError):
    """Профиля нет (не создан или удалён по /delete): решения и прочие данные без него не пишем."""


# ─── время ───
def _zone(tz: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(tz or settings.DEFAULT_TZ)
    except Exception:  # noqa: BLE001
        return ZoneInfo(settings.DEFAULT_TZ)


def utcnow() -> datetime:
    """Текущий момент (UTC). Единая точка для живых путей бота и воркера — удобно подменять в тестах и симуляции."""
    return datetime.now(timezone.utc)


def local_today(p: Profile | None = None, now: datetime | None = None) -> date:
    now = now or utcnow()
    return now.astimezone(_zone(p.tz if p else None)).date()


def local_now(p: Profile | None = None, now: datetime | None = None) -> datetime:
    """Момент в часовом поясе профиля (или города по умолчанию)."""
    return (now or utcnow()).astimezone(_zone(p.tz if p else None))


def today_or(p: Profile | None, today: date | None) -> date:
    return today or local_today(p)


# ─── события ───
def event_view(ev: dict) -> dict:
    return {**ev, "slot": slot_of(ev), "free": is_free(ev)}


def upcoming_events(session: Session, city: str, today: date, now: datetime | None = None,
                    statuses: Iterable[str] = ("published",)) -> list[dict]:
    """События города с датами не раньше сегодня, в формате ядра; по умолчанию только опубликованные.

    now — местное время (дата + часы): сегодняшние даты событий, до начала которых меньше 30 минут (или которые уже начались), отбрасываются; выставки и места — только после end_time.
    Без now времени суток не учитываем. statuses — какие статусы читать (сборщик читает ещё и черновики).
    """
    rows = session.scalars(select(Event).where(Event.status.in_(tuple(statuses)), Event.city == city)
                           .order_by(Event.created_at)).all()
    return trim_past([r.as_core() for r in rows], today.isoformat(), now)


def get_event(session: Session, key: str) -> Event | None:
    key = str(key).strip()
    if len(key) == 36 and key.count("-") == 4:
        try:
            ev = session.get(Event, uuid.UUID(key))
            if ev is not None:
                return ev
        except ValueError:
            pass
    return session.scalar(select(Event).where(Event.slug == key))


def page_url(ev: dict) -> str:
    return f"{settings.WEB_BASE_URL.rstrip('/')}/e/{ev.get('slug')}"


def links_for(ev: dict, day: str | None, why: str | None = None) -> dict:
    return {
        "gcal": gcal_url(ev, day), "outlook": outlook_url(ev, day),
        "ics": f"{settings.WEB_BASE_URL.rstrip('/')}/api/events/{ev.get('slug')}/ics" + (f"?day={day}" if day else ""),
        "tg": tg_share_url(ev, day, url=page_url(ev), why=why), "page": page_url(ev),
    }


# ─── профиль ───
def get_profile(session: Session, user_id: int) -> Profile | None:
    return session.get(Profile, user_id)


def new_user_id(session: Session) -> int:
    """Новый идентификатор из guest_user_id_seq (с 10^12): для гостевой сессии и дополнительных профилей аккаунта."""
    uid = session.execute(text("select nextval('guest_user_id_seq')")).scalar_one()
    return int(uid)


def get_or_create_profile(session: Session, user_id: int, name: str = "", username: str = "", can_write: bool = False,
                          account_id: int | None = None, kind: str = "self") -> Profile:
    """Профиль создаёт веб (первый PUT с согласием). Основной профиль аккаунта: user_id = id аккаунта (аккаунт заводится здесь же,
    если его ещё нет); дополнительные — через create_profile. can_write оставлено на будущее (push сняты), по умолчанию false."""
    p = session.get(Profile, user_id)
    if p is None:
        acc_id = account_id or user_id
        if session.get(Account, acc_id) is None:
            session.add(Account(id=acc_id))
            session.flush()
        d = default_profile()
        p = Profile(user_id=user_id, account_id=acc_id, kind=kind if kind in PROFILE_KINDS else "other", name=name, username=username,
                    city=settings.DEFAULT_CITY, values=d["values"], interests=d["interests"], params=d["params"], notes="",
                    tz=settings.DEFAULT_TZ, can_write=can_write)
        session.add(p)
        session.commit()
        session.refresh(p)
    return p


def account_profiles(session: Session, account_id: int) -> list[Profile]:
    return session.scalars(select(Profile).where(Profile.account_id == account_id).order_by(Profile.created_at, Profile.user_id)).all()


def create_profile(session: Session, account_id: int, name: str, kind: str = "other") -> Profile:
    """Дополнительный профиль аккаунта («мама», «ребёнок»): свой user_id, свои ценности/интересы/решения; согласие наследуется от
    владельца, онбординг — отдельно."""
    owner = session.get(Profile, account_id) or next(iter(account_profiles(session, account_id)), None)
    if owner is None:
        raise ProfileMissing(account_id)
    p = get_or_create_profile(session, new_user_id(session), name=name, account_id=account_id, kind=kind)
    p.consent_at, p.tz, p.city = owner.consent_at, owner.tz, owner.city
    session.commit()
    session.refresh(p)
    return p


def set_active(session: Session, user_id: int, active: bool) -> bool:
    """Включить/выключить рассылки уведомлений (профиль active=false не получает подборки, планы и «Как прошло?»)."""
    p = session.get(Profile, user_id)
    if p is None or p.active == active:
        return False
    p.active = active
    session.commit()
    return True


def update_profile(session: Session, p: Profile, data: dict, auto_onboarded: bool = True) -> Profile:
    """data — словарь из ProfileIn.model_dump(exclude_none=True); словари сливаются, остальное заменяется.

    auto_onboarded=False: запись черновика (шаги онбординга бота) не помечает профиль готовым — только явный onboarded."""
    for k in ("name", "username", "city", "notes", "tz", "digest_day", "digest_hour", "show_name", "can_write", "offer_seen"):
        if data.get(k) is not None:
            setattr(p, k, data[k])
    if data.get("values") is not None:
        p.values = {**(p.values or {}), **{k: int(v) for k, v in data["values"].items()}}
    if data.get("interests") is not None:
        p.interests = {**(p.interests or {}), **{k: int(v) for k, v in data["interests"].items()}}
    if data.get("params") is not None:
        p.params = {**(p.params or {}), **{k: v for k, v in data["params"].items() if v is not None}}
    if data.get("affinity") and (data["affinity"].get("tag") or data["affinity"].get("cat")):
        set_manual_affinity(session, p, data["affinity"])
    if data.get("consent") and p.consent_at is None:
        p.consent_at = datetime.now(timezone.utc)
    # Онбординг идёт по шагам (ценности → интересы → параметры): считаем завершённым по явному флагу
    # или по шагу «интересы» — с него профиль уже можно скорить.
    if p.onboarded_at is None and (data.get("onboarded") or (auto_onboarded and data.get("interests") is not None)):
        p.onboarded_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(p)
    return p


def delete_profile(session: Session, user_id: int) -> bool:
    """Отзыв согласия: профиль, решения и дайджесты удаляются каскадом. Обезличенной статистики пока нет."""
    p = session.get(Profile, user_id)
    if p is None:
        return False
    if p.user_id == p.account_id:           # основной профиль: уходит весь аккаунт со всеми профилями, решениями, токенами входа
        acc = session.get(Account, p.account_id)
        for extra in account_profiles(session, p.account_id):
            session.delete(extra)
        session.delete(acc)
    else:
        session.delete(p)
    session.commit()
    return True


def profile_view(p: Profile, decisions: list[Decision] | None = None) -> dict:
    decs = [d.as_core() for d in (decisions or [])]
    aff = p.affinity or {"tag": {}, "cat": {}, "n": 0}
    return {
        "user_id": p.user_id, "name": p.name, "username": p.username, "city": p.city, "values": p.values or {},
        "interests": p.interests or {}, "params": p.params or {}, "notes": p.notes, "tz": p.tz,
        "digest_day": p.digest_day, "digest_hour": p.digest_hour, "plan": p.plan, "affinity": aff,
        "learned": describe_affinity(aff, decs), "learned_text": describe_affinity_text(aff, decs),
        "onboarded": p.onboarded_at is not None, "show_name": p.show_name, "source": p.source, "can_write": p.can_write,
        "account_id": p.account_id, "kind": p.kind,
        "offer_seen": p.offer_seen, "offer_due": p.offer_due.isoformat() if p.offer_due else None,
        "has_consent": p.consent_at is not None, "email": p.account.email if p.account else None,
        "affinity_manual_at": p.affinity_manual_at.isoformat() if p.affinity_manual_at else None,
    }


# ─── решения и обучение ───
def user_decisions(session: Session, user_id: int) -> list[Decision]:
    return session.scalars(select(Decision).where(Decision.user_id == user_id)).all()


def merge_affinity(computed: dict, manual: dict | None) -> dict:
    """Вычисленное по решениям + ручная правка (прибавка по ключам). Без правки результат равен computed."""
    out = {"tag": dict(computed.get("tag") or {}), "cat": dict(computed.get("cat") or {}), "n": computed.get("n", 0)}
    for kind in ("tag", "cat"):
        for k, delta in ((manual or {}).get(kind) or {}).items():
            out[kind][k] = out[kind].get(k, 0.0) + float(delta)
    return out


def recompute_affinity(session: Session, p: Profile) -> dict:
    """Пересчёт обучения по решениям; ручная правка пользователя (affinity_manual) складывается с вычисленным, а не затирается."""
    decs = [d.as_core() for d in user_decisions(session, p.user_id)]
    p.affinity = merge_affinity(compute_affinity(decs, scoring_config()), p.affinity_manual)
    session.commit()
    return p.affinity


def set_manual_affinity(session: Session, p: Profile, edit: dict) -> dict:
    """Ручная правка «Что я узнал о тебе»: edit = {'tag': {тег: вес}, 'cat': {категория: вес}} — желаемые итоговые веса
    по указанным ключам. Хранится разницей с вычисленным по решениям, поэтому дальнейшие решения добавляются поверх."""
    decs = [d.as_core() for d in user_decisions(session, p.user_id)]
    computed = compute_affinity(decs, scoring_config())
    manual = {"tag": dict((p.affinity_manual or {}).get("tag") or {}), "cat": dict((p.affinity_manual or {}).get("cat") or {})}
    for kind in ("tag", "cat"):
        for k, target in (edit.get(kind) or {}).items():
            delta = float(target) - float(computed[kind].get(k, 0.0))
            if abs(delta) < 1e-9:
                manual[kind].pop(k, None)
            else:
                manual[kind][k] = delta
    p.affinity_manual = manual
    p.affinity_manual_at = datetime.now(timezone.utc)
    p.affinity = merge_affinity(computed, manual)
    session.commit()
    return p.affinity


def _default_day(ev: Event, today: date) -> date | None:
    """День решения по умолчанию: первая дата события не раньше сегодня, иначе последняя известная."""
    ds = sorted(ev.dates or [])
    if not ds:
        return None
    return next((d for d in ds if d >= today), ds[-1])


def set_decision(session: Session, user_id: int, ev: Event, status: str, reason: str | None = None,
                 day: date | None = None, rating: int | None = None, invite_id: int | None = None) -> Decision:
    """Записать решение. Профиль не создаём: после /delete старая кнопка не должна воскрешать данные (ProfileMissing).

    day — день с карточки; если передан, обновляет Decision.day и при повторном решении. Смена дня сбрасывает флаги
    напоминания и запроса оценки (они относятся к конкретному дню).
    """
    status = DECISION_ALIASES.get(status, status)
    if status not in DECISION_STATUSES:
        raise ValueError(f"status должен быть одним из {DECISION_STATUSES}")
    p = get_profile(session, user_id)
    if p is None:
        raise ProfileMissing(user_id)
    d = session.scalar(select(Decision).where(Decision.user_id == user_id, Decision.event_id == ev.id))
    if d is None:
        d = Decision(user_id=user_id, event_id=ev.id)
        session.add(d)
    old_day = d.day
    new_day = day or d.day or _default_day(ev, local_today(p))
    if status in ("сходил", "не сходил"):           # отметки в плане: только после дня события
        if new_day is None or new_day > local_today(p):
            session.rollback()
            raise DecisionTooEarly(new_day)
    d.status = status
    d.reason = reason if status in ("мимо", "пропуск", "не моё") else None
    d.day = new_day
    if old_day is not None and d.day != old_day:
        d.reminded_at = d.feedback_asked_at = None
    if rating is not None:
        d.rating = rating
    if invite_id is not None:
        d.invite_id = invite_id
    d.event_slug, d.event_category, d.event_tags = ev.slug, ev.category, list(ev.tags or [])
    session.commit()
    recompute_affinity(session, p)
    refresh_digest_stats(session, p, ev)
    session.refresh(d)
    return d


def refresh_digest_stats(session: Session, p: Profile, ev: Event, today: date | None = None) -> None:
    """Дайджест этого уикенда, в котором есть событие: opened = True, decisions_count = число решений по его событиям."""
    weekend_start = weekend_for(today_or(p, today))[0]
    row = session.scalar(select(Digest).where(Digest.user_id == p.user_id, Digest.weekend_start == weekend_start,
                                              Digest.sent_at.is_not(None)))
    if row is None:
        return
    ids = {str(it.get("event_id")) for it in (row.items or [])}
    if str(ev.id) not in ids:
        return
    decided = {str(d.event_id) for d in user_decisions(session, p.user_id) if d.event_id}
    row.opened = True
    row.decisions_count = len(ids & decided)
    session.commit()


def remove_decision(session: Session, user_id: int, ev: Event) -> bool:
    d = session.scalar(select(Decision).where(Decision.user_id == user_id, Decision.event_id == ev.id))
    if d is None:
        return False
    session.delete(d)
    session.commit()
    p = get_profile(session, user_id)
    if p:
        recompute_affinity(session, p)
        refresh_digest_stats(session, p, ev)
    return True


def decision_view(d: Decision) -> dict:
    return {"event_id": str(d.event_id) if d.event_id else None, "event_slug": d.event_slug, "status": d.status,
            "reason": d.reason, "day": d.day.isoformat() if d.day else None, "rating": d.rating}


# ─── дайджест ───
def recently_shown_ids(session: Session, user_id: int, before_weekend: date, n: int | None = None) -> set[str]:
    """События из последних n ОТПРАВЛЕННЫХ дайджестов за прошлые уикенды, на которые не было реакции."""
    n = n or int(scoring_config()["recommend"]["digests_without_reaction"])
    digests = session.scalars(
        select(Digest).where(Digest.user_id == user_id, Digest.sent_at.is_not(None), Digest.weekend_start < before_weekend)
        .order_by(Digest.weekend_start.desc()).limit(n)).all()
    shown = {str(it.get("event_id")) for dg in digests for it in (dg.items or [])}
    reacted = {str(d.event_id) for d in user_decisions(session, user_id) if d.event_id}
    return shown - reacted


def core_digest(session: Session, p: Profile, today: date, weekend: list[str] | None = None,
                now: datetime | None = None) -> tuple[CoreDigest, list[dict], dict[str, ScoreResult]]:
    """now — момент сборки: сегодняшние события, до начала которых меньше 30 минут, в подборку не попадают."""
    weekend = weekend or weekend_iso(today)
    events = upcoming_events(session, p.city, today, local_now(p, now).replace(tzinfo=None) if now else None)
    decs = [d.as_core() for d in user_decisions(session, p.user_id)]
    scores = score_events(events, p.as_core(), decs, aff=p.affinity or None)
    recent = recently_shown_ids(session, p.user_id, date.fromisoformat(weekend[0]))
    dg = build_digest(events, p.as_core(), decs, weekend, recently_shown=recent, scores=scores)
    return dg, events, scores


def decision_map(session: Session, user_id: int) -> dict[str, dict]:
    """Текущие решения пользователя по id события: {event_id: decision_view}."""
    return {str(d.event_id): decision_view(d) for d in user_decisions(session, user_id) if d.event_id}


def _item(ev: dict, day: str | None, slot: str, r: ScoreResult | None, chosen: bool, why_limit: int,
          weekend: list[str] | None = None, decisions: dict[str, dict] | None = None) -> dict:
    why = r.why_dicts(why_limit) if r else []
    hint = ev.get("why_fit_hint") or None
    return {"event": event_view(ev), "day": day, "slot": slot, "score": r.score if r else None, "why": why,
            "chosen": chosen, "links": links_for(ev, day, hint), "days": weekend_days(ev, weekend or []),
            "decision": (decisions or {}).get(str(ev.get("id")))}


def digest_view(p: Profile, dg: CoreDigest, decisions: dict[str, dict] | None = None) -> dict:
    """Дайджест для API и бота. decisions — {event_id: decision_view}: каждый элемент несёт текущее решение или None."""
    limit = int(scoring_config()["why"]["max_total"])
    items = [_item(s.event, s.day, s.slot, s.result, s.chosen, limit, dg.weekend, decisions) for s in dg.slots if s.event]
    horizon = [_item(ev, event_dates(ev)[0] if event_dates(ev) else None, "горизонт", r, False, limit, dg.weekend, decisions)
               for ev, r in dg.horizon]
    return {"user_id": p.user_id, "weekend": dg.weekend, "title": weekend_title(dg.weekend), "items": items, "horizon": horizon}


def first_day(ev: Event, today: date) -> date | None:
    """Первый день события не раньше сегодня (для карточки по диплинку), иначе последний известный."""
    return _default_day(ev, today)


def card_item(session: Session, p: Profile | None, ev: Event, day: str | None, weekend: list[str], scored: bool = True) -> dict:
    """Элемент карточки для одного события (перерисовка при выборе дня, диплинк): тот же формат, что в digest_view.
    scored=False — без «совпадения» и причин (профиль ещё не настроен, оценивать нечем)."""
    core = ev.as_core()
    r = None
    if scored and p is not None:        # тот же расчёт, что в scored_events (дайджест для веба)
        decs = [d.as_core() for d in user_decisions(session, p.user_id)]
        r = score_events([core], p.as_core(), decs, aff=p.affinity or None)[core["id"]]
    dm = decision_map(session, p.user_id) if p is not None else {}
    slot = reco_slot(core)
    return _item(core, day, slot, r, False, int(scoring_config()["why"]["max_total"]), weekend, dm)


def digest_preview(session: Session, p: Profile, today: date | None = None, now: datetime | None = None) -> dict:
    dg, _, _ = core_digest(session, p, today_or(p, today), now=now)
    return digest_view(p, dg, decision_map(session, p.user_id))


def digest_row(session: Session, p: Profile, weekend_start: date) -> Digest:
    row = session.scalar(select(Digest).where(Digest.user_id == p.user_id, Digest.weekend_start == weekend_start))
    if row is None:
        row = Digest(user_id=p.user_id, weekend_start=weekend_start, items=[])
        session.add(row)
        session.commit()
    return row


def save_digest(session: Session, p: Profile, dg: CoreDigest, sent: bool = False) -> Digest:
    row = digest_row(session, p, date.fromisoformat(dg.weekend[0]))
    if row.sent_at is not None and not sent:
        return row  # журнал «что показывали» не затираем пересборкой уже отправленной подборки
    row.items = dg.items(int(scoring_config()["why"]["max_total"]))
    if sent:
        row.sent_at = datetime.now(timezone.utc)
    session.commit()
    return row


def scored_events(session: Session, p: Profile, today: date | None = None) -> list[dict]:
    """Полный дайджест для веба: все предстоящие события с баллом, по убыванию совпадения."""
    today = today_or(p, today)
    events = upcoming_events(session, p.city, today)
    decs = [d.as_core() for d in user_decisions(session, p.user_id)]
    scores = score_events(events, p.as_core(), decs, aff=p.affinity or None)
    limit = int(scoring_config()["why"]["max_total"])
    dm = decision_map(session, p.user_id)
    out = [{**event_view(ev), "score": scores[ev["id"]].score, "why": scores[ev["id"]].why_dicts(limit),
            "links": links_for(ev, (event_dates(ev) or [None])[0], ev.get("why_fit_hint") or None), "decision": dm.get(ev["id"])}
           for ev in events]
    out.sort(key=lambda e: -e["score"])
    return out


def companion_names(session: Session, user_id: int, d: Decision) -> list[str]:
    """С кем человек идёт на событие по приглашениям: имена (или «другом», если имя скрыто). Лениво импортирует модуль приглашений."""
    from . import invites
    return invites.companion_names(session, user_id, d)


# ─── план ───
def _mark_conflicts(items: list[dict], day: str) -> None:
    """Сортирует события дня по началу и ставит conflict у пересекающихся «иду»."""
    items.sort(key=lambda it: event_times(it["event"], day)[1])
    going = [it for it in items if it["status"] == "иду"]
    for a in going:
        _, s1, e1 = event_times(a["event"], day)
        for b in going:
            if a is b:
                continue
            _, s2, e2 = event_times(b["event"], day)
            if s1 < e2 and s2 < e1:
                a["conflict"] = True
                a.setdefault("conflict_with", b["event"]["title"])


def day_plan(decisions: Iterable[Decision], day: date, session: Session | None = None) -> dict:
    """План на один произвольный день (будни, события «на горизонте») по решениям «иду» с этим днём.

    Формат как у plan(): {'weekend': [день], 'days': {день: [items]}}, годится для plan_today_text.
    Решения без живого опубликованного события пропускаются.
    """
    iso = day.isoformat()
    items = []
    for d in decisions:
        ev = d.event
        if ev is None or ev.status != "published" or d.status != "иду":
            continue
        core = ev.as_core()
        items.append({"event": event_view(core), "status": d.status, "day": iso, "links": links_for(core, iso),
                      "companions": companion_names(session, d.user_id, d) if session is not None else []})
    _mark_conflicts(items, iso)
    return {"weekend": [iso], "days": {iso: items}}


PLAN_DAYS = 7          # окно плана: сегодня и шесть дней вперёд
PAST_DAYS = 30         # прошедшие события держим для отметок «сходил / не сходил» и оценки
PLAN_STATUSES = ("иду", "может", "сходил", "не сходил")


def plan(session: Session, p: Profile, today: date | None = None) -> dict:
    """План профиля (версия 2): 7 дней от сегодня по дням, «дальше» — за окном, «прошедшие» — за последние 30 дней с отметками.
    Решения без живого опубликованного события пропускаются; «вдвоём с Имя» — companions."""
    today = today_or(p, today)
    window = [(today + timedelta(days=i)).isoformat() for i in range(PLAN_DAYS)]
    since = (today - timedelta(days=PAST_DAYS)).isoformat()
    rows = session.scalars(select(Event).where(Event.status == "published", Event.city == p.city)).all()
    events = {str(r.id): r.as_core() for r in rows}
    days: dict[str, list[dict]] = {d: [] for d in window}
    horizon: list[dict] = []
    past: list[dict] = []
    for d in user_decisions(session, p.user_id):
        ev = events.get(str(d.event_id)) if d.event_id else None
        if ev is None or d.status not in PLAN_STATUSES:
            continue
        ds = event_dates(ev)
        if d.day and d.day.isoformat() in ds:
            day = d.day.isoformat()
        else:
            day = next((x for x in ds if x >= today.isoformat()), ds[-1] if ds else None)
        if day is None:
            continue
        item = {"event": event_view(ev), "status": d.status, "day": day, "rating": d.rating, "links": links_for(ev, day),
                "companions": companion_names(session, p.user_id, d)}
        if day < today.isoformat():
            if day >= since:
                past.append(item)
        elif day in days:
            days[day].append(item)
        else:
            horizon.append(item)
    for day, items in days.items():
        _mark_conflicts(items, day)
    horizon.sort(key=lambda it: it["day"])
    past.sort(key=lambda it: it["day"], reverse=True)
    text = plan_text({d: [it["event"] for it in items if it["status"] == "иду"] for d, items in days.items()}, window,
                     [h["event"] for h in horizon if h["status"] == "иду"])
    return {"weekend": window, "today": today.isoformat(), "title": weekend_title(window), "days": days, "horizon": horizon,
            "past": past, "text": text}


def feed(session: Session, p: Profile, spec: str = "today", segment: str = "all", limit: int | None = None,
         today: date | None = None, now: datetime | None = None, include_missed: bool = False) -> dict:
    """GET /api/feed: лента профиля на день или период (core.feed.build_feed). now — местное время профиля без пояса (тесты,
    симулятор); без now и today берётся текущее время профиля, с одним today время суток не учитывается."""
    from leisure.core.feed import build_feed, parse_window

    if now is None and today is None:
        now = local_now(p).replace(tzinfo=None)
    today = today or (now.date() if now else local_today(p))
    days = parse_window(spec, today)
    events = upcoming_events(session, p.city, today)
    decs = [d.as_core() for d in user_decisions(session, p.user_id)]
    travel = (p.params or {}).get("travel_minutes")
    items = build_feed(events, p.as_core(), decs, days, today, now=now, segment=segment, travel_minutes=travel, limit=limit,
                       include_missed=include_missed)
    dm = decision_map(session, p.user_id)
    why_limit = int(scoring_config()["why"]["max_total"])
    out = [{"event": event_view(it.event), "day": it.day, "days": it.days, "score": it.result.score,
            "why": it.result.why_dicts(why_limit), "can_make_it": it.can_make_it,
            "links": links_for(it.event, it.day, it.event.get("why_fit_hint") or None), "decision": dm.get(str(it.event["id"]))}
           for it in items]
    travel_out = int(travel) if travel is not None else int(scoring_config()["feed"]["travel_minutes"])
    return {"user_id": p.user_id, "date": spec, "days": [d.isoformat() for d in days], "today": today.isoformat(),
            "segment": segment, "travel_minutes": travel_out, "items": out}


def ics_for(ev: dict, day: date | str | None) -> str:
    d = day.isoformat() if isinstance(day, date) else day
    return ics_text(ev, d, uid_domain=settings.WEB_BASE_URL.split("//")[-1].split("/")[0] or "leisure")
