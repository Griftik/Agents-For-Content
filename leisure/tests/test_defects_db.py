"""Журнал показанного (Digest) и служебная выборка событий на реальной БД: Д8, Д9, statuses в upcoming_events.
Нужны БД с seed и тестовый профиль с id от pid (tests/ids.py), который удаляется после теста."""
import os
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select, text

from leisure.api import services
from leisure.core.timeutil import weekend_for
from leisure.db.models import Digest, Event, Profile
from leisure.db.session import engine, session_factory
from leisure.worker import schedules

from .ids import user_id

UID = user_id(0)


def _db_ok() -> bool:
    try:
        with engine().connect() as c:
            return c.execute(text("select count(*) from events")).scalar() > 0
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _db_ok(), reason="нет доступной БД с seed")


@pytest.fixture
def db():
    with session_factory()() as s:
        yield s


@pytest.fixture
def user(db):
    """Настроенный профиль; после теста удаляется вместе с решениями и журналом."""
    services.delete_profile(db, UID)
    p = services.get_or_create_profile(db, UID, "Тест", "tester")
    services.update_profile(db, p, {"consent": True, "onboarded": True})
    yield p
    services.delete_profile(db, UID)


def _event(db) -> Event:
    return db.scalars(select(Event).where(Event.status == "published").order_by(Event.slug).limit(3)).all()[1]


# ── Д8, Д9 ──
def test_save_digest_does_not_overwrite_sent_items(db, user):
    weekend = ["2026-10-23", "2026-10-24", "2026-10-25"]
    dg, _, _ = services.core_digest(db, user, date(2026, 10, 22), weekend)
    assert dg.items()
    row = services.save_digest(db, user, dg, sent=True)
    sent_items, sent_at = list(row.items), row.sent_at
    other = type(dg)(dg.weekend, dg.slots[:1], [])
    services.save_digest(db, user, other, sent=False)
    db.expire_all()
    row = db.scalar(select(Digest).where(Digest.user_id == UID))
    assert row.items == sent_items and row.sent_at == sent_at


def test_build_job_skips_sent_digest(db, user, monkeypatch):
    monkeypatch.setattr(schedules, "_active_profiles", lambda s: [s.get(Profile, UID)])
    now = datetime(2026, 10, 21, 19, 5, tzinfo=timezone.utc)                         # среда 22:05 МСК
    row = services.digest_row(db, user, date(2026, 10, 23))
    row.items, row.sent_at = [{"event_id": "marker"}], now
    db.commit()
    assert schedules.job_build_digests(now) == 0
    db.expire_all()
    assert db.scalar(select(Digest).where(Digest.user_id == UID)).items == [{"event_id": "marker"}]


def test_build_job_fills_journal_once(db, user, monkeypatch):
    monkeypatch.setattr(schedules, "_active_profiles", lambda s: [s.get(Profile, UID)])
    now = datetime(2026, 10, 21, 19, 5, tzinfo=timezone.utc)
    assert schedules.job_build_digests(now) == 1
    db.expire_all()
    row = db.scalar(select(Digest).where(Digest.user_id == UID))
    assert row is not None and row.items and row.sent_at is None


def test_decision_marks_digest_opened_and_counts(db, user):
    ev1, ev2 = db.scalars(select(Event).where(Event.status == "published").order_by(Event.slug).limit(2)).all()
    start = weekend_for(services.local_today(user))[0]
    row = services.digest_row(db, user, start)
    row.items, row.sent_at = [{"event_id": str(ev1.id)}, {"event_id": str(ev2.id)}], datetime.now(timezone.utc)
    db.commit()
    services.set_decision(db, UID, ev1, "иду")
    db.refresh(row)
    assert row.opened is True and row.decisions_count == 1
    services.set_decision(db, UID, ev2, "мимо")
    services.set_decision(db, UID, ev2, "может")                                      # повторное решение не удваивает счёт
    db.refresh(row)
    assert row.decisions_count == 2
    services.remove_decision(db, UID, ev1)
    db.refresh(row)
    assert row.decisions_count == 1


def test_decision_outside_digest_does_not_touch_stats(db, user):
    ev = _event(db)
    start = weekend_for(services.local_today(user))[0]
    row = services.digest_row(db, user, start)
    row.items, row.sent_at = [{"event_id": "other"}], datetime.now(timezone.utc)
    db.commit()
    services.set_decision(db, UID, ev, "иду")
    db.refresh(row)
    assert row.opened is False and row.decisions_count == 0


# ── statuses в upcoming_events ──
def test_upcoming_events_statuses_param(db, seed_raw):
    """Свой черновик (slug от pid), а не правка seed-события: параллельный прогон не должен видеть событие скрытым."""
    from leisure.seed.load import upsert_events

    slug = f"zz-test-draft-{os.getpid()}"
    base = next(e for e in seed_raw if "2026-10-24" in e["dates"])
    upsert_events(db, [{**base, "slug": slug, "title": "Тестовый черновик"}], status="draft")
    ev = db.scalar(select(Event).where(Event.slug == slug))
    today = date(2026, 10, 24)
    try:
        default = {e["id"] for e in services.upcoming_events(db, ev.city, today)}
        with_drafts = {e["id"] for e in services.upcoming_events(db, ev.city, today, statuses=("published", "draft"))}
        only_drafts = {e["id"] for e in services.upcoming_events(db, ev.city, today, statuses=["draft"])}
        assert str(ev.id) not in default and str(ev.id) in with_drafts and str(ev.id) in only_drafts
    finally:
        db.delete(ev)
        db.commit()
