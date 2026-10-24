"""Расписание воркера (п. 8 спеки), APScheduler.

- среда 22:00 МСК — пересчёт и сборка дайджестов для всех активных профилей (предпросмотр в админке);
- каждый час :00 — отправка дайджеста тем, у кого по их tz сейчас digest_day/digest_hour (по умолчанию чт 19:00);
- каждый час :00 — «План на сегодня» (сб 09:00 по tz) и «Как прошло?» (пн 12:00 по tz).

Запуск: python -m leisure.worker.schedules
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from leisure import settings
from leisure.api import services
from leisure.db.models import Decision, Digest, Profile
from leisure.db.session import session_factory
from leisure.worker.messages import (card_keyboard, card_text, digest_footer_keyboard, digest_header, how_was_it_text,
                                     plan_item_keyboard, plan_today_text, rating_keyboard)
from leisure.worker.send import send_sync

log = logging.getLogger("leisure.worker")
MAX_MESSAGES_PER_DIGEST = 7  # заголовок + карточки
PLAN_HOUR, PLAN_ISO_DAY = 9, 6      # суббота 09:00
FEEDBACK_HOUR, FEEDBACK_ISO_DAY = 12, 1  # понедельник 12:00


def _local_now(tz: str, now_utc: datetime) -> datetime:
    try:
        return now_utc.astimezone(ZoneInfo(tz or settings.DEFAULT_TZ))
    except Exception:  # noqa: BLE001
        return now_utc.astimezone(ZoneInfo(settings.DEFAULT_TZ))


def _active_profiles(session):
    return session.scalars(select(Profile).where(Profile.active.is_(True), Profile.onboarded_at.is_not(None))).all()


def job_build_digests(now_utc: datetime | None = None) -> int:
    """Среда: собрать дайджесты на предстоящий уикенд, не отправляя."""
    now_utc = now_utc or datetime.now(ZoneInfo("UTC"))
    n = 0
    with session_factory()() as s:
        for p in _active_profiles(s):
            today = _local_now(p.tz, now_utc).date()
            dg, _, _ = services.core_digest(s, p, today)
            services.save_digest(s, p, dg, sent=False)
            n += 1
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
    """Каждый час: кому по локальному времени пора — собрать свежий дайджест, сохранить и отправить."""
    now_utc = now_utc or datetime.now(ZoneInfo("UTC"))
    sent_users = 0
    with session_factory()() as s:
        for p in _active_profiles(s):
            local = _local_now(p.tz, now_utc)
            if local.isoweekday() != p.digest_day or local.hour != p.digest_hour:
                continue
            dg, _, _ = services.core_digest(s, p, local.date())
            ws = date.fromisoformat(dg.weekend[0])
            existing = s.scalar(select(Digest).where(Digest.user_id == p.user_id, Digest.weekend_start == ws))
            if existing is not None and existing.sent_at is not None:
                continue
            if not dg.items():
                log.info("пользователю %s нечего отправить", p.user_id)
                continue
            view = services.digest_view(p, dg)
            if send_sync(digest_messages(p, view)):
                services.save_digest(s, p, dg, sent=True)
                sent_users += 1
    log.info("дайджесты отправлены: %d", sent_users)
    return sent_users


def job_plan_today(now_utc: datetime | None = None) -> int:
    """Суббота 09:00 по tz: «План на сегодня» тем, у кого есть «иду» на сегодня."""
    now_utc = now_utc or datetime.now(ZoneInfo("UTC"))
    n = 0
    with session_factory()() as s:
        for p in _active_profiles(s):
            local = _local_now(p.tz, now_utc)
            if local.isoweekday() != PLAN_ISO_DAY or local.hour != PLAN_HOUR:
                continue
            plan = services.plan(s, p.user_id, local.date())
            today = local.date().isoformat()
            text = plan_today_text(plan, today)
            if not text:
                continue
            msgs = [(p.user_id, text, None)]
            for it in [i for i in plan["days"].get(today, []) if i["status"] == "иду"]:
                msgs.append((p.user_id, it["event"]["title"], plan_item_keyboard(it)))
            n += 1 if send_sync(msgs) else 0
    log.info("планов на сегодня отправлено: %d", n)
    return n


def job_how_was_it(now_utc: datetime | None = None) -> int:
    """Понедельник 12:00 по tz: «Как прошло?» по каждому «иду» прошедшего уикенда без оценки."""
    now_utc = now_utc or datetime.now(ZoneInfo("UTC"))
    n = 0
    with session_factory()() as s:
        for p in _active_profiles(s):
            local = _local_now(p.tz, now_utc)
            if local.isoweekday() != FEEDBACK_ISO_DAY or local.hour != FEEDBACK_HOUR:
                continue
            monday = local.date()
            fri, sun = monday - timedelta(days=3), monday - timedelta(days=1)
            decs = s.scalars(select(Decision).where(Decision.user_id == p.user_id, Decision.status == "иду",
                                                    Decision.day >= fri, Decision.day <= sun, Decision.rating.is_(None))).all()
            msgs = []
            for d in decs:
                if d.event is None:
                    continue
                msgs.append((p.user_id, how_was_it_text(d.event.as_core()), rating_keyboard(str(d.event_id))))
            if msgs:
                n += 1 if send_sync(msgs) else 0
    log.info("«как прошло» отправлено: %d", n)
    return n


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    tz = ZoneInfo(settings.DEFAULT_TZ)
    sched = BlockingScheduler(timezone=tz)
    sched.add_job(job_build_digests, CronTrigger(day_of_week="wed", hour=22, minute=0, timezone=tz), id="build_digests")
    sched.add_job(job_send_digests, CronTrigger(minute=0, timezone=tz), id="send_digests")
    sched.add_job(job_plan_today, CronTrigger(minute=0, timezone=tz), id="plan_today")
    sched.add_job(job_how_was_it, CronTrigger(minute=0, timezone=tz), id="how_was_it")
    log.info("воркер запущен, tz=%s", settings.DEFAULT_TZ)
    sched.start()


if __name__ == "__main__":
    main()
