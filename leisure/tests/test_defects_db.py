"""Дефекты Д1–Д3, Д6–Д13 и юзабилити 6–7 из sim/REPORT.md на реальной БД и настоящем диспетчере бота.

Диспетчер работает с поддельным Telegram из leisure.sim.fakebot (он проверяет правила Bot API: длину callback_data,
URL кнопок, «message is not modified»). Нужны БД с seed и тестовые профили 999_100_xxx, которые удаляются после теста.
Задачи воркера запускаются только для тестового профиля (подменяется выборка активных), отправка — в запись.
"""
import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from leisure.api import services
from leisure.bot import decisions as bot_decisions
from leisure.bot.onboarding import Onb, markup
from leisure.core.timeutil import weekend_for
from leisure.db.models import Decision, Digest, Event, Profile
from leisure.db.session import engine, session_factory
from leisure.sim import fakebot
from leisure.worker import schedules
from leisure.worker.messages import card_keyboard, digest_footer_keyboard
from leisure.worker.send import SendResult

from .conftest import fresh_dispatcher

UID = 999_100_001


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
    """Онбординговый профиль; после теста удаляется вместе с решениями и дайджестами."""
    services.delete_profile(db, UID)
    p = services.get_or_create_profile(db, UID, "Тест", "tester")
    services.update_profile(db, p, {"consent": True, "onboarded": True})
    yield p
    services.delete_profile(db, UID)


def _event(db, **cond) -> Event:
    q = select(Event).where(Event.status == "published")
    if cond.get("multi"):
        q = q.where(text("array_length(dates, 1) >= 2"))
    return db.scalars(q.order_by(Event.slug).limit(3)).all()[1]


def _decision(db, uid, ev) -> Decision | None:
    db.expire_all()
    return db.scalar(select(Decision).where(Decision.user_id == uid, Decision.event_id == ev.id))


class Chat:
    """Диспетчер бота + поддельный Telegram + одна карточка в чате."""

    def __init__(self, uid=UID):
        self.uid, self.world = uid, fakebot.FakeTelegram()
        self.bot = fakebot.make_bot(self.world)
        self.dp = fresh_dispatcher()

    def run(self, coro):
        return asyncio.run(coro)

    async def _send(self, text, rows):
        return await self.bot.send_message(self.uid, text, reply_markup=markup(rows) if rows else None)

    def send(self, text="card", rows=None):
        return self.run(self._send(text, rows)).message_id

    async def _feed(self, upd):
        await self.dp.feed_update(self.bot, upd)

    def press(self, mid, data) -> str:
        upd, cb_id = self.world.callback_update(self.bot, self.uid, "Тест", "tester", mid, data)
        self.run(self._feed(upd))
        return self.world.callbacks[cb_id]["toast"]

    def say(self, text):
        self.run(self._feed(self.world.message_update(self.bot, self.uid, "Тест", "tester", text)))

    def rows(self, mid):
        return [[b["text"] for b in r] for r in self.world.get(self.uid, mid).rows]

    def cbs(self, mid, text_):
        return next(b["callback_data"] for r in self.world.get(self.uid, mid).rows for b in r if b["text"].endswith(text_))

    def last_text(self):
        return self.world.last_bot_message(self.uid).text

    def state(self):
        return self.run(self.dp.fsm.get_context(self.bot, self.uid, self.uid).get_state())

    def set_state(self, st):
        self.run(self.dp.fsm.get_context(self.bot, self.uid, self.uid).set_state(st))


def _item(ev: Event, day: str) -> dict:
    return {"event": {"id": str(ev.id), "title": ev.title, "url": "https://example.org/e"}, "day": day,
            "links": {"tg": "https://t.me/share/url?x", "page": "https://leisure.example.org/e/x"}}


@pytest.fixture
def card(db, user):
    """Карточка события с несколькими датами, показанная на последний день."""
    ev = _event(db, multi=True)
    day = sorted(ev.dates)[-1]
    chat = Chat()
    rows = card_keyboard(_item(ev, day.isoformat()), url_buttons=True) + digest_footer_keyboard("https://leisure.example.org/digest", True)
    return chat, chat.send("карточка", rows), ev, day


# ── Д1, Д5 ──
def test_press_saves_card_day_and_interesting(db, card):
    chat, mid, ev, day = card
    assert chat.press(mid, chat.cbs(mid, "Иду")) == "В плане ✓ Напомню утром в день события."
    assert _decision(db, UID, ev).day == day                                    # день с карточки, а не первая дата
    assert chat.rows(mid)[0][0] == "● Иду"
    assert chat.press(mid, chat.cbs(mid, "Интересно")) == "Запомнил: буду искать похожее."
    d = _decision(db, UID, ev)
    assert d.status == "интересно" and d.day == day and chat.rows(mid)[0][3] == "● Интересно"


def test_repeated_decision_updates_day_and_resets_flags(db, user):
    ev = _event(db, multi=True)
    d1, d2 = sorted(ev.dates)[:2]
    services.set_decision(db, UID, ev, "иду", day=d1)
    d = _decision(db, UID, ev)
    d.reminded_at = datetime.now(timezone.utc)
    db.commit()
    services.set_decision(db, UID, ev, "иду", day=d2)
    d = _decision(db, UID, ev)
    assert d.day == d2 and d.reminded_at is None
    services.set_decision(db, UID, ev, "может")                                  # без дня — день не трогаем
    assert _decision(db, UID, ev).day == d2


def test_old_button_without_day_still_works(db, card):
    chat, mid, ev, day = card
    chat.press(mid, f"d:g:{ev.id}")
    assert _decision(db, UID, ev).status == "иду"


def test_all_five_decision_codes_are_handled(db, card):
    """Каждый код d:g/m/i/s/p даёт тост из TOASTS и запись в БД, без KeyError."""
    from leisure.bot.callbacks import CODES_STATUS
    assert set(CODES_STATUS.values()) == set(bot_decisions.TOASTS) == set(bot_decisions.STATUS_TITLE)
    chat, mid, ev, day = card
    for code, status in CODES_STATUS.items():
        toast = chat.press(mid, f"d:{code}:{ev.id}:{day}")
        assert toast == bot_decisions.TOASTS[status] and _decision(db, UID, ev).status == status
    assert bot_decisions.TOASTS["пропуск"] == "Понял, пропускаю."


# ── Д3 ──
def test_deleted_profile_is_not_recreated(db, card):
    chat, mid, ev, _ = card
    services.delete_profile(db, UID)
    assert chat.press(mid, chat.cbs(mid, "Иду")) == "Профиль удалён. Чтобы начать заново — /start"
    assert db.get(Profile, UID) is None and _decision(db, UID, ev) is None
    with pytest.raises(services.ProfileMissing):
        services.set_decision(db, UID, ev, "иду")
    assert db.get(Profile, UID) is None


# ── Д6, Юзабилити 6 ──
def test_miss_then_reason_keeps_links_and_footer(db, card):
    chat, mid, ev, _ = card
    toast = chat.press(mid, chat.cbs(mid, "Мимо"))
    assert "Причину можно не указывать" in toast and _decision(db, UID, ev).status == "мимо"
    rows = chat.rows(mid)
    assert rows[0][2] == "● Мимо" and rows[1] == ["Почему мимо? Можно не отвечать"] and rows[-2:] == [["Подробнее", "Другу"], ["Весь дайджест"]]
    chat.press(mid, chat.cbs(mid, "дорого"))
    assert chat.rows(mid) == [["Иду", "Может быть", "● Мимо", "Интересно"], ["Подробнее", "Другу"], ["Весь дайджест"]]
    assert _decision(db, UID, ev).reason == "дорого"
    assert chat.press(mid, "ob:noop") == ""                                        # подпись — не кнопка действия


# ── Д7 ──
def test_double_tap_is_not_an_error(db, card, caplog):
    chat, mid, ev, _ = card
    with caplog.at_level(logging.ERROR):
        for status in ("Иду", "Мимо"):
            data = chat.cbs(mid, status)
            first, second = chat.press(mid, data), chat.press(mid, data)
            assert first == second and "не так" not in second
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert not chat.world.violations


def test_other_bad_request_still_reports_error(db, card, monkeypatch, caplog):
    from aiogram.exceptions import TelegramBadRequest
    chat, mid, ev, _ = card

    async def boom(self, **kw):
        raise TelegramBadRequest(method=None, message="Bad Request: message can't be edited")

    monkeypatch.setattr("aiogram.types.Message.edit_reply_markup", boom)
    with caplog.at_level(logging.ERROR):
        assert chat.press(mid, chat.cbs(mid, "Иду")) == "Что-то пошло не так, попробуй ещё раз."
    assert [r for r in caplog.records if r.levelno >= logging.ERROR]


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


# ── Д10, Д11: задача отправки ──
THU = datetime(2026, 10, 22, 16, 5, tzinfo=timezone.utc)                                # чт 19:05 МСК


def _patch_send(monkeypatch, result_fn):
    sent = []
    monkeypatch.setattr(schedules, "_active_profiles", lambda s: [s.get(Profile, UID)])

    def fake(msgs):
        sent.append(msgs)
        return result_fn(msgs)

    monkeypatch.setattr(schedules, "send_sync", fake)
    return sent


def _row(db):
    db.expire_all()
    return db.scalar(select(Digest).where(Digest.user_id == UID))


def test_digest_counts_as_sent_if_header_and_a_card_delivered(db, user, monkeypatch, caplog):
    sent = _patch_send(monkeypatch, lambda m: SendResult(len(m) - 1, [len(m) - 1], []))
    with caplog.at_level(logging.WARNING, logger="leisure.worker"):
        assert schedules.job_send_digests(THU) == 1
    assert _row(db).sent_at is not None and len(sent) == 1
    assert "не доставлены карточки" in caplog.text


def test_digest_not_sent_if_header_lost_or_no_card(db, user, monkeypatch):
    _patch_send(monkeypatch, lambda m: SendResult(len(m) - 1, [0], []))               # заголовок потерян
    assert schedules.job_send_digests(THU) == 0 and (_row(db) is None or _row(db).sent_at is None)
    _patch_send(monkeypatch, lambda m: SendResult(1, list(range(1, len(m))), []))     # ушёл только заголовок
    assert schedules.job_send_digests(THU) == 0 and (_row(db) is None or _row(db).sent_at is None)


def test_blocked_user_is_deactivated(db, user, monkeypatch):
    _patch_send(monkeypatch, lambda m: SendResult(0, list(range(len(m))), [UID]))
    assert schedules.job_send_digests(THU) == 0
    db.expire_all()
    assert db.get(Profile, UID).active is False
    # вернулся по /start — рассылки снова включены
    chat = Chat()
    chat.say("/start")
    db.expire_all()
    assert db.get(Profile, UID).active is True


# ── Юзабилити 7 ──
def test_empty_digest_sends_one_message_once(db, user, monkeypatch):
    services.update_profile(db, user, {"interests": {c: 0 for c in user.interests}})
    sent = _patch_send(monkeypatch, lambda m: SendResult(len(m), [], []))
    assert schedules.job_send_digests(THU) == 1
    assert len(sent[0]) == 1 and sent[0][0][1].startswith("На эти выходные под твой профиль ничего не нашлось")
    assert schedules.job_send_digests(THU) == 0                                       # дважды не шлём


def test_digest_command_with_empty_profile_sends_hint(db, user):
    services.update_profile(db, user, {"interests": {c: 0 for c in user.interests}})
    chat = Chat()
    chat.say("/digest")
    assert chat.last_text().startswith("На эти выходные под твой профиль ничего не нашлось. Можно расширить интересы: /profile")


# ── Д2: напоминания и «Как прошло?» ──
def _reminder_setup(db, monkeypatch, day: date):
    ev = _event(db)
    services.set_decision(db, UID, ev, "иду", day=day)
    sent = _patch_send(monkeypatch, lambda m: SendResult(len(m), [], []))
    return ev, sent


def msk(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone(timedelta(hours=3)))


@pytest.mark.parametrize("day", ["2026-10-27", "2026-10-25", "2026-11-12"])             # вторник, воскресенье, «на горизонте»
def test_plan_today_on_any_day(db, user, monkeypatch, day):
    ev, sent = _reminder_setup(db, monkeypatch, date.fromisoformat(day))
    assert schedules.job_plan_today(msk(day + "T08:59")) == 0                           # до 09:00 тихо
    assert schedules.job_plan_today(msk(f"{day}T09:05")) == 1
    assert "План на сегодня" in sent[0][0][1] and ev.title.split()[0] in sent[0][1][1]
    assert _decision(db, UID, ev).reminded_at is not None
    assert schedules.job_plan_today(msk(f"{day}T10:05")) == 0                           # второй раз не шлём


def test_plan_today_late_press_still_reminded_and_other_day_not(db, user, monkeypatch):
    ev, sent = _reminder_setup(db, monkeypatch, date(2026, 10, 24))
    assert schedules.job_plan_today(msk("2026-10-23T09:05")) == 0                       # решение на другой день
    assert schedules.job_plan_today(msk("2026-10-24T15:00")) == 1                       # нажато после 09:00 — всё равно придёт


def test_plan_today_retries_when_delivery_failed(db, user, monkeypatch):
    ev, _ = _reminder_setup(db, monkeypatch, date(2026, 10, 24))
    _patch_send(monkeypatch, lambda m: SendResult(0, list(range(len(m))), []))
    assert schedules.job_plan_today(msk("2026-10-24T09:05")) == 0
    assert _decision(db, UID, ev).reminded_at is None


def test_how_was_it_next_day_noon_once_and_only_unrated(db, user, monkeypatch):
    ev, sent = _reminder_setup(db, monkeypatch, date(2026, 10, 27))
    assert schedules.job_how_was_it(msk("2026-10-27T13:00")) == 0                       # в день события не спрашиваем
    assert schedules.job_how_was_it(msk("2026-10-28T11:59")) == 0
    assert schedules.job_how_was_it(msk("2026-10-28T12:05")) == 1
    assert "Как прошло?" in sent[0][0][1] and _decision(db, UID, ev).feedback_asked_at is not None
    assert schedules.job_how_was_it(msk("2026-10-28T13:05")) == 0
    d = _decision(db, UID, ev)
    d.feedback_asked_at, d.rating = None, 4
    db.commit()
    assert schedules.job_how_was_it(msk("2026-10-28T14:05")) == 0                       # оценка уже есть


def test_workers_do_not_depend_on_digest_flags(db, user, monkeypatch):
    ev, sent = _reminder_setup(db, monkeypatch, date(2026, 10, 24))
    row = services.digest_row(db, user, date(2026, 10, 23))
    row.plan_sent_at = row.feedback_sent_at = datetime.now(timezone.utc)
    db.commit()
    assert schedules.job_plan_today(msk("2026-10-24T09:05")) == 1


# ── Д12, Д13: онбординг ──
def test_stale_onboarding_button_gets_reply(user):
    chat = Chat()
    mid = chat.send("старый экран", [[{"text": "утро", "callback_data": "ob:t:0"}]])
    assert chat.press(mid, "ob:t:0") == ""                                              # индикатор снят
    assert chat.last_text() == "Этот экран устарел. Начни заново: /start"
    assert chat.state() is None


def test_unknown_callback_is_answered(user):
    chat = Chat()
    mid = chat.send("x", [[{"text": "?", "callback_data": "zz:42"}]])
    assert chat.press(mid, "zz:42") == ""
    assert chat.world.callbacks["cb1"]["answered"]


def test_text_on_button_step_gets_hint_and_keeps_state(user):
    chat = Chat()
    chat.set_state(Onb.values)
    chat.say("а что тут нужно сделать?")
    assert chat.last_text() == "Здесь нужно нажать кнопку выше" and chat.state() == Onb.values.state


def test_command_on_notes_step_is_a_command_not_a_note(db, user):
    chat = Chat()
    chat.set_state(Onb.notes)
    before = db.get(Profile, UID).notes
    chat.say("/help")
    assert "/digest — подборка" in chat.last_text()                                     # ответила команда
    assert chat.state() == Onb.notes.state                                               # онбординг не завершён
    db.expire_all()
    assert db.get(Profile, UID).notes == before


def test_onboarding_has_no_areas_screen_and_goes_to_notes(user):
    chat = Chat()
    chat.set_state(Onb.aesthetics)
    mid = chat.send("эстетика", [[{"text": "Да, важна", "callback_data": "ob:a:1"}]])
    chat.press(mid, "ob:a:1")
    assert chat.state() == Onb.notes.state and "Шаг 4 из 5" in chat.world.get(UID, mid).text


# ── Д18 ──
def test_local_web_url_does_not_break_bot(db, user, monkeypatch):
    from leisure import settings
    monkeypatch.setattr(settings, "WEB_BASE_URL", "http://localhost:8000")
    chat = Chat()
    services.delete_profile(db, UID)
    chat.say("/start")                                                                   # URL-кнопка политики Telegram бы отклонил
    assert "Политика обработки данных: http://localhost:8000" in chat.last_text()
    assert not chat.world.violations


# ── statuses в upcoming_events ──
def test_upcoming_events_statuses_param(db):
    ev = _event(db)
    today = date(2026, 10, 24)
    try:
        ev.status = "draft"
        db.commit()
        default = {e["id"] for e in services.upcoming_events(db, ev.city, today)}
        with_drafts = {e["id"] for e in services.upcoming_events(db, ev.city, today, statuses=("published", "draft"))}
        only_drafts = {e["id"] for e in services.upcoming_events(db, ev.city, today, statuses=["draft"])}
        assert str(ev.id) not in default and str(ev.id) in with_drafts and str(ev.id) in only_drafts
    finally:
        ev.status = "published"
        db.commit()
