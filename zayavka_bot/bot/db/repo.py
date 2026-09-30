"""Операции с БД. Каждая функция — своя короткая транзакция."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, update

from bot.db.models import Answer, Event, Lead, ScheduledJob, User, utcnow
from bot.db.session import session


# --- users ----------------------------------------------------------------
async def get_user(user_id: int) -> User | None:
    async with session() as s:
        return await s.get(User, user_id)


async def upsert_user(
    user_id: int, username: str | None, first_name: str | None,
    source: str | None = None, ref: str | None = None,
) -> tuple[User, bool]:
    """Создать или обновить. Источник пишется только при первом старте. Возвращает (user, created)."""
    async with session() as s:
        u = await s.get(User, user_id)
        created = u is None
        if u is None:
            u = User(id=user_id, source=source or "direct", ref=ref)
            s.add(u)
        elif u.deleted_at is not None:
            # человек удалил данные и вернулся — снова живой пользователь, источник прежний
            u.deleted_at = None
        u.username = username
        u.first_name = first_name
        u.last_seen_at = utcnow()
        await s.commit()
        return u, created


async def set_stage(user_id: int, stage: str | None) -> None:
    async with session() as s:
        await s.execute(update(User).where(User.id == user_id).values(stage=stage, last_seen_at=utcnow()))
        await s.commit()


async def set_nurture(user_id: int, enabled: bool) -> None:
    async with session() as s:
        await s.execute(update(User).where(User.id == user_id).values(nurture_enabled=enabled))
        await s.commit()


# --- answers --------------------------------------------------------------
async def save_answer(user_id: int, q_code: str, a_code: str) -> None:
    """Перезапись при повторном ответе (после «Назад»)."""
    async with session() as s:
        a = (await s.execute(
            select(Answer).where(Answer.user_id == user_id, Answer.q_code == q_code)
        )).scalar_one_or_none()
        if a is None:
            s.add(Answer(user_id=user_id, q_code=q_code, a_code=a_code))
        else:
            a.a_code = a_code
            a.answered_at = utcnow()
        await s.commit()


async def delete_answers(user_id: int, q_codes: list[str] | None = None) -> None:
    async with session() as s:
        q = delete(Answer).where(Answer.user_id == user_id)
        if q_codes is not None:
            q = q.where(Answer.q_code.in_(q_codes))
        await s.execute(q)
        await s.commit()


async def get_answers(user_id: int) -> dict[str, str]:
    async with session() as s:
        rows = (await s.execute(select(Answer).where(Answer.user_id == user_id))).scalars()
        return {a.q_code: a.a_code for a in rows}


# --- leads ----------------------------------------------------------------
async def get_lead(user_id: int) -> Lead | None:
    async with session() as s:
        return await s.get(Lead, user_id)


async def update_lead(user_id: int, **fields: Any) -> Lead:
    async with session() as s:
        lead = await s.get(Lead, user_id)
        if lead is None:
            lead = Lead(user_id=user_id)
            s.add(lead)
        for k, v in fields.items():
            setattr(lead, k, v)
        lead.updated_at = utcnow()
        await s.commit()
        return lead


async def forget_user(user_id: int) -> None:
    """/delete_me: телефон, имя, компания, ответы удаляются; события остаются обезличенной статистикой."""
    async with session() as s:
        await s.execute(delete(Answer).where(Answer.user_id == user_id))
        await s.execute(update(Lead).where(Lead.user_id == user_id).values(
            phone=None, company=None, consent_at=None, report_path=None, report_json=None,
            status="deleted", updated_at=utcnow(),
        ))
        await s.execute(update(User).where(User.id == user_id).values(
            username=None, first_name=None, stage=None, nurture_enabled=False, deleted_at=utcnow(),
        ))
        await s.execute(update(ScheduledJob).where(
            ScheduledJob.user_id == user_id, ScheduledJob.status == "pending"
        ).values(status="cancelled"))
        await s.commit()


# --- events ---------------------------------------------------------------
async def log_event(user_id: int | None, name: str, **payload: Any) -> None:
    async with session() as s:
        if user_id is not None and "source" not in payload:
            u = await s.get(User, user_id)
            payload["source"] = u.source if u else "direct"
        s.add(Event(user_id=user_id, name=name, payload=payload))
        await s.commit()


async def events_since(since: datetime) -> list[Event]:
    async with session() as s:
        return list((await s.execute(select(Event).where(Event.ts >= since).order_by(Event.id))).scalars())


async def contacted_since(since: datetime) -> list[Lead]:
    async with session() as s:
        return list((await s.execute(select(Lead).where(Lead.contacted_at >= since))).scalars())


# --- scheduled jobs -------------------------------------------------------
async def schedule(user_id: int | None, kind: str, delay: timedelta, **payload: Any) -> None:
    async with session() as s:
        s.add(ScheduledJob(user_id=user_id, kind=kind, run_at=utcnow() + delay, payload=payload))
        await s.commit()


async def cancel_jobs(user_id: int, kinds: list[str]) -> None:
    async with session() as s:
        await s.execute(update(ScheduledJob).where(
            ScheduledJob.user_id == user_id, ScheduledJob.kind.in_(kinds),
            ScheduledJob.status == "pending",
        ).values(status="cancelled"))
        await s.commit()


async def take_due_jobs(limit: int = 50) -> list[ScheduledJob]:
    """Забрать созревшие задания и сразу пометить done (один процесс — гонок нет)."""
    async with session() as s:
        jobs = list((await s.execute(
            select(ScheduledJob).where(
                ScheduledJob.status == "pending", ScheduledJob.run_at <= utcnow()
            ).order_by(ScheduledJob.run_at).limit(limit)
        )).scalars())
        for j in jobs:
            j.status = "done"
        await s.commit()
        return jobs


async def mark_job(job_id: int, status: str, note: str | None = None) -> None:
    async with session() as s:
        await s.execute(update(ScheduledJob).where(ScheduledJob.id == job_id).values(status=status, note=note))
        await s.commit()


async def lead_snapshot(user_id: int) -> dict[str, Any]:
    """Всё о лиде одним словарём — для CRM-синка."""
    async with session() as s:
        u = await s.get(User, user_id)
        lead = await s.get(Lead, user_id)
        answers = {a.q_code: a.a_code for a in (await s.execute(
            select(Answer).where(Answer.user_id == user_id))).scalars()}
    if u is None:
        return {}
    booking = await _first_event_ts(user_id, "booking_link_clicked")
    return {
        "created_at": _fmt(lead.created_at if lead else u.created_at),
        "user_id": u.id,
        "name": u.first_name,
        "username": u.username,
        "phone": lead.phone if lead else None,
        "company": lead.company if lead else None,
        "source": u.source + (f":{u.ref}" if u.ref else ""),
        "answers": answers,
        "score": lead.score if lead else None,
        "segment": lead.segment if lead else None,
        "session_type": lead.session_type if lead else None,
        "verdict": lead.verdict if lead else None,
        "booking_at": _fmt(booking),
        "contacted_at": _fmt(lead.contacted_at if lead else None),
        "status": (lead.status if lead else None) or u.stage,
    }


async def _first_event_ts(user_id: int, name: str) -> datetime | None:
    async with session() as s:
        return (await s.execute(
            select(Event.ts).where(Event.user_id == user_id, Event.name == name).order_by(Event.id).limit(1)
        )).scalar_one_or_none()


def _fmt(dt: datetime | None) -> str | None:
    return (dt + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M") if dt else None  # МСК для таблицы
