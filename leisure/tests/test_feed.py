"""Живая лента (core/feed.py, docs/PIVOT-PWA.md v2): окна дат, сегменты, «успеваешь», скрытое, обучение профиля. Без БД."""
from datetime import date, datetime

import pytest

from leisure.core.affinity import compute_affinity
from leisure.core.catalog import BUSINESS_CATS, default_profile
from leisure.core.feed import adult_only, build_feed, hidden_by_learning, in_segment, parse_window

from .conftest import make_event

TODAY = date(2026, 10, 24)


def _feed(*a, **k):
    """Старые проверки смотрят на список карточек; страница — build_feed(...).items."""
    return build_feed(*a, **k).items


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
    assert [it.event["id"] for it in _feed(evs, _prof(), [], [TODAY], TODAY, segment="business")] == ["e1"]
    assert [it.event["id"] for it in _feed(evs, _prof(), [], [TODAY], TODAY, segment="leisure")] == ["e2"]
    assert len(_feed(evs, _prof(), [], [TODAY], TODAY, segment="all")) == 2


def test_today_excludes_starts_before_now_plus_travel_minutes():
    evs = [_ev(1, start_time="18:30"), _ev(2, start_time="19:30"), _ev(3, kind="выставка", start_time="11:00", end_time="20:00"),
           _ev(4, start_time="18:30", dates=["2026-10-24", "2026-10-25"])]
    now = datetime(2026, 10, 24, 18, 0)
    got = {it.event["id"]: it for it in _feed(evs, _prof(), [], [TODAY], TODAY, now=now)}       # travel 40 по умолчанию
    assert set(got) == {"e2", "e3"} and all(it.can_make_it for it in got.values())
    got = {it.event["id"] for it in _feed(evs, _prof(travel_minutes=10), [], [TODAY], TODAY, now=now)}
    assert got == {"e1", "e2", "e3", "e4"}                                                           # ближе ехать — успеваешь
    # завтра и неделя: сегодняшний старт e4 не успеть, но завтра — да; day = первый подходящий день
    week = {it.event["id"]: it for it in _feed(evs, _prof(), [], parse_window("week", TODAY), TODAY, now=now)}
    assert week["e4"].day == "2026-10-25" and week["e4"].days == ["2026-10-25"] and week["e4"].can_make_it
    # include_missed: не успеваешь — в конце с бейджем false
    missed = _feed(evs, _prof(), [], [TODAY], TODAY, now=now, include_missed=True)
    assert [it.event["id"] for it in missed][-2:] and not missed[-1].can_make_it and missed[0].can_make_it
    # без now (другой день или нет времени) время суток не учитывается
    assert len(_feed(evs, _prof(), [], [TODAY], TODAY, now=None)) == 4


def test_answered_events_are_hidden_and_order_is_by_score():
    evs = [_ev(1), _ev(2), _ev(3), _ev(4, novelty=5, aesthetics=5)]
    decs = [{"event_id": "e1", "status": "не моё"}, {"event_id": "e2", "status": "сходил"}, {"event_id": "e3", "status": "иду"}]
    items = _feed(evs, _prof(), decs, [TODAY], TODAY)
    assert [it.event["id"] for it in items] == ["e4", "e3"]                           # «иду» остаётся видимым, e4 выше по баллу
    assert items[0].result.score >= items[1].result.score
    assert len(_feed(evs, _prof(), [], [TODAY], TODAY, limit=2)) == 2


def _train(cat, status, n, rating=0, tags=("музыка", "камерно")):
    return [{"event_id": f"t{cat}{i}", "status": status, "rating": rating, "event_category": cat, "event_tags": list(tags)}
            for i in range(n)]


def _feed_with(decs, evs):
    p = _prof()
    p["affinity"] = compute_affinity(decs)
    return _feed(evs, p, decs, [TODAY], TODAY)


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


# ── ТЗ-13: ребёнок, лимит на день и догрузка, «сходил, 5» против двойника ──
def test_child_profile_hides_adult_and_lifts_kids():
    evs = [_ev(1, category="Винные бары"), _ev(2, category="Вечеринки"), _ev(3, title="Стендап-вечер", category="Нетривиальное"),
           _ev(4, tags=["музыка", "18+"]), _ev(5, tags=["музыка", "ночь"]), _ev(6, title="Бурлеск-шоу"),
           _ev(7, tags=["музыка", "дети", "семья"], audience_kids=True), _ev(8, tags=["музыка"])]
    child, adult = _prof(), _prof()
    child["kind"], adult["kind"] = "child", "self"
    got = [it.event["id"] for it in build_feed(evs, child, [], [TODAY], TODAY).items]
    assert set(got) == {"e7", "e8"} and got[0] == "e7"                           # детское выше, взрослое скрыто
    assert len(build_feed(evs, adult, [], [TODAY], TODAY).items) == 8             # у взрослого (и parent) без изменений
    parent = _prof()
    parent["kind"] = "parent"
    assert len(build_feed(evs, parent, [], [TODAY], TODAY).items) == 8
    assert adult_only({"category": "Вечеринки"}) and adult_only({"title": "Открытый стендап", "category": "Кино"})
    assert adult_only({"tags": ["18+"], "category": "Кино"}) and not adult_only({"title": "Сказка", "category": "Театр", "tags": ["дети"]})


def test_period_feed_caps_per_day_and_pages_with_offset():
    evs = [_ev(i, dates=["2026-10-24"]) for i in range(14)] + [_ev(100 + i, dates=["2026-10-25"]) for i in range(3)] + \
          [_ev(200 + i, dates=["2026-10-27"]) for i in range(7)]
    week = parse_window("week", TODAY)
    page = build_feed(evs, _prof(), [], week, TODAY, limit=100)
    by_day = {}
    for it in page.items:
        by_day[it.day] = by_day.get(it.day, 0) + 1
    assert by_day == {"2026-10-24": 5, "2026-10-25": 3, "2026-10-27": 5} and page.total == 13 and page.next_offset is None
    assert len(build_feed(evs, _prof(), [], week, TODAY, limit=100, per_day=2).items) == 6
    # на один день лимит не действует
    assert build_feed(evs, _prof(), [], [TODAY], TODAY, limit=100).total == 14
    # страницы: limit 5 → next_offset 5, 10, None
    p1 = build_feed(evs, _prof(), [], week, TODAY, limit=5)
    p2 = build_feed(evs, _prof(), [], week, TODAY, limit=5, offset=p1.next_offset)
    p3 = build_feed(evs, _prof(), [], week, TODAY, limit=5, offset=p2.next_offset)
    assert (p1.next_offset, p2.next_offset, p3.next_offset) == (5, 10, None) and len(p3.items) == 3
    ids = [it.event["id"] for p in (p1, p2, p3) for it in p.items]
    assert len(ids) == len(set(ids)) == 13 and ids == [it.event["id"] for it in page.items]
    assert build_feed(evs, _prof(), [], week, TODAY, limit=5, offset=99).items == []


def test_three_went_5_lift_category_above_tag_twins():
    """Три «сходил, 5» по Джазу: джазовые карточки выше «двойников» с теми же тегами из другой категории; служебные теги
    («день», «вечер») не дают +12 всем подряд, порядок остальных не схлопывается."""
    tags = ["музыка", "камерно", "вечер"]
    jazz = [_ev(i, category="Джаз", tags=tags, novelty=2, aesthetics=2) for i in range(3)]
    twins = [_ev(10 + i, category="Современное искусство", tags=tags, novelty=2, aesthetics=2) for i in range(3)]   # тот же интерес (2)
    others = [_ev(20 + i, category="Кино", tags=["визуальное", "вечер"], novelty=5, aesthetics=5) for i in range(3)]
    evs = jazz + twins + others
    base = build_feed(evs, _prof(), [], [TODAY], TODAY, limit=100).items
    base_scores = {it.event["id"]: it.result.score for it in base}
    assert base_scores["e0"] == base_scores["e10"]                                  # без решений двойники равны
    decs = _train("Джаз", "сходил", 3, rating=5, tags=tuple(tags))
    p = _prof()
    p["affinity"] = compute_affinity(decs)
    after = build_feed(evs, p, decs, [TODAY], TODAY, limit=100).items
    order = [it.event["id"] for it in after]
    scores = {it.event["id"]: it.result.score for it in after}
    assert order[:3] == ["e0", "e1", "e2"] and scores["e0"] > scores["e10"] > base_scores["e10"]
    # «вечер» общий у всех: Кино без совпадений по смысловым тегам не получило прибавки за один служебный тег
    assert scores["e20"] == base_scores["e20"]
