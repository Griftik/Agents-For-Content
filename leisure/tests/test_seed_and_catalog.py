import pytest
from pydantic import ValidationError

from leisure.core.catalog import (ALL_CATS, CATEGORY_TAGS, CATS, KNOWN_TAGS, REASONS, VALUE_CLUSTERS, VALUE_MAP, VALUE_SHORT,
                                  VALUES, default_profile, interests_from_values, values_average)
from leisure.core.timeutil import weekend_days
from leisure.normalize.schema import EventIn


def test_catalog_sizes():
    assert len(VALUES) == 19 and len(CATS) == 15 and len(ALL_CATS) == 19 and len(REASONS) == 6
    assert len(VALUE_MAP) == 22 + 17 and all(v in VALUES for m in VALUE_MAP.values() for v, _ in m)
    assert set(CATEGORY_TAGS) == set(ALL_CATS) and all(t in KNOWN_TAGS for ts in CATEGORY_TAGS.values() for t in ts)
    p = default_profile()
    assert set(p["values"]) == set(VALUES) and set(p["interests"]) == set(CATS)


def test_value_clusters_cover_all_values_once():
    flat = [v for vs in VALUE_CLUSTERS.values() for v in vs]
    assert sorted(flat) == sorted(VALUES) and list(VALUE_CLUSTERS) == ["Познание", "Люди", "Тело и чувства", "Смысл"]
    assert VALUES[13:] == ["Удовольствие", "Веселье", "Азарт", "Покой", "Близость", "Смысл"]
    assert VALUE_SHORT == {"Красота/эстетика": "Эстетика", "Единство/Дружба": "Дружба", "Инновации/новизна": "Новизна",
                           "Сохранение традиций": "Традиции"}
    assert all(w == 2 for v, w in default_profile()["values"].items() if v in VALUES[13:])


def test_interests_from_values():
    top = {v: 5 for v in VALUES}
    assert all(x == 3 for x in interests_from_values(top).values())
    low = {v: 0 for v in VALUES}
    assert all(x == 1 for x in interests_from_values(low).values())
    crafts = interests_from_values({**low, "Творчество": 5})
    assert crafts["Своими руками"] >= 2 and crafts["Волейбол"] == 1
    assert interests_from_values(default_profile()["values"])["Своими руками"] == 3
    assert values_average([], {}) == 2.5 and values_average(["эстетика"], {"Красота/эстетика": 4}) == 4


def test_seed_validates(seed_raw, seed_events, weekend):
    assert len(seed_events) == 177
    slugs = [e["slug"] for e in seed_events]
    assert len(set(slugs)) == len(slugs)
    assert all(e["url"] for e in seed_events) and all(e["status"] == "published" for e in seed_events)
    on_weekend = [e for e in seed_events if weekend_days(e, weekend)]
    assert len(on_weekend) >= 30  # цель спеки: 30–50 событий на выходные
    assert {e["category"] for e in seed_events} == set(CATS)


def test_schema_rejects_unknown_tag_and_bad_slug():
    base = {"slug": "ok-event", "title": "Событие для теста", "category": "Джаз", "dates": ["2026-10-24"]}
    EventIn.model_validate(base)
    with pytest.raises(ValidationError):
        EventIn.model_validate({**base, "tags": ["неведомый-тег"]})
    with pytest.raises(ValidationError):
        EventIn.model_validate({**base, "slug": "Плохой slug"})
    with pytest.raises(ValidationError):
        EventIn.model_validate({**base, "aesthetics": 7})


def test_schema_derives_times():
    ev = EventIn.model_validate({"slug": "t-1", "title": "Тестовое событие", "category": "Джаз", "dates": ["2026-10-24"],
                                 "time_text": "19:30–21:00", "tags": ["Музыка", "музыка"]})
    assert ev.start_time.isoformat() == "19:30:00" and ev.end_time.isoformat() == "21:00:00" and ev.tags == ["музыка"]
    core = ev.as_core()
    assert core["id"] == "t-1" and core["dates"] == ["2026-10-24"] and core["start_time"] == "19:30"
