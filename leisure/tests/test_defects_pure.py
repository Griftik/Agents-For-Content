"""Дефекты Д1–Д15, Д18 и юзабилити 6–7 из sim/REPORT.md: проверки без БД (чистые функции, отправка, скоринг)."""
import asyncio
import logging
from datetime import date, datetime

import pytest
from aiogram.exceptions import TelegramForbiddenError, TelegramNetworkError, TelegramServerError
from aiogram.methods import SendMessage

from leisure import settings
from leisure.bot import keyboards as kb
from leisure.bot.callbacks import decision_cb, parse_cb, reason_cb
from leisure.core.catalog import default_profile
from leisure.core.scoring import score
from leisure.core.timeutil import trim_past
from leisure.worker import messages as msg
from leisure.worker import send as send_mod

from .conftest import make_event

EID = "4f2c8a10-1111-2222-3333-444455556666"
ITEM = {"event": {"id": EID, "title": "Концерт", "time_text": "19:00", "venue": "Зал", "url": "https://example.org/e"},
        "day": "2026-10-25", "slot": "вечер", "score": 80, "why": [], "days": [], "decision": None,
        "links": {"tg": "https://t.me/share/url?x", "page": "https://leisure.example.org/e/x", "gcal": "g", "outlook": "o", "ics": "i"}}


# ── Д5, Д1: кнопки карточки ──
def test_card_has_interesting_button_and_day_in_callback():
    rows = msg.card_keyboard(ITEM, url_buttons=True)
    flat = [b for r in rows for b in r]
    assert [b["text"] for r in rows[:2] for b in r] == ["Иду", "Может быть", "Интересно", "Мимо"]
    assert next(b for b in flat if b["text"] == "Интересно")["callback_data"] == f"d:i:{EID}:2026-10-25"
    assert all(len(b["callback_data"].encode()) <= 64 for b in flat if "callback_data" in b)
    assert len(decision_cb("иду", EID, "2026-10-25").encode()) == 51


def test_parse_cb_day_optional_and_old_buttons_work():
    p = parse_cb(f"d:g:{EID}:2026-10-25")
    assert (p.kind, p.value, p.event_id, p.day) == ("decision", "иду", EID, date(2026, 10, 25))
    old = parse_cb(f"d:g:{EID}")                      # кнопка из ранее отправленной карточки
    assert old.day is None and old.value == "иду"
    assert parse_cb(f"d:g:{EID}:вчера") is None and parse_cb(f"r:1:{EID}:2026-10-25") is None
    assert parse_cb(reason_cb("дорого", EID)).kind == "reason"


# ── Д6, Юзабилити 6: клавиатура после «Мимо» и причины ──
def _rows_after_miss(reasons):
    links = msg.card_link_rows(ITEM, True)
    return msg.card_rows(EID, [], "2026-10-25", "мимо", reasons, links)


def test_miss_keeps_links_and_reasons_removed_after_choice():
    texts = lambda rows: [[b["text"] for b in r] for r in rows]   # noqa: E731
    after_miss = _rows_after_miss("main")
    assert texts(after_miss)[:2] == [["Иду", "Может быть"], ["Интересно", "● Мимо"]]
    assert texts(after_miss)[2] == [kb.REASON_CAPTION]                       # подпись: причина необязательна
    assert texts(after_miss)[3] == ["Не моё", "Дорого", "Далеко", "Ещё…"] and texts(after_miss)[-1] == ["Подробнее", "Другу"]
    more = _rows_after_miss("more")
    assert texts(more)[3:5] == [["Уже был", "Не то время"], ["Не та компания"]] and "Без причины" not in str(more)
    assert texts(_rows_after_miss(None)) == [["Иду", "Может быть"], ["Интересно", "● Мимо"], ["Подробнее", "Другу"]]


# ── Д14: события, которые уже начались или вот-вот начнутся ──
def _kept(events, now):
    return {e["id"]: e["dates"] for e in trim_past(events, "2026-10-24", now)}


def test_trim_past_hides_events_starting_within_30_minutes():
    """Правило: на сегодня попадает событие, начало которого не раньше now + 30 минут (время доехать)."""
    ev = {"id": "a", "dates": ["2026-10-24", "2026-10-25"], "start_time": "13:00"}
    only_today = {"id": "b", "dates": ["2026-10-24"], "start_time": "13:00"}
    no_time = {"id": "c", "dates": ["2026-10-24"]}
    evs = [ev, only_today, no_time]
    assert _kept(evs, datetime(2026, 10, 24, 12, 0)) == {"a": ["2026-10-24", "2026-10-25"], "b": ["2026-10-24"], "c": ["2026-10-24"]}
    assert "b" in _kept(evs, datetime(2026, 10, 24, 12, 30))                  # ровно за 30 минут — ещё можно
    assert "b" not in _kept(evs, datetime(2026, 10, 24, 12, 31))              # меньше 30 минут до начала — уже нет
    late = _kept(evs, datetime(2026, 10, 24, 14, 0))                           # давно началось: сегодняшняя дата уходит
    assert late == {"a": ["2026-10-25"], "c": ["2026-10-24"]}                  # завтрашняя дата и событие без времени остаются
    assert _kept(evs, None) == {"a": ["2026-10-24", "2026-10-25"], "b": ["2026-10-24"], "c": ["2026-10-24"]}   # без now — по дате


def test_trim_past_exhibitions_and_places_hidden_only_after_end_time():
    """Для kind «выставка» и «место» start_time не применяется: прячем, только когда прошёл end_time."""
    expo = {"id": "x", "kind": "выставка", "dates": ["2026-10-24"], "start_time": "11:00", "end_time": "20:00"}
    place = {"id": "p", "kind": "место", "dates": ["2026-10-24"], "start_time": "10:00", "end_time": "18:00"}
    no_end = {"id": "n", "kind": "выставка", "dates": ["2026-10-24"], "start_time": "10:00"}
    evs = [expo, place, no_end]
    assert set(_kept(evs, datetime(2026, 10, 24, 15, 0))) == {"x", "p", "n"}   # давно открыты, но ещё работают
    assert set(_kept(evs, datetime(2026, 10, 24, 19, 59))) == {"x", "n"}        # место закрылось в 18:00
    assert set(_kept(evs, datetime(2026, 10, 24, 20, 0))) == {"n"}              # выставка закрылась; без end_time — остаётся
    assert "x" not in _kept([{**expo, "kind": "событие"}], datetime(2026, 10, 24, 15, 0))   # обычное событие — по start_time


def test_trim_past_ignores_now_on_other_day():
    """now другого дня не должен вычёркивать события: фильтр действует только на сегодняшнюю дату."""
    ev = {"id": "b", "dates": ["2026-10-24"], "start_time": "13:00"}
    assert trim_past([ev], "2026-10-24", datetime(2026, 11, 1, 20, 0))


# ── Д4: параметры с детьми ──
def _score(ev, **params):
    prof = default_profile()
    prof["params"].update(params)
    return score(ev, prof)


def test_kids_params_change_score_and_defaults_do_not():
    kid = make_event(audience_kids=True, tags=["музыка", "семья"])
    night = make_event(tags=["музыка", "ночь"])
    base_kid, base_night = _score(kid), _score(night)
    for params in ({"kids": True}, {"company": "с детьми"}):
        assert _score(kid, **params).raw == pytest.approx(base_kid.raw + 6)
        assert _score(night, **params).raw == pytest.approx(base_night.raw - 8)
    assert _score(make_event(tags=["музыка", "шумно"]), kids=True).raw < _score(make_event(tags=["музыка", "шумно"])).raw
    assert any(w.text == "подходит с детьми" for w in _score(kid, kids=True).why)
    assert not any("детьми" in w.text for w in base_kid.why)            # у профиля по умолчанию правило выключено


def test_onboarding_has_no_areas_step():
    from leisure.bot.onboarding import Onb
    assert not hasattr(Onb, "areas") and not hasattr(kb, "areas_keyboard")


# ── Д18: localhost ──
def test_local_web_url_gives_text_links_not_url_buttons(monkeypatch):
    from leisure.db.models import Profile
    monkeypatch.setattr(settings, "WEB_BASE_URL", "http://localhost:8000")
    p = Profile(user_id=1, name="Аня")
    view = {"title": "23–25 октября", "weekend": ["2026-10-23", "2026-10-24", "2026-10-25"],
            "items": [{**ITEM, "event": {**ITEM["event"], "url": ""}}, ITEM], "horizon": []}
    from leisure.worker.schedules import digest_messages
    out = digest_messages(p, view)
    urls = [b["url"] for _, _, rows in out for r in (rows or []) for b in r if "url" in b]
    assert all("localhost" not in u for u in urls) and not any(b.get("text") in ("Другу", "Весь дайджест")
                                                               for _, _, rows in out for r in (rows or []) for b in r)
    assert "Весь дайджест: http://localhost:8000/digest" in out[0][1] and "Другу: " in out[-1][1]
    # а политика — текстом в приветствии
    from leisure.bot.onboarding import hello_message
    text, rows = hello_message()
    assert "Политика обработки данных: " in text and all("url" not in b for r in rows for b in r)


def test_public_web_url_keeps_url_buttons(monkeypatch):
    monkeypatch.setattr(settings, "WEB_BASE_URL", "https://leisure.example.org")
    row2 = msg.card_keyboard(ITEM)[-1]
    assert [b["text"] for b in row2] == ["Подробнее", "Другу"]


def test_warn_local_web_url_logs(monkeypatch, caplog):
    from leisure.api import services
    monkeypatch.setattr(settings, "WEB_BASE_URL", "http://127.0.0.1:8000")
    with caplog.at_level(logging.WARNING, logger="leisure.services"):
        services.warn_local_web_url()
    assert "WEB_BASE_URL" in caplog.text
    caplog.clear()
    monkeypatch.setattr(settings, "WEB_BASE_URL", "https://leisure.example.org")
    services.warn_local_web_url()
    assert not caplog.records


# ── Юзабилити 7: пустая подборка ──
def test_empty_digest_is_one_message():
    from leisure.db.models import Profile
    from leisure.worker.schedules import digest_messages
    out = digest_messages(Profile(user_id=7, name="Б"), {"title": "t", "weekend": [], "items": [], "horizon": []})
    assert len(out) == 1 and out[0][1].startswith("<b>Выходные t</b>\nНа эти выходные под твой профиль ничего не нашлось.")
    assert [b["text"] for b in out[0][2][0]][-1] == "Мои интересы"


# ── тексты напоминаний ──
def test_texts_do_not_promise_saturday():
    assert "в субботу" not in msg.digest_header("23–25 октября", 3)
    from leisure.bot.decisions import TOASTS
    assert TOASTS["иду"] == "В плане: {day}. Напомню утром." and "суббот" not in TOASTS["иду"]
    plan = {"weekend": ["2026-10-27"], "days": {"2026-10-27": [
        {"event": {"title": "А", "time_text": "13:00", "venue": "V", "address": "A"}, "status": "иду"}]}}
    assert "План на сегодня · вторник, 27 окт" in msg.plan_today_text(plan, "2026-10-27")


# ── Д10, Д11: отправка ──
class FakeBot:
    """send_message по плану: для каждого вызова — исключение или None (успех)."""

    def __init__(self, plan):
        self.plan, self.calls = list(plan), []

    async def send_message(self, uid, text, **kw):
        self.calls.append((uid, text))
        err = self.plan.pop(0) if self.plan else None
        if err:
            raise err


def _m():
    return SendMessage(chat_id=1, text="x")


@pytest.fixture
def sleeps(monkeypatch):
    rec = []

    async def fake_sleep(t):
        rec.append(t)

    monkeypatch.setattr(send_mod.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(send_mod, "SEND_INTERVAL", 0)
    return rec


def _run(bot, messages):
    return asyncio.run(send_mod.send_with_bot(bot, messages))


def test_send_retries_5xx_and_network_with_backoff(sleeps):
    bot = FakeBot([TelegramServerError(_m(), "Bad Gateway"), TelegramNetworkError(_m(), "reset")])
    res = _run(bot, [(1, "m1", None), (1, "m2", None)])
    assert res.sent == 2 and res.undelivered == [] and res.blocked == []
    assert [t for t in sleeps if t] == [1, 2]


def test_send_gives_up_after_three_retries(sleeps):
    bot = FakeBot([TelegramServerError(_m(), "Bad Gateway")] * 10)
    res = _run(bot, [(1, "m1", None), (1, "m2", None)])
    assert res.sent == 0 and res.undelivered == [0, 1]
    assert len(bot.calls) == 4 + 4                                   # по первой попытке и трём повторам на сообщение
    assert [t for t in sleeps if t] == [1, 2, 4, 1, 2, 4]


def test_send_forbidden_stops_that_user_only(sleeps):
    bot = FakeBot([None, TelegramForbiddenError(_m(), "bot was blocked by the user")])
    res = _run(bot, [(1, "h", None), (1, "c1", None), (1, "c2", None), (2, "h", None)])
    assert res.sent == 2 and res.undelivered == [1, 2] and res.blocked == [1]
    assert [c[0] for c in bot.calls] == [1, 1, 2]                    # после отказа пользователю 1 больше не писали


def test_send_other_errors_do_not_retry(sleeps):
    bot = FakeBot([ValueError("boom")])
    res = _run(bot, [(1, "a", None), (1, "b", None)])
    assert res.sent == 1 and res.undelivered == [0] and len(bot.calls) == 2


def test_dry_run_without_token_delivers_nothing(monkeypatch):
    monkeypatch.setattr(settings, "bot_token", lambda: (_ for _ in ()).throw(RuntimeError("нет токена")))
    res = asyncio.run(send_mod.send_messages([(1, "a", None), (1, "b", None)]))
    assert res.sent == 0 and res.undelivered == [0, 1]
