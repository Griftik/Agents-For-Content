"""Живая лента (core/feed.py, docs/PIVOT-PWA.md v2): окна дат, сегменты, «успеваешь», скрытое, обучение профиля. Без БД."""
from datetime import date, datetime

import pytest

from leisure.core.affinity import compute_affinity
from leisure.core.catalog import BUSINESS_CATS, default_profile
from leisure.core.feed import build_feed, hidden_by_learning, in_segment, parse_window

from .conftest import make_event

TODAY = date(2026, 10, 24)


def _ev(i, **over):
    base = {"id": f"e{i}", "slug": f"e{i}", "title": f"Событие {i}", "dates": ["2026-10-24"], "start_time": "19:00"}
    base.update(over)
    return make_event(**base)


def _prof(**params):
    p = default_profile()
    p["params"].update(params)
    return p


def test_parse_window():
    assert parse_window("today", TODAY) == [TODAY] and parse_window("tomorrow", TODAY) == [date(2026, 10, 25)]
    week = parse_window("week", TODAY)
    assert len(week) == 7 and week[0] == TODAY and week[-1] == date(2026, 10, 30)
    assert parse_window("2026-10-27", TODAY) == [date(2026, 10, 27)]
    for bad in ("2026-10-23", "вчера", "2026-13-01"):
        with pytest.raises(ValueError):
            parse_window(bad, TODAY)


def test_segments_by_catalog_categories():
    biz, fun = {"category": BUSINESS_CATS[0]}, {"category": "Джаз"}
    assert in_segment(biz, "business") and not in_segment(biz, "leisure") and in_segment(biz, "all")
    assert in_segment(fun, "leisure") and not in_segment(fun, "business")
    evs = [_ev(1, category=BUSINESS_CATS[1]), _ev(2, category="Театр")]
    assert [it.event["id"] for it in build_feed(evs, _prof(), [], [TODAY], TODAY, segment="business")] == ["e1"]
    assert [it.event["id"] for it in build_feed(evs, _prof(), [], [TODAY], TODAY, segment="leisure")] == ["e2"]
    assert len(build_feed(evs, _prof(), [], [TODAY], TODAY, segment="all")) == 2


def test_today_excludes_starts_before_now_plus_travel_minutes():
    evs = [_ev(1, start_time="18:30"), _ev(2, start_time="19:30"), _ev(3, kind="выставка", start_time="11:00", end_time="20:00"),
           _ev(4, start_time="18:30", dates=["2026-10-24", "2026-10-25"])]
    now = datetime(2026, 10, 24, 18, 0)
    got = {it.event["id"]: it for it in build_feed(evs, _prof(), [], [TODAY], TODAY, now=now)}       # travel 40 по умолчанию
    assert set(got) == {"e2", "e3"} and all(it.can_make_it for it in got.values())
    got = {it.event["id"] for it in build_feed(evs, _prof(travel_minutes=10), [], [TODAY], TODAY, now=now)}
    assert got == {"e1", "e2", "e3", "e4"}                                                           # ближе ехать — успеваешь
    # завтра и неделя: сегодняшний старт e4 не успеть, но завтра — да; day = первый подходящий день
    week = {it.event["id"]: it for it in build_feed(evs, _prof(), [], parse_window("week", TODAY), TODAY, now=now)}
    assert week["e4"].day == "2026-10-25" and week["e4"].days == ["2026-10-25"] and week["e4"].can_make_it
    # include_missed: не успеваешь — в конце с бейджем false
    missed = build_feed(evs, _prof(), [], [TODAY], TODAY, now=now, include_missed=True)
    assert [it.event["id"] for it in missed][-2:] and not missed[-1].can_make_it and missed[0].can_make_it
    # без now (другой день или нет времени) время суток не учитывается
    assert len(build_feed(evs, _prof(), [], [TODAY], TODAY, now=None)) == 4


def test_answered_events_are_hidden_and_order_is_by_score():
    evs = [_ev(1), _ev(2), _ev(3), _ev(4, novelty=5, aesthetics=5)]
    decs = [{"event_id": "e1", "status": "не моё"}, {"event_id": "e2", "status": "сходил"}, {"event_id": "e3", "status": "иду"}]
    items = build_feed(evs, _prof(), decs, [TODAY], TODAY)
    assert [it.event["id"] for it in items] == ["e4", "e3"]                           # «иду» остаётся видимым, e4 выше по баллу
    assert items[0].result.score >= items[1].result.score
    assert len(build_feed(evs, _prof(), [], [TODAY], TODAY, limit=2)) == 2


def _train(cat, status, n, rating=0, tags=("музыка", "камерно")):
    return [{"event_id": f"t{cat}{i}", "status": status, "rating": rating, "event_category": cat, "event_tags": list(tags)}
            for i in range(n)]


def _feed_with(decs, evs):
    p = _prof()
    p["affinity"] = compute_affinity(decs)
    return build_feed(evs, p, decs, [TODAY], TODAY)


def test_three_not_mine_drop_category_from_top_five_and_three_went_5_lift_it():
    cats = ["Джаз", "Театр", "Кино", "Концерты", "Своими руками", "Нетривиальное"]
    evs = [_ev(i, category=c, tags=["музыка", "камерно"] if c == "Джаз" else ["визуальное"]) for i, c in enumerate(cats)]
    base = [it.event["category"] for it in _feed_with([], evs)]
    assert "Джаз" in base[:5]
    # три «не моё» по Джазу: категория уходит из первой пятёрки (и вовсе скрыта порогом «не показывать похожее»)
    after = [it.event["category"] for it in _feed_with(_train("Джаз", "не моё", 3), evs)]
    assert "Джаз" not in after[:5]
    p = _prof()
    p["affinity"] = compute_affinity(_train("Джаз", "не моё", 3))
    assert hidden_by_learning(evs[0], p["affinity"])
    assert not hidden_by_learning(evs[0], compute_affinity(_train("Джаз", "мимо", 3)))     # прежнее «мимо» слабее: не прячет
    # три «сходил, 5» по Нетривиальному поднимают категорию наверх
    lifted = [it.event["category"] for it in _feed_with(_train("Нетривиальное", "сходил", 3, rating=5, tags=("нетривиально",)), evs)]
    assert lifted[0] == "Нетривиальное" and base.index("Нетривиальное") > 0
    # низкая оценка после «сходил» даёт минус даже при положительном статусе
    low = compute_affinity(_train("Кино", "сходил", 2, rating=1, tags=("визуальное",)))
    assert low["cat"]["Кино"] < 0 and low["tag"]["визуальное"] < 0
