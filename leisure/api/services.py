"""Сервисный слой: БД ↔ ядро. Один модуль, чтобы бот, воркер и роутеры звали одно и то же.

«Сегодня» всегда считается по часовому поясу профиля (или города по умолчанию), а не по часам сервера.
"""
from __future__ import annotations

import uuid
import logging
from collections.abc import Iterable
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from leisure import settings
from leisure.core.affinity import compute_affinity, describe_affinity, describe_affinity_text
from leisure.core.catalog import DECISION_STATUSES, default_profile
from leisure.core.config import scoring_config
from leisure.core.links import gcal_url, ics_text, is_local_url, outlook_url, plan_text, tg_share_url
from leisure.core.recommend import Digest as CoreDigest, build_digest
from leisure.core.scoring import ScoreResult, score_events
from leisure.core.timeutil import (event_dates, event_times, is_free, is_horizon, reco_slot, slot_of, trim_past, weekend_days,
                                   weekend_for, weekend_iso, weekend_title)
from leisure.db.models import Decision, Digest, Event, Profile

log = logging.getLogger("leisure.services")


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


def web_links_enabled() -> bool:
    """Можно ли ставить URL-кнопки на страницы веба: localhost Telegram отклоняет (BUTTON_URL_INVALID)."""
    return not is_local_url(settings.WEB_BASE_URL)


def warn_local_web_url() -> None:
    if not web_links_enabled():
        log.warning("WEB_BASE_URL=%s указывает на локальный адрес: бот не ставит URL-кнопки (политика, «Весь дайджест», "
                    "«Другу»), а даёт ссылки текстом. Задай публичный адрес в WEB_BASE_URL.", settings.WEB_BASE_URL)


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


def get_or_create_profile(session: Session, user_id: int, name: str = "", username: str = "", via_bot: bool = True) -> Profile:
    """via_bot=False — профиль создаёт Mini App/API: бот этому человеку ещё писать не может (can_write=False до /start или права)."""
    p = session.get(Profile, user_id)
    if p is None:
        d = default_profile()
        p = Profile(user_id=user_id, name=name, username=username, city=settings.DEFAULT_CITY, values=d["values"],
                    interests=d["interests"], params=d["params"], notes="", tz=settings.DEFAULT_TZ, can_write=via_bot)
        session.add(p)
        session.commit()
        session.refresh(p)
    return p


def set_active(session: Session, user_id: int, active: bool) -> bool:
    """Включить/выключить рассылки (заблокировавшего бота выключаем, вернувшегося по /start включаем)."""
    p = session.get(Profile, user_id)
    if p is None or p.active == active:
        return False
    p.active = active
    session.commit()
    return True


def mark_blocked(session: Session, user_id: int) -> bool:
    """Telegram ответил Forbidden. Заблокировавшему бота выключаем рассылки; человеку, которому бот ещё не мог писать
    (профиль из Mini App, can_write=False), — ничего: молча пропускаем. True — рассылки выключены."""
    p = session.get(Profile, user_id)
    if p is None or not p.can_write:
        return False
    return set_active(session, user_id, False)


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
        "offer_seen": p.offer_seen, "offer_due": p.offer_due.isoformat() if p.offer_due else None,
        "has_consent": p.consent_at is not None,
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
    d.status = status
    d.reason = reason if status in ("мимо", "пропуск") else None
    d.day = day or d.day or _default_day(ev, local_today(p))
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


def decisions_to_remind(session: Session, user_id: int, day: date) -> list[Decision]:
    """«Иду» на этот день, о которых ещё не напоминали."""
    return session.scalars(select(Decision).where(Decision.user_id == user_id, Decision.status == "иду", Decision.day == day,
                                                  Decision.reminded_at.is_(None)).order_by(Decision.id)).all()


def decisions_to_ask(session: Session, user_id: int, day: date) -> list[Decision]:
    """«Иду» на этот день без оценки, о которых ещё не спрашивали «Как прошло?»."""
    return session.scalars(select(Decision).where(Decision.user_id == user_id, Decision.status == "иду", Decision.day == day,
                                                  Decision.rating.is_(None), Decision.feedback_asked_at.is_(None))
                           .order_by(Decision.id)).all()


def plan(session: Session, p: Profile, today: date | None = None) -> dict:
    today = today_or(p, today)
    weekend = weekend_iso(today)
    events = {e["id"]: e for e in upcoming_events(session, p.city, today)}
    decs = [d for d in user_decisions(session, p.user_id) if d.status in ("иду", "может") and d.event_id and str(d.event_id) in events]
    days: dict[str, list[dict]] = {d: [] for d in weekend}
    horizon: list[dict] = []
    for d in decs:
        ev = events[str(d.event_id)]
        if is_horizon(ev, weekend):
            hday = d.day.isoformat() if d.day and d.day.isoformat() in event_dates(ev) else event_dates(ev)[0]
            horizon.append({"event": event_view(ev), "status": d.status, "day": hday, "links": links_for(ev, hday),
                            "companions": companion_names(session, p.user_id, d)})
            continue
        wd = weekend_days(ev, weekend)
        day = d.day.isoformat() if d.day and d.day.isoformat() in wd else wd[0]
        days[day].append({"event": event_view(ev), "status": d.status, "day": day, "links": links_for(ev, day),
                          "companions": companion_names(session, p.user_id, d)})
    for day, items in days.items():
        _mark_conflicts(items, day)
    text = plan_text({d: [it["event"] for it in items if it["status"] == "иду"] for d, items in days.items()}, weekend,
                     [h["event"] for h in horizon if h["status"] == "иду"])
    return {"weekend": weekend, "title": weekend_title(weekend), "days": days, "horizon": horizon, "text": text}


def ics_for(ev: dict, day: date | str | None) -> str:
    d = day.isoformat() if isinstance(day, date) else day
    return ics_text(ev, d, uid_domain=settings.WEB_BASE_URL.split("//")[-1].split("/")[0] or "leisure")
