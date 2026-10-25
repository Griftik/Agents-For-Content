"""Служебные задачи воркера (APScheduler). Рассылок больше нет (docs/PIVOT-PWA.md, версия 2): человек сам открывает приложение,
лента всегда актуальна. Остаётся журнал показанного: по средам в 22:00 МСК собираются подборки на предстоящий уикенд для всех
настроенных профилей (предпросмотр в админке, статистика «показано / открыто»). Сбор событий — отдельный процесс (collectors).

Ошибка у одного профиля не останавливает остальных. Запуск: python -m leisure.worker.schedules
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from leisure import settings
from leisure.api import services
from leisure.core.timeutil import weekend_for, weekend_iso
from leisure.db.models import Profile
from leisure.db.session import session_factory

log = logging.getLogger("leisure.worker")


def _local_now(tz: str, now_utc: datetime) -> datetime:
    try:
        return now_utc.astimezone(ZoneInfo(tz or settings.DEFAULT_TZ))
    except Exception:  # noqa: BLE001
        return now_utc.astimezone(ZoneInfo(settings.DEFAULT_TZ))


def _active_profiles(session):
    return session.scalars(select(Profile).where(Profile.active.is_(True), Profile.onboarded_at.is_not(None))).all()


def due_weekend(local_now: datetime, digest_day: int, digest_hour: int) -> list[str] | None:
    """Уикенд, для которого отметка «показано» уже наступила: последняя наступившая отметка (день ISO, час) определяет уикенд;
    если он уже прошёл — None. Оставлено для журнала и симулятора."""
    delta = (local_now.isoweekday() - digest_day) % 7
    due = (local_now - timedelta(days=delta)).replace(hour=digest_hour, minute=0, second=0, microsecond=0)
    if due > local_now:
        due -= timedelta(days=7)
    weekend = weekend_for(due.date())
    if local_now.date() > weekend[2]:
        return None
    return [d.isoformat() for d in weekend]


def _for_each_profile(session, now_utc: datetime, fn, profiles=None) -> int:
    """fn(profile, local_now) → bool; исключения логируются по профилю и не валят остальных."""
    n = 0
    for p in (_active_profiles(session) if profiles is None else profiles(session)):
        try:
            if fn(p, _local_now(p.tz, now_utc)):
                n += 1
        except Exception:  # noqa: BLE001
            session.rollback()
            log.exception("профиль %s: ошибка, пропускаю", p.user_id)
    return n


def job_build_digests(now_utc: datetime | None = None) -> int:
    """Среда: собрать подборки на предстоящий уикенд в журнал (Digest), ничего не отправляя."""
    now_utc = now_utc or datetime.now(timezone.utc)
    with session_factory()() as s:
        def build(p, local):
            row = services.digest_row(s, p, date.fromisoformat(weekend_iso(local.date())[0]))
            if row.sent_at is not None:
                return False  # уже зафиксировано как показанное: журнал не трогаем
            dg, _, _ = services.core_digest(s, p, local.date(), now=now_utc)
            services.save_digest(s, p, dg, sent=False)
            return True
        n = _for_each_profile(s, now_utc, build)
    log.info("собрано подборок в журнал: %d", n)
    return n


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    tz = ZoneInfo(settings.DEFAULT_TZ)
    sched = BlockingScheduler(timezone=tz, job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600})
    sched.add_job(job_build_digests, CronTrigger(day_of_week="wed", hour=22, minute=0, timezone=tz), id="build_digests")
    log.info("воркер запущен, tz=%s", settings.DEFAULT_TZ)
    sched.start()


if __name__ == "__main__":
    main()
