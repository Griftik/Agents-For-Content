"""Расписание воркера (п. 8 спеки), APScheduler.

- среда 22:00 МСК — пересчёт и сборка дайджестов для всех активных профилей (предпросмотр в админке);
- каждый час :00 — отправка дайджеста тем, у кого по их tz наступило время (digest_day/digest_hour, по
  умолчанию чт 19:00) и дайджест на этот уикенд ещё не отправлен — пропущенный час досылается позже;
- каждый час :00 — «План на сегодня» (сб с 09:00 по tz) и «Как прошло?» (пн с 12:00 по tz), по одному разу.

Ошибка у одного пользователя не останавливает рассылку остальным.
Запуск: python -m leisure.worker.schedules
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from html import escape
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from leisure import settings
from leisure.api import services
from leisure.core.timeutil import weekend_for
from leisure.db.models import Decision, Profile
from leisure.db.session import session_factory
from leisure.worker.messages import (card_keyboard, card_text, digest_footer_keyboard, digest_header, how_was_it_text,
                                     plan_item_keyboard, plan_today_text, rating_keyboard)
from leisure.worker.send import send_sync

log = logging.getLogger("leisure.worker")
MAX_MESSAGES_PER_DIGEST = 7  # заголовок + карточки
PLAN_HOUR, PLAN_ISO_DAY = 9, 6          # суббота с 09:00
FEEDBACK_HOUR, FEEDBACK_ISO_DAY = 12, 1  # понедельник с 12:00


def _local_now(tz: str, now_utc: datetime) -> datetime:
    try:
        return now_utc.astimezone(ZoneInfo(tz or settings.DEFAULT_TZ))
    except Exception:  # noqa: BLE001
        return now_utc.astimezone(ZoneInfo(settings.DEFAULT_TZ))


def _active_profiles(session):
    return session.scalars(select(Profile).where(Profile.active.is_(True), Profile.onboarded_at.is_not(None))).all()


def due_weekend(local_now: datetime, digest_day: int, digest_hour: int) -> list[str] | None:
    """Уикенд, для которого дайджест уже пора отправить: последняя наступившая отметка (день ISO, час)
    определяет уикенд; если он уже прошёл — None."""
    delta = (local_now.isoweekday() - digest_day) % 7
    due = (local_now - timedelta(days=delta)).replace(hour=digest_hour, minute=0, second=0, microsecond=0)
    if due > local_now:
        due -= timedelta(days=7)
    weekend = weekend_for(due.date())
    if local_now.date() > weekend[2]:
        return None
    return [d.isoformat() for d in weekend]


def _for_each_profile(session, now_utc: datetime, fn) -> int:
    """fn(profile, local_now) → bool; исключения логируются по пользователю и не валят остальных."""
    n = 0
    for p in _active_profiles(session):
        try:
            if fn(p, _local_now(p.tz, now_utc)):
                n += 1
        except Exception:  # noqa: BLE001
            session.rollback()
            log.exception("пользователь %s: ошибка, пропускаю", p.user_id)
    return n


def job_build_digests(now_utc: datetime | None = None) -> int:
    """Среда: собрать дайджесты на предстоящий уикенд, не отправляя."""
    now_utc = now_utc or datetime.now(timezone.utc)
    with session_factory()() as s:
        def build(p, local):
            dg, _, _ = services.core_digest(s, p, local.date())
            services.save_digest(s, p, dg, sent=False)
            return True
        n = _for_each_profile(s, now_utc, build)
    log.info("собрано дайджестов: %d", n)
    return n


def digest_messages(p: Profile, view: dict) -> list[tuple[int, str, list | None]]:
    items = (view["items"] + view["horizon"])[: MAX_MESSAGES_PER_DIGEST - 1]
    msgs = [(p.user_id, digest_header(view["title"], len(items), p.name), None)]
    for it in items:
        msgs.append((p.user_id, card_text(it, view["weekend"]), card_keyboard(it)))
    web = f"{settings.WEB_BASE_URL.rstrip('/')}/digest"
    msgs[-1] = (msgs[-1][0], msgs[-1][1], (msgs[-1][2] or []) + digest_footer_keyboard(web))
    return msgs


def job_send_digests(now_utc: datetime | None = None) -> int:
    """Каждый час: кому пора и ещё не отправлено — собрать свежий дайджест, отправить, отметить."""
    now_utc = now_utc or datetime.now(timezone.utc)
    with session_factory()() as s:
        def send(p, local):
            weekend = due_weekend(local, p.digest_day, p.digest_hour)
            if weekend is None:
                return False
            row = services.digest_row(s, p, date.fromisoformat(weekend[0]))
            if row.sent_at is not None:
                return False
            dg, _, _ = services.core_digest(s, p, local.date(), weekend)
            if not dg.items():
                log.info("пользователю %s нечего отправить на %s", p.user_id, weekend[0])
                return False
            view = services.digest_view(p, dg)
            if not send_sync(digest_messages(p, view)):
                return False
            services.save_digest(s, p, dg, sent=True)
            return True
        n = _for_each_profile(s, now_utc, send)
    log.info("дайджесты отправлены: %d", n)
    return n


def job_plan_today(now_utc: datetime | None = None) -> int:
    """Суббота с 09:00 по tz: «План на сегодня» тем, у кого есть «иду» на сегодня; один раз за уикенд."""
    now_utc = now_utc or datetime.now(timezone.utc)
    with session_factory()() as s:
        def send(p, local):
            if local.isoweekday() != PLAN_ISO_DAY or local.hour < PLAN_HOUR:
                return False
            weekend = weekend_for(local.date())
            row = services.digest_row(s, p, weekend[0])
            if row.plan_sent_at is not None:
                return False
            plan = services.plan(s, p, local.date())
            today = local.date().isoformat()
            text = plan_today_text(plan, today)
            row.plan_sent_at = now_utc  # отмечаем и пустой план — повторно не проверяем
            s.commit()
            if not text:
                return False
            msgs = [(p.user_id, text, None)]
            for it in [i for i in plan["days"].get(today, []) if i["status"] == "иду"]:
                msgs.append((p.user_id, f"<b>{escape(it['event']['title'])}</b>", plan_item_keyboard(it)))
            return bool(send_sync(msgs))
        n = _for_each_profile(s, now_utc, send)
    log.info("планов на сегодня отправлено: %d", n)
    return n


def job_how_was_it(now_utc: datetime | None = None) -> int:
    """Понедельник с 12:00 по tz: «Как прошло?» по каждому «иду» прошедшего уикенда без оценки; один раз."""
    now_utc = now_utc or datetime.now(timezone.utc)
    with session_factory()() as s:
        def send(p, local):
            if local.isoweekday() != FEEDBACK_ISO_DAY or local.hour < FEEDBACK_HOUR:
                return False
            monday = local.date()
            fri, sun = monday - timedelta(days=3), monday - timedelta(days=1)
            row = services.digest_row(s, p, fri)
            if row.feedback_sent_at is not None:
                return False
            decs = s.scalars(select(Decision).where(Decision.user_id == p.user_id, Decision.status == "иду",
                                                    Decision.day >= fri, Decision.day <= sun, Decision.rating.is_(None))).all()
            row.feedback_sent_at = now_utc
            s.commit()
            msgs = [(p.user_id, how_was_it_text(d.event.as_core()), rating_keyboard(str(d.event_id)))
                    for d in decs if d.event is not None]
            return bool(msgs) and bool(send_sync(msgs))
        n = _for_each_profile(s, now_utc, send)
    log.info("«как прошло» отправлено: %d", n)
    return n


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    tz = ZoneInfo(settings.DEFAULT_TZ)
    sched = BlockingScheduler(timezone=tz, job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600})
    sched.add_job(job_build_digests, CronTrigger(day_of_week="wed", hour=22, minute=0, timezone=tz), id="build_digests")
    sched.add_job(job_send_digests, CronTrigger(minute=0, timezone=tz), id="send_digests")
    sched.add_job(job_plan_today, CronTrigger(minute=0, timezone=tz), id="plan_today")
    sched.add_job(job_how_was_it, CronTrigger(minute=0, timezone=tz), id="how_was_it")
    log.info("воркер запущен, tz=%s", settings.DEFAULT_TZ)
    sched.start()


if __name__ == "__main__":
    main()
