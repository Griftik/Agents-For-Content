"""Чистые проверки без БД: правило «успеваешь» (Д14), параметры «с детьми» (Д4)."""
from datetime import datetime

import pytest

from leisure.core.catalog import default_profile
from leisure.core.scoring import score
from leisure.core.timeutil import trim_past

from .conftest import make_event


# ── Д14: начавшиеся события ──
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
