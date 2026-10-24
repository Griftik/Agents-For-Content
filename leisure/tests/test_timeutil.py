from datetime import date, datetime

import pytest

from leisure.core.timeutil import (end_hour, event_times, fmt_date, hhmm, is_free, js_round, slot_of, start_hour,
                                   trim_past, weekend_for, weekend_title)


@pytest.mark.parametrize("today,fri", [
    ("2026-10-19", "2026-10-23"), ("2026-10-22", "2026-10-23"), ("2026-10-23", "2026-10-23"),
    ("2026-10-24", "2026-10-23"), ("2026-10-25", "2026-10-23"), ("2026-10-26", "2026-10-30"),
])
def test_weekend_for(today, fri):
    wk = weekend_for(date.fromisoformat(today))
    assert wk[0].isoformat() == fri and (wk[2] - wk[0]).days == 2


def test_weekend_title():
    assert weekend_title(["2026-10-23", "2026-10-24", "2026-10-25"]) == "23–25 октября"
    assert weekend_title(["2026-10-30", "2026-10-31", "2026-11-01"]) == "30 октября – 1 ноября"
    assert fmt_date("2026-10-24") == "24 окт"


def test_hours():
    assert start_hour("19:30") == 19.5 and start_hour("с 12.00") == 12 and start_hour("весь день") is None
    # даты перед временем не принимаются за время; невозможные значения отбрасываются
    assert start_hour("23.10 — 20:00; 24.10 и 25.10 — 17:00 и 20:00") == 20
    assert end_hour({"time_text": "23.10 — 20:00; 24.10 и 25.10 — 17:00 и 20:00"}) == 22.5
    assert start_hour("25.10 в 12:00") == 12 and start_hour("99:00") is None and start_hour("12:75") is None
    assert end_hour({"time_text": "12:00; экскурсии 14:00–16:00"}) == 14.5  # конец только у смежного диапазона
    assert end_hour({"time_text": "10:00–18:00 (чт до 21:00)"}) == 18 and end_hour({"time_text": "19:00 — 21:30"}) == 21.5
    assert end_hour({"time_text": "10:00–12:00"}) == 12
    assert end_hour({"time_text": "19:00", "duration_min": 90}) == 20.5
    assert end_hour({"time_text": "19:00"}) == 21.5  # 150 минут по умолчанию
    assert hhmm(19.5) == "19:30" and hhmm(None) is None


@pytest.mark.parametrize("ev,slot", [
    ({"kind": "событие", "time_text": "10:00"}, "утро"), ({"kind": "событие", "time_text": "14:00"}, "день"),
    ({"kind": "событие", "time_text": "19:00"}, "вечер"), ({"kind": "событие", "time_text": "23:00"}, "ночь"),
    ({"kind": "событие", "time_text": ""}, "день"), ({"kind": "выставка", "time_text": "19:00"}, "день"),
    ({"kind": "место", "time_text": "12:00–23:00"}, "день"), ({"kind": "место", "time_text": "18:00–02:00"}, "вечер"),
    ({"kind": "событие", "time": "20:00"}, "вечер"),  # поле прототипа
])
def test_slot_of(ev, slot):
    assert slot_of(ev) == slot


@pytest.mark.parametrize("ev,free", [
    ({"price_from": 0}, True), ({"price_from": 500, "price_text": "500 ₽"}, False),
    ({"price_from": None, "price_text": "бесплатно по регистрации"}, True),
    ({"price_from": None, "price_text": "вход свободный"}, True),
    ({"price_from": None, "price_text": "550 ₽; бесплатно для детей"}, False),
    ({"price_from": None, "price_text": "от 300 руб, свободный вход для студентов"}, False),
    ({"price_from": None, "price_text": ""}, False),
])
def test_is_free(ev, free):
    assert is_free(ev) is free


def test_event_times():
    all_day, s, e = event_times({"time_text": "", "dates": ["2026-10-24"]})
    assert all_day and s == datetime(2026, 10, 24) and e == datetime(2026, 10, 25)
    all_day, s, e = event_times({"time_text": "13:00–15:00", "dates": ["2026-10-24"]})
    assert not all_day and s == datetime(2026, 10, 24, 13) and e == datetime(2026, 10, 24, 15)
    _, s, e = event_times({"time_text": "23:00–02:00", "dates": ["2026-10-23"]}, "2026-10-24")
    assert s == datetime(2026, 10, 24, 23) and e == datetime(2026, 10, 25, 2)
    _, s, e = event_times({"time_text": "19:20", "duration_min": 100, "dates": ["2026-10-24"]})
    assert s == datetime(2026, 10, 24, 19, 20) and e == datetime(2026, 10, 24, 21)


def test_trim_past_and_round():
    evs = [{"id": 1, "dates": ["2026-10-01", "2026-10-30"]}, {"id": 2, "dates": ["2026-10-01"]}]
    out = trim_past(evs, "2026-10-24")
    assert [e["id"] for e in out] == [1] and out[0]["dates"] == ["2026-10-30"]
    assert js_round(0.5) == 1 and js_round(1.5) == 2 and js_round(2.4999) == 2 and js_round(-0.5) == 0
