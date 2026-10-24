"""Сервисный слой: БД ↔ ядро. Один модуль, чтобы бот, воркер и роутеры звали одно и то же.

«Сегодня» всегда считается по часовому поясу профиля (или города по умолчанию), а не по часам сервера.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from leisure import settings
from leisure.core.affinity import compute_affinity, describe_affinity, describe_affinity_text
from leisure.core.catalog import DECISION_STATUSES, default_profile
from leisure.core.config import scoring_config
from leisure.core.links import gcal_url, ics_text, outlook_url, plan_text, tg_share_url
from leisure.core.recommend import Digest as CoreDigest, build_digest
from leisure.core.scoring import ScoreResult, score_events
from leisure.core.timeutil import (event_dates, event_times, is_free, is_horizon, slot_of, trim_past, weekend_days,
                                   weekend_iso, weekend_title)
from leisure.db.models import Decision, Digest, Event, Profile


# ─── время ───
def _zone(tz: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(tz or settings.DEFAULT_TZ)
    except Exception:  # noqa: BLE001
        return ZoneInfo(settings.DEFAULT_TZ)


def local_today(p: Profile | None = None, now: datetime | None = None) -> date:
    now = now or datetime.now(timezone.utc)
    return now.astimezone(_zone(p.tz if p else None)).date()


def today_or(p: Profile | None, today: date | None) -> date:
    return today or local_today(p)


# ─── события ───
def event_view(ev: dict) -> dict:
    return {**ev, "slot": slot_of(ev), "free": is_free(ev)}


def upcoming_events(session: Session, city: str, today: date) -> list[dict]:
    """Опубликованные события города с датами не раньше сегодня, в формате ядра."""
    rows = session.scalars(select(Event).where(Event.status == "published", Event.city == city).order_by(Event.created_at)).all()
    return trim_past([r.as_core() for r in rows], today.isoformat())


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


def get_or_create_profile(session: Session, user_id: int, name: str = "", username: str = "") -> Profile:
    p = session.get(Profile, user_id)
    if p is None:
        d = default_profile()
        p = Profile(user_id=user_id, name=name, username=username, city=settings.DEFAULT_CITY, values=d["values"],
                    interests=d["interests"], params=d["params"], notes="", tz=settings.DEFAULT_TZ)
        session.add(p)
        session.commit()
        session.refresh(p)
    return p


def update_profile(session: Session, p: Profile, data: dict) -> Profile:
    """data — словарь из ProfileIn.model_dump(exclude_none=True); словари сливаются, остальное заменяется."""
    for k in ("name", "username", "city", "notes", "tz", "digest_day", "digest_hour"):
        if data.get(k) is not None:
            setattr(p, k, data[k])
    if data.get("values") is not None:
        p.values = {**(p.values or {}), **{k: int(v) for k, v in data["values"].items()}}
    if data.get("interests") is not None:
        p.interests = {**(p.interests or {}), **{k: int(v) for k, v in data["interests"].items()}}
    if data.get("params") is not None:
        p.params = {**(p.params or {}), **{k: v for k, v in data["params"].items() if v is not None}}
    if data.get("consent") and p.consent_at is None:
        p.consent_at = datetime.now(timezone.utc)
    # Онбординг идёт по шагам (ценности → интересы → параметры): считаем завершённым по явному флагу
    # или по шагу «интересы» — с него профиль уже можно скорить.
    if p.onboarded_at is None and (data.get("onboarded") or data.get("interests") is not None):
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
        "onboarded": p.onboarded_at is not None,
    }


# ─── решения и обучение ───
def user_decisions(session: Session, user_id: int) -> list[Decision]:
    return session.scalars(select(Decision).where(Decision.user_id == user_id)).all()


def recompute_affinity(session: Session, p: Profile) -> dict:
    decs = [d.as_core() for d in user_decisions(session, p.user_id)]
    p.affinity = compute_affinity(decs, scoring_config())
    session.commit()
    return p.affinity


def _default_day(ev: Event, today: date) -> date | None:
    """День решения по умолчанию: первая дата события не раньше сегодня, иначе последняя известная."""
    ds = sorted(ev.dates or [])
    if not ds:
        return None
    return next((d for d in ds if d >= today), ds[-1])


def set_decision(session: Session, user_id: int, ev: Event, status: str, reason: str | None = None,
                 day: date | None = None, rating: int | None = None) -> Decision:
    if status not in DECISION_STATUSES:
        raise ValueError(f"status должен быть одним из {DECISION_STATUSES}")
    p = get_or_create_profile(session, user_id)
    d = session.scalar(select(Decision).where(Decision.user_id == user_id, Decision.event_id == ev.id))
    if d is None:
        d = Decision(user_id=user_id, event_id=ev.id)
        session.add(d)
    d.status = status
    d.reason = reason if status in ("мимо", "пропуск") else None
    d.day = day or d.day or _default_day(ev, local_today(p))
    if rating is not None:
        d.rating = rating
    d.event_slug, d.event_category, d.event_tags = ev.slug, ev.category, list(ev.tags or [])
    session.commit()
    recompute_affinity(session, p)
    session.refresh(d)
    return d


def remove_decision(session: Session, user_id: int, ev: Event) -> bool:
    d = session.scalar(select(Decision).where(Decision.user_id == user_id, Decision.event_id == ev.id))
    if d is None:
        return False
    session.delete(d)
    session.commit()
    p = get_profile(session, user_id)
    if p:
        recompute_affinity(session, p)
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


def core_digest(session: Session, p: Profile, today: date, weekend: list[str] | None = None
                ) -> tuple[CoreDigest, list[dict], dict[str, ScoreResult]]:
    weekend = weekend or weekend_iso(today)
    events = upcoming_events(session, p.city, today)
    decs = [d.as_core() for d in user_decisions(session, p.user_id)]
    scores = score_events(events, p.as_core(), decs, aff=p.affinity or None)
    recent = recently_shown_ids(session, p.user_id, date.fromisoformat(weekend[0]))
    dg = build_digest(events, p.as_core(), decs, weekend, recently_shown=recent, scores=scores)
    return dg, events, scores


def _item(ev: dict, day: str | None, slot: str, r: ScoreResult | None, chosen: bool, why_limit: int) -> dict:
    why = r.why_dicts(why_limit) if r else []
    hint = ev.get("why_fit_hint") or None
    return {"event": event_view(ev), "day": day, "slot": slot, "score": r.score if r else None, "why": why,
            "chosen": chosen, "links": links_for(ev, day, hint)}


def digest_view(p: Profile, dg: CoreDigest) -> dict:
    limit = int(scoring_config()["why"]["max_total"])
    items = [_item(s.event, s.day, s.slot, s.result, s.chosen, limit) for s in dg.slots if s.event]
    horizon = [_item(ev, event_dates(ev)[0] if event_dates(ev) else None, "горизонт", r, False, limit) for ev, r in dg.horizon]
    return {"user_id": p.user_id, "weekend": dg.weekend, "title": weekend_title(dg.weekend), "items": items, "horizon": horizon}


def digest_preview(session: Session, p: Profile, today: date | None = None) -> dict:
    dg, _, _ = core_digest(session, p, today_or(p, today))
    return digest_view(p, dg)


def digest_row(session: Session, p: Profile, weekend_start: date) -> Digest:
    row = session.scalar(select(Digest).where(Digest.user_id == p.user_id, Digest.weekend_start == weekend_start))
    if row is None:
        row = Digest(user_id=p.user_id, weekend_start=weekend_start, items=[])
        session.add(row)
        session.commit()
    return row


def save_digest(session: Session, p: Profile, dg: CoreDigest, sent: bool = False) -> Digest:
    row = digest_row(session, p, date.fromisoformat(dg.weekend[0]))
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
    out = [{**event_view(ev), "score": scores[ev["id"]].score, "why": scores[ev["id"]].why_dicts(limit)} for ev in events]
    out.sort(key=lambda e: -e["score"])
    return out


# ─── план ───
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
            horizon.append({"event": event_view(ev), "status": d.status, "day": event_dates(ev)[0], "links": links_for(ev, event_dates(ev)[0])})
            continue
        wd = weekend_days(ev, weekend)
        day = d.day.isoformat() if d.day and d.day.isoformat() in wd else wd[0]
        days[day].append({"event": event_view(ev), "status": d.status, "day": day, "links": links_for(ev, day)})
    for day, items in days.items():
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
    text = plan_text({d: [it["event"] for it in items if it["status"] == "иду"] for d, items in days.items()}, weekend,
                     [h["event"] for h in horizon if h["status"] == "иду"])
    return {"weekend": weekend, "title": weekend_title(weekend), "days": days, "horizon": horizon, "text": text}


def ics_for(ev: dict, day: date | str | None) -> str:
    d = day.isoformat() if isinstance(day, date) else day
    return ics_text(ev, d, uid_domain=settings.WEB_BASE_URL.split("//")[-1].split("/")[0] or "leisure")
