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
from leisure.bot.onboarding import Onb
from leisure.core.timeutil import weekend_for, weekend_iso
from leisure.db.models import Decision, Digest, Event, Profile
from leisure.db.session import engine, session_factory
from leisure.worker import schedules
from leisure.worker import messages as msg
from leisure.worker.send import SendResult

from .chat import UID, Chat


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


def _same_weekend_event(db) -> Event:
    """Событие, идущее и в субботу, и в воскресенье одного уикенда (на карточке появляется ряд выбора дня)."""
    return db.scalars(select(Event).where(Event.status == "published", text("dates @> ARRAY['2026-10-24','2026-10-25']::date[]"))
                      .order_by(Event.slug).limit(2)).all()[0]


def _send_card(db, user, ev: Event, day: str) -> tuple[Chat, int]:
    weekend = weekend_iso(date.fromisoformat(day))
    item = services.card_item(db, user, ev, day, weekend)
    chat = Chat()
    return chat, chat.send(msg.card_text(item, weekend, plain_links=False), msg.card_keyboard(item, url_buttons=True))


@pytest.fixture
def card(db, user):
    """Карточка события с несколькими датами, показанная на последний день."""
    ev = _event(db, multi=True)
    day = sorted(ev.dates)[-1]
    chat, mid = _send_card(db, user, ev, day.isoformat())
    return chat, mid, ev, day


def _marked(chat, mid) -> list[str]:
    """Отмеченные кнопки решений (день — отдельный ряд, его отметку не считаем)."""
    return [b for r in chat.rows(mid) for b in r if b.startswith("● ") and b[2:] in ("Иду", "Может быть", "Интересно", "Мимо")]


# ── Д1, Д5 ──
def test_press_saves_card_day_and_interesting(db, card):
    chat, mid, ev, day = card
    assert chat.press(mid, chat.cbs(mid, "Иду")) == f"В плане: {msg.day_phrase(day.isoformat())}. Напомню утром."
    assert _decision(db, UID, ev).day == day                                    # день с карточки, а не первая дата
    assert _marked(chat, mid) == ["● Иду"]
    assert chat.press(mid, chat.cbs(mid, "Интересно")) == "Запомнил. Буду показывать похожее."
    d = _decision(db, UID, ev)
    assert d.status == "интересно" and d.day == day and _marked(chat, mid) == ["● Интересно"]


def test_day_row_changes_card_and_moves_decision(db, user):
    ev = _same_weekend_event(db)
    chat, mid = _send_card(db, user, ev, "2026-10-24")
    assert "● Сб" in chat.rows(mid)[0] and "Вс" in chat.rows(mid)[0]
    assert chat.press(mid, f"y:2:{ev.id}") == "Показываю воскресенье, 25 окт."          # решения нет — только показ
    assert "Воскресенье, 25 окт" in chat.world.get(UID, mid).text and "● Вс" in chat.rows(mid)[0]
    assert _decision(db, UID, ev) is None
    chat.press(mid, chat.cbs(mid, "Иду"))
    assert _decision(db, UID, ev).day == date(2026, 10, 25)                           # день из выбранного, а не первый
    assert chat.press(mid, f"y:1:{ev.id}") == "Перенёс в план на суббота, 24 окт."
    assert _decision(db, UID, ev).day == date(2026, 10, 24) and "Прежний ответ: иду, суббота" in chat.world.get(UID, mid).text
    assert _marked(chat, mid) == ["● Иду"] and "● Сб" in chat.rows(mid)[0]
    assert chat.press(mid, f"y:1:{ev.id}") == ""                                       # повторный тап — тихо


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
        if status == "пропуск":      # «Убрать из плана» живёт на карточках плана, а не подборки
            mid = chat.send("карточка плана", [[{"text": "Убрать из плана", "callback_data": f"d:p:{ev.id}"}]])
        toast = chat.press(mid, f"d:{code}:{ev.id}:{day}")
        assert toast == bot_decisions.toast_for(status, day) and _decision(db, UID, ev).status == status
    assert bot_decisions.TOASTS["пропуск"] == "Убрал из плана."


def test_remove_from_plan_and_rating(db, user):
    ev = _event(db)
    services.set_decision(db, UID, ev, "иду", day=date(2026, 10, 24))
    chat = Chat()
    mid = chat.send("Как прошло?", msg.rating_keyboard(str(ev.id)))
    assert chat.press(mid, f"s:4:{ev.id}") == "Оценка 4 из 5." and _decision(db, UID, ev).rating == 4
    assert "● 4 ★" in chat.rows(mid)[0] and chat.press(mid, f"s:5:{ev.id}") == "Оценка изменена: 5 из 5."
    assert chat.press(mid, f"d:p:{ev.id}") == "Убрал из плана." and _decision(db, UID, ev).status == "пропуск"
    assert chat.rows(mid) == [["1 ★", "2 ★", "3 ★", "4 ★", "● 5 ★"]]               # кнопка «Не получилось пойти» снята


# ── Д3 ──
def test_deleted_profile_is_not_recreated(db, card):
    chat, mid, ev, _ = card
    services.delete_profile(db, UID)
    assert chat.press(mid, chat.cbs(mid, "Иду")) == "Профиля больше нет. Чтобы начать заново, нажми /start."
    assert db.get(Profile, UID) is None and _decision(db, UID, ev) is None
    with pytest.raises(services.ProfileMissing):
        services.set_decision(db, UID, ev, "иду")
    assert db.get(Profile, UID) is None


# ── Д6, Юзабилити 6 ──
def test_miss_then_reason_keeps_links(db, card):
    chat, mid, ev, _ = card
    toast = chat.press(mid, chat.cbs(mid, "Мимо"))
    assert toast == "Понял, больше не покажу. Причину можно выбрать ниже, это необязательно."
    assert _decision(db, UID, ev).status == "мимо"
    rows = chat.rows(mid)
    assert ["Иду", "Может быть"] in rows and ["Интересно", "● Мимо"] in rows and rows[-1] == ["Подробнее", "Другу"]
    assert ["Почему мимо? Можно не отвечать"] in rows and ["Не моё", "Дорого", "Далеко", "Ещё…"] in rows
    chat.press(mid, f"r:m:{ev.id}")                                                    # «Ещё…» — остальные причины
    assert ["Уже был", "Не то время"] in chat.rows(mid) and ["Не моё", "Дорого", "Далеко", "Ещё…"] not in chat.rows(mid)
    assert chat.press(mid, chat.cbs(mid, "Не то время")) == "Учту."
    assert chat.rows(mid)[-1] == ["Подробнее", "Другу"] and not any("Почему" in b for r in chat.rows(mid) for b in r)
    assert _decision(db, UID, ev).reason == "не в это время"
    assert chat.press(mid, "ob:noop") == ""                                            # подпись — не кнопка действия


# ── Д7 ──
def test_double_tap_is_not_an_error(db, card, caplog):
    chat, mid, ev, _ = card
    with caplog.at_level(logging.ERROR):
        for status in ("Иду", "Мимо"):
            data = chat.cbs(mid, status)
            first, second = chat.press(mid, data), chat.press(mid, data)
            assert first and second == ""                                              # повторное нажатие — без текста
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert not chat.world.violations


def test_other_bad_request_still_reports_error(db, card, monkeypatch, caplog):
    from aiogram.exceptions import TelegramBadRequest
    chat, mid, ev, _ = card

    async def boom(self, **kw):
        raise TelegramBadRequest(method=None, message="Bad Request: message can't be edited")

    monkeypatch.setattr("aiogram.types.Message.edit_reply_markup", boom)
    with caplog.at_level(logging.ERROR):
        assert chat.press(mid, chat.cbs(mid, "Иду")) == "Не удалось сохранить ответ. Нажми ещё раз."
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
    assert len(sent[0]) == 1 and "На эти выходные под твой профиль ничего не нашлось" in sent[0][0][1]
    assert schedules.job_send_digests(THU) == 0                                       # дважды не шлём


def test_digest_command_with_empty_profile_sends_hint(db, user):
    services.update_profile(db, user, {"interests": {c: 0 for c in user.interests}})
    chat = Chat()
    chat.say("/digest")
    assert "На эти выходные под твой профиль ничего не нашлось" in chat.last_text()
    assert chat.world.last_bot_message(UID).buttons()[-1]["text"] == "Мои интересы"


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


# ── Д12, Д13: устаревшие экраны и текст ──
def test_stale_or_unknown_onboarding_button_gets_reply(user):
    chat = Chat()
    mid = chat.send("старый экран", [[{"text": "что-то", "callback_data": "ob:zzz"}]])
    assert chat.press(mid, "ob:zzz") == "Этот экран устарел. Открой актуальный: /start."          # индикатор снят
    assert chat.state() is None


def test_onboarding_button_without_profile_says_profile_is_gone(db, user):
    chat = Chat()
    mid = chat.send("экран", [[{"text": "утро", "callback_data": "ob:t:0"}]])
    services.delete_profile(db, UID)
    assert chat.press(mid, "ob:t:0") == "Профиля больше нет. Чтобы начать заново, нажми /start."
    assert db.get(Profile, UID) is None                                                           # профиль не воскрешён


def test_unknown_callback_is_answered(user):
    chat = Chat()
    mid = chat.send("x", [[{"text": "?", "callback_data": "zz:42"}]])
    assert chat.press(mid, "zz:42") == "Этот экран устарел. Открой актуальный: /start."
    assert chat.world.callbacks["cb1"]["answered"]


def test_free_text_gets_a_reply(db, user):
    chat = Chat()
    chat.say("а что тут нужно сделать?")
    assert chat.last_text().startswith("Я понимаю кнопки и команды")
    p = db.get(Profile, UID)
    p.onboarded_at = None
    db.commit()
    chat.say("привет")
    assert chat.last_text().startswith("Здесь нужно нажать кнопку под сообщением")
    chat.say("/нет_такой")
    assert chat.last_text() == "Такой команды нет. Список: /help."


def test_command_on_notes_step_is_a_command_not_a_note(db, user):
    chat = Chat()
    chat.set_state(Onb.notes)
    before = db.get(Profile, UID).notes
    chat.say("/help")
    assert "/digest — подборка" in chat.last_text()                                     # ответила команда
    assert chat.state() == Onb.notes.state                                               # ожидание заметки не сбито
    db.expire_all()
    assert db.get(Profile, UID).notes == before


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
