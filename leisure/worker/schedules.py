"""Расписание воркера (п. 8 спеки), APScheduler.

- среда 22:00 МСК — пересчёт и сборка дайджестов для всех активных профилей (предпросмотр в админке);
- каждый час :00 — отправка дайджеста тем, у кого по их tz наступило время (digest_day/digest_hour, по
  умолчанию чт 19:00) и дайджест на этот уикенд ещё не отправлен — пропущенный час досылается позже;
- каждый час :00 — «План на сегодня» (каждый день с 09:00 по tz, если на сегодня есть «иду») и «Как прошло?»
  (с 12:00 по tz на следующий день после события, по каждому «иду» без оценки). Флаги стоят на самом решении
  (Decision.reminded_at / feedback_asked_at), а не на дайджесте.

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
from leisure.core.timeutil import weekend_for, weekend_iso
from leisure.db.models import Profile
from leisure.db.session import session_factory
from leisure.worker.messages import (card_keyboard, card_text, digest_head_keyboard, digest_head_text, how_was_it_text,
                                     plan_item_keyboard, plan_today_text, rating_keyboard)
from leisure.worker.send import SendResult, send_sync

log = logging.getLogger("leisure.worker")
MAX_MESSAGES_PER_DIGEST = 7  # заголовок + карточки
PLAN_HOUR = 9        # «План на сегодня» — каждый день с 09:00 по tz
FEEDBACK_HOUR = 12   # «Как прошло?» — с 12:00 по tz на следующий день после события


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
            row = services.digest_row(s, p, date.fromisoformat(weekend_iso(local.date())[0]))
            if row.sent_at is not None:
                return False  # уже отправлено (например, при онбординге): журнал «что показывали» не трогаем
            dg, _, _ = services.core_digest(s, p, local.date(), now=now_utc)
            services.save_digest(s, p, dg, sent=False)
            return True
        n = _for_each_profile(s, now_utc, build)
    log.info("собрано дайджестов: %d", n)
    return n


def digest_messages(p: Profile, view: dict, first: bool = False) -> list[tuple[int, str, list | None]]:
    """Заголовок с кнопками («Весь дайджест», «Мой план», у первой подборки «Уточнить под себя») + карточки.

    Пустая подборка — один заголовок с текстом T-DIGEST-EMPTY. При WEB_BASE_URL=localhost URL-кнопок нет:
    «Весь дайджест» и ссылки карточек уходят текстом."""
    items = (view["items"] + view["horizon"])[: MAX_MESSAGES_PER_DIGEST - 1]
    n_main = min(len(view["items"]), len(items))
    web_ok = services.web_links_enabled()
    web = f"{settings.WEB_BASE_URL.rstrip('/')}/digest"
    head = digest_head_text(view["title"], n_main, len(items) - n_main, p.name, first)
    if not web_ok:
        head += f"\nВесь дайджест: {escape(web)}"
    msgs = [(p.user_id, head, digest_head_keyboard(web, first=first, empty=not items, url_buttons=web_ok))]
    for it in items:
        msgs.append((p.user_id, card_text(it, view["weekend"], plain_links=not web_ok), card_keyboard(it, url_buttons=web_ok)))
    return msgs


def _handle_blocked(s, res: SendResult) -> None:
    """Заблокировавшим бота выключаем рассылки (вернутся по /start)."""
    for uid in res.blocked:
        if services.set_active(s, uid, False):
            log.info("пользователь %s заблокировал бота — рассылки выключены", uid)


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
            dg, _, _ = services.core_digest(s, p, local.date(), weekend, now=now_utc)
            view = services.digest_view(p, dg, services.decision_map(s, p.user_id))
            if not dg.items():
                log.info("пользователю %s нечего отправить на %s: шлю сообщение о пустой подборке", p.user_id, weekend[0])
            msgs = digest_messages(p, view)
            res = send_sync(msgs)
            _handle_blocked(s, res)
            # подборка отправлена, если ушёл заголовок и хотя бы одна карточка (пустая — если ушло её единственное сообщение)
            ok = 0 not in res.undelivered and (res.sent >= 2 or len(msgs) == 1)
            if not ok:
                return False
            if res.undelivered:
                log.warning("пользователю %s не доставлены карточки подборки %s: сообщения %s из %d", p.user_id, weekend[0],
                            res.undelivered, len(msgs))
            services.save_digest(s, p, dg, sent=True)
            return True
        n = _for_each_profile(s, now_utc, send)
    log.info("дайджесты отправлены: %d", n)
    return n


def job_plan_today(now_utc: datetime | None = None) -> int:
    """Каждый день с 09:00 по tz: «План на сегодня» тем, у кого на сегодня есть «иду» без напоминания (в том числе
    в будни и на события «на горизонте»). Флаг — на решении; «иду», нажатое позже, получит напоминание на следующем запуске."""
    now_utc = now_utc or datetime.now(timezone.utc)
    with session_factory()() as s:
        def send(p, local):
            if local.hour < PLAN_HOUR:
                return False
            decs = services.decisions_to_remind(s, p.user_id, local.date())
            plan = services.day_plan(decs, local.date())
            today = local.date().isoformat()
            items = plan["days"][today]
            text = plan_today_text(plan, today)
            if not text:
                return False
            msgs = [(p.user_id, text, None)]
            for it in items:
                msgs.append((p.user_id, f"<b>{escape(it['event']['title'])}</b>", plan_item_keyboard(it)))
            res = send_sync(msgs)
            _handle_blocked(s, res)
            if 0 in res.undelivered:
                return False
            shown = {it["event"]["id"] for it in items}
            for d in decs:
                if str(d.event_id) in shown:
                    d.reminded_at = now_utc
            s.commit()
            return True
        n = _for_each_profile(s, now_utc, send)
    log.info("планов на сегодня отправлено: %d", n)
    return n


def job_how_was_it(now_utc: datetime | None = None) -> int:
    """С 12:00 по tz на следующий день после события: «Как прошло?» по каждому «иду» без оценки; один раз на решение."""
    now_utc = now_utc or datetime.now(timezone.utc)
    with session_factory()() as s:
        def send(p, local):
            if local.hour < FEEDBACK_HOUR:
                return False
            decs = [d for d in services.decisions_to_ask(s, p.user_id, local.date() - timedelta(days=1))
                    if d.event is not None]
            if not decs:
                return False
            msgs = [(p.user_id, how_was_it_text(d.event.as_core(), d.day.isoformat() if d.day else None), rating_keyboard(str(d.event_id)))
                    for d in decs]
            res = send_sync(msgs)
            _handle_blocked(s, res)
            for i, d in enumerate(decs):
                if i not in res.undelivered:
                    d.feedback_asked_at = now_utc
            s.commit()
            return res.sent > 0
        n = _for_each_profile(s, now_utc, send)
    log.info("«как прошло» отправлено: %d", n)
    return n


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    services.warn_local_web_url()
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
