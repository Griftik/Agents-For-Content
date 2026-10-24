"""Дедупликация: нормализация, триграммы, пары «дубликат / не дубликат», группы, выбор лучшего."""
from __future__ import annotations

import random
import string
import time as _time
from datetime import date, datetime, timedelta, timezone

import pytest

from leisure.normalize import dedup
from leisure.normalize.dedup import (
    DUP_THRESHOLD,
    completeness,
    explain,
    find_duplicates,
    find_matches,
    is_duplicate,
    normalize_title,
    pick_best,
    similarity,
    title_similarity,
    trigram_similarity,
    trigrams,
    venue_similarity,
)
from leisure.normalize.schema import EventIn

D24, D25, D26, D31 = "2026-10-24", "2026-10-25", "2026-10-26", "2026-10-31"


def ev(title, venue="Большой театр", dates=(D24,), **kw):
    return {"title": title, "venue": venue, "dates": list(dates), "city": "Москва", **kw}


def month(start: date, days: int) -> list[str]:
    return [(start + timedelta(days=i)).isoformat() for i in range(days)]


# ─── нормализация и триграммы ───

@pytest.mark.parametrize("raw,expected", [
    ("  «Щелкунчик»!  ", "щелкунчик"),
    ('"ЩЕЛКУНЧИК" (балет)', "щелкунчик балет"),
    ("ЁЛКА у Лужкова", "елка у лужкова"),
    ("Щелкунчик   Балет", "щелкунчик балет"),            # неразрывные и двойные пробелы
    ("Лебединое озеро 16+", "лебединое озеро"),                      # возрастная метка не часть названия
    ("Джаз & Блюз — вечер", "джаз блюз вечер"),
    ("спектакль «Дюймовочка»", "дюймовочка"),                        # жанровое слово KudaGo
    ("Мастер-класс по керамике 12+", "по керамике"),
    ("Концерт", "концерт"),                                          # жанровое слово целиком не стираем
    ("", ""),
])
def test_normalize_title(raw, expected):
    assert normalize_title(raw) == expected


def test_trigrams_match_pg_trgm():
    assert trigrams("cat") == {"  c", " ca", "cat", "at "}  # пример из документации pg_trgm
    assert trigrams("") == frozenset()
    assert trigram_similarity("cat", "cat") == 1.0
    assert trigram_similarity("cat", "dog") == 0.0
    assert trigram_similarity("", "cat") == 0.0


@pytest.mark.parametrize("a,b,lo,hi", [
    ("«Щелкунчик»", "ЩЕЛКУНЧИК!", 1.0, 1.0),
    ("спектакль «Дюймовочка»", "Дюймовочка", 1.0, 1.0),
    ("Дюймовочка", "Дюймовочка. Московский театр юного зрителя", 0.9, 0.9),   # вложенный заголовок
    ("Вечер джаза в усадьбе Люблино", "Вечер джаза в Люблино", 0.9, 0.9),
    ("Гамлет", "Гамлет-машина", 0.4, 0.55),                                    # разные спектакли
    ("Джаз", "Джаз в усадьбе", 0.0, 0.4),                                      # короткое не «вкладываем»
    ("Вечер фортепианной музыки", "Вечер органной музыки", 0.0, 0.6),
    ("Щелкунчик", "Лебединое озеро", 0.0, 0.1),
    ("", "Щелкунчик", 0.0, 0.0),
])
def test_title_similarity_ranges(a, b, lo, hi):
    assert lo <= title_similarity(a, b) <= hi


@pytest.mark.parametrize("a,b,expected", [
    ("ГЭС-2", "Дом культуры «ГЭС-2»", 1.0),
    ("Центр Зотов", "Центр «Зотов»", 1.0),
    ("Эссе", "Клуб Эссе", 1.0),
    ("Лофт 1", "Лофт 2", 0.0),             # номер — часть названия
    ("ГЭС", "ГЭС-2", 1.0),                 # номер указан только с одной стороны — не повод считать разными
    ("Музей Москвы", "Музей современного искусства «Гараж»", None),
    ("", "ГЭС-2", None),
])
def test_venue_similarity(a, b, expected):
    got = venue_similarity(a, b)
    if expected is None and a and b:
        assert got is not None and got < dedup.VENUE_MIN
    elif expected is None:
        assert got is None
    else:
        assert got == expected


# ─── пары: дубликат ───

DUPLICATES = {
    "регистр, кавычки и пунктуация": (
        ev("«Щелкунчик»"), ev("щелкунчик!")),
    "жанровое слово и разная запись площадки (KudaGo против афиши)": (
        ev("спектакль «Дюймовочка»", "Московский международный Дом музыки (ММДМ)"), ev("Дюймовочка", "Дом музыки")),
    "декоративные слова площадки": (
        ev("Кино в ГЭС-2", "ГЭС-2"), ev("Кино в ГЭС-2", "Дом культуры «ГЭС-2»")),
    "возрастная метка в одном из заголовков": (
        ev("Лебединое озеро 16+"), ev("Лебединое озеро")),
    "вложенный заголовок": (
        ev("Дюймовочка", "Театр юного зрителя"), ev("Дюймовочка. Московский театр юного зрителя", "Театр юного зрителя")),
    "даты пересекаются частично": (
        ev("Ночь джаза", dates=(D24, D25)), ev("Ночь джаза", dates=(D25, D26))),
    "выставка: полный список дней и окно уикенда": (
        ev("Шито-вышито", "Музей декоративного искусства", month(date(2026, 10, 1), 92), kind="выставка"),
        ev("Шито-вышито", "Музей декоративного искусства", (D24, D25), kind="выставка")),
    "выставка: пересечение только в последний день": (
        ev("Шито-вышито", "Музей декоративного искусства", month(date(2026, 10, 1), 92), kind="выставка"),
        ev("выставка «Шито-вышито»", "Музей декоративного искусства", ("2026-12-31", "2027-01-15"), kind="выставка")),
    "выставка: часы работы у источников разные — время не сравниваем": (
        ev("Шито-вышито", "Музей", month(date(2026, 10, 20), 10), kind="выставка", time_text="10:00–18:00"),
        ev("Шито-вышито", "Музей", month(date(2026, 10, 20), 10), kind="выставка", time_text="19:00–22:00")),
    "время начала расходится на час («двери» и «начало»)": (
        ev("Квартет Иванова", time_text="19:00"), ev("Квартет Иванова", time_text="20:00")),
    "площадка не указана, заголовки идентичны": (
        ev("Лекция о дзене", ""), ev("Лекция о дзене", "Культурный центр")),
    "город указан у одного": (
        ev("Щелкунчик", city=""), ev("Щелкунчик")),
}


@pytest.mark.parametrize("a,b", DUPLICATES.values(), ids=DUPLICATES.keys())
def test_duplicate_pairs(a, b):
    assert is_duplicate(a, b), explain(a, b)
    assert is_duplicate(b, a)                        # симметрия
    assert similarity(a, b) == pytest.approx(similarity(b, a))


# ─── пары: НЕ дубликат ───

NOT_DUPLICATES = {
    "один спектакль в разные дни": (
        ev("Щелкунчик", dates=(D24,)), ev("Щелкунчик", dates=(D31,))),
    "то же название в разных площадках": (
        ev("Щелкунчик", "Большой театр"), ev("Щелкунчик", "Театр Моссовета")),
    "то же название в разных городах": (
        ev("Щелкунчик", city="Москва"), ev("Щелкунчик", city="Санкт-Петербург")),
    "разные спектакли с похожими названиями": (
        ev("Гамлет"), ev("Гамлет-машина")),
    "одна площадка и день, разные концерты": (
        ev("Вечер фортепианной музыки"), ev("Вечер органной музыки")),
    "площадки с номерами": (
        ev("Стендап-вечер", "Лофт 1"), ev("Стендап-вечер", "Лофт 2")),
    "похожие имена площадок разного типа": (
        ev("Читка пьесы", "Театр Маяковского"), ev("Читка пьесы", "Музей Маяковского")),
    "дневной и вечерний показ в один день": (
        ev("Дюймовочка", time_text="12:00"), ev("Дюймовочка", time_text="19:00")),
    "то же по start_time (EventIn)": (
        EventIn(slug="a-2026", title="Дюймовочка", category="Театр", dates=[date(2026, 10, 24)], venue="Большой театр",
                start_time="12:00"),
        EventIn(slug="b-2026", title="Дюймовочка", category="Театр", dates=[date(2026, 10, 24)], venue="Большой театр",
                start_time="19:00")),
    "выставка: повторный показ после закрытия": (
        ev("Шито-вышито", "Музей", month(date(2026, 10, 1), 20), kind="выставка"),
        ev("Шито-вышито", "Музей", month(date(2026, 10, 25), 35), kind="выставка")),
    "выставка: то же название в другом музее": (
        ev("Шито-вышито", "Музей А", month(date(2026, 10, 1), 92), kind="выставка"),
        ev("Шито-вышито", "Музей Б", (D24, D25), kind="выставка")),
    "короткое название не вкладывается в длинное": (
        ev("Джаз", "Клуб Эссе"), ev("Джаз в усадьбе", "Клуб Эссе")),
    "площадка не указана и заголовки лишь похожи": (
        ev("Вечер джаза в усадьбе Люблино", ""), ev("Вечер джаза в Люблино", "Усадьба Люблино")),
    "совсем разное": (
        ev("Щелкунчик"), ev("Лекция о дзене")),
    "нет дат": (
        ev("Щелкунчик", dates=()), ev("Щелкунчик", dates=())),
}


@pytest.mark.parametrize("a,b", NOT_DUPLICATES.values(), ids=NOT_DUPLICATES.keys())
def test_not_duplicate_pairs(a, b):
    assert not is_duplicate(a, b), explain(a, b)


def test_explain_gives_reasons():
    assert explain(ev("Щелкунчик", dates=(D24,)), ev("Щелкунчик", dates=(D31,))).reason == "нет общих дней"
    assert explain(ev("Щелкунчик", "Большой театр"), ev("Щелкунчик", "Театр Моссовета")).reason == "разные площадки"
    assert explain(ev("Щелкунчик"), ev("Лекция о дзене")).reason == "заголовки не похожи"
    assert explain(ev("Щелкунчик", city="Москва"), ev("Щелкунчик", city="Сочи")).reason == "разные города"
    m = explain(ev("Ночь джаза", dates=(D24, D25)), ev("Ночь джаза", dates=(D25, D26)))
    assert m.reason == "" and m.shared_dates == (date(2026, 10, 25),) and m.title == 1.0 and m.venue == 1.0


def test_similarity_is_bounded_and_graded():
    same = similarity(ev("Щелкунчик"), ev("Щелкунчик"))
    nested = similarity(ev("Дюймовочка"), ev("Дюймовочка. Московский театр юного зрителя"))
    no_venue = similarity(ev("Щелкунчик"), ev("Щелкунчик", ""))
    assert same == 1.0 > nested > no_venue >= DUP_THRESHOLD
    assert similarity(ev("Щелкунчик"), ev("Лекция о дзене")) == 0.0


def test_thresholds_are_consistent():
    assert dedup.TITLE_WEIGHT + dedup.VENUE_WEIGHT == pytest.approx(1.0)
    assert 0 < dedup.TITLE_MIN < DUP_THRESHOLD < 1
    # при совпавших площадке и днях порог требует заметно более похожих заголовков, чем отсечка TITLE_MIN
    assert (DUP_THRESHOLD - dedup.VENUE_WEIGHT) / dedup.TITLE_WEIGHT > dedup.TITLE_MIN
    assert dedup.UNKNOWN_VENUE_FACTOR >= DUP_THRESHOLD  # без площадки идентичные заголовки ещё дубликат


# ─── поиск в списке ───

def test_find_duplicates_groups():
    events = [
        ev("Щелкунчик"),                                              # 0 ┐
        ev("Лекция о дзене", "Культурный центр"),                      # 1 │ одиночка
        ev("спектакль «Щелкунчик»", dates=(D24, D25)),                # 2 ┘ группа с 0
        ev("Щелкунчик", dates=(D31,)),                                # 3   другой день — одиночка
        ev("Шито-вышито", "Музей", month(date(2026, 10, 1), 92), kind="выставка"),   # 4 ┐
        ev("Шито-вышито", "Музей", (D24,), kind="выставка"),          # 5 │ группа
        ev("Шито-вышито", "Музей", (D25, D26), kind="выставка"),      # 6 ┘ (через 4)
        ev("Щелкунчик", "Театр Моссовета"),                            # 7   другая площадка — одиночка
    ]
    assert find_duplicates(events) == [[0, 2], [4, 5, 6]]


def test_find_duplicates_edge_cases():
    assert find_duplicates([]) == []
    assert find_duplicates([ev("Щелкунчик")]) == []
    assert find_duplicates([ev("Щелкунчик", dates=()), ev("Щелкунчик", dates=())]) == []
    assert find_duplicates([ev("Щелкунчик"), ev("Щелкунчик")]) == [[0, 1]]
    assert find_duplicates([ev("Щелкунчик"), ev("Щелкунчик")], threshold=1.01) == []


def test_find_duplicates_accepts_eventin_and_dicts():
    pydantic_ev = EventIn(slug="shchelkunchik-2026", title="«Щелкунчик»", category="Театр", dates=[date(2026, 10, 24)],
                          venue="Большой театр")
    assert find_duplicates([ev("Щелкунчик"), pydantic_ev]) == [[0, 1]]


def test_find_duplicates_is_fast_on_a_few_hundred_events():
    rnd = random.Random(7)
    events = [ev("".join(rnd.choices(string.ascii_lowercase, k=12)), f"площадка {i % 7}", (D24, D25)) for i in range(400)]
    t0 = _time.perf_counter()
    assert find_duplicates(events) == []
    assert _time.perf_counter() - t0 < 5


def test_find_matches_new_against_known():
    known = [ev("Лекция о дзене"), ev("«Щелкунчик»", dates=(D24, D25)), ev("Щелкунчик", dates=(D31,)), ev("Щелкунчик. Балет")]
    hits = find_matches(ev("Щелкунчик"), known)
    assert [i for i, _ in hits] == [1, 3]
    assert hits[0][1] >= hits[1][1] >= DUP_THRESHOLD
    assert find_matches(ev("Что-то новое"), known) == []


def test_seed_has_no_false_duplicates(seed_raw):
    """177 событий seed — разные события: срабатываний быть не должно (ложное склеивание хуже пропуска)."""
    groups = find_duplicates(seed_raw)
    assert groups == [], [[seed_raw[i]["title"][:40] for i in g] for g in groups]


# ─── выбор лучшего ───

def test_pick_best_confidence_beats_completeness():
    rich_unsure = ev("Щелкунчик", confidence="нужно проверить", address="Театральная пл., 1", metro="Охотный ряд",
                     price_text="от 1000", description="Балет", url="https://x.example/1")
    poor_sure = ev("Щелкунчик", confidence="подтверждено")
    mid = ev("Щелкунчик", confidence="вероятно", address="Театральная пл., 1")
    assert pick_best([rich_unsure, poor_sure, mid]) == 1
    assert pick_best([rich_unsure, mid]) == 1


def test_pick_best_completeness_then_freshness():
    a = ev("Щелкунчик", confidence="подтверждено", address="ул. А", price_from=0)   # 0 рублей — тоже данные
    b = ev("Щелкунчик", confidence="подтверждено", address="ул. А", price_from=0, metro="Охотный ряд")
    assert completeness(b) == completeness(a) + 1
    assert pick_best([a, b]) == 1 and pick_best([b, a]) == 0

    old = ev("Щелкунчик", confidence="подтверждено", updated_at="2026-10-20T10:00:00")
    new = ev("Щелкунчик", confidence="подтверждено", updated_at=datetime(2026, 10, 22, tzinfo=timezone.utc))
    assert pick_best([new, old]) == 0 and pick_best([old, new]) == 1               # метка важнее позиции, str и datetime


def test_pick_best_without_timestamps_later_wins_and_group_subset():
    first, second, third = ev("Щелкунчик"), ev("Щелкунчик"), ev("Щелкунчик")
    assert pick_best([first, second, third]) == 2
    assert pick_best([first, second, third], group=[0, 1]) == 1
    with pytest.raises(ValueError):
        pick_best([first], group=[])


def test_pick_best_on_eventin_and_blank_values_do_not_count():
    sure = EventIn(slug="s-2026", title="Щелкунчик", category="Театр", dates=[date(2026, 10, 24)], confidence="подтверждено")
    guess = EventIn(slug="g-2026", title="Щелкунчик", category="Театр", dates=[date(2026, 10, 24)],
                    confidence="нужно проверить", venue="Большой театр", description="Балет")
    assert pick_best([guess, sure]) == 1
    assert completeness({"venue": "   ", "tags": [], "note": "", "price_from": None}) == 0
    assert completeness({"price_from": 0, "tags": ["музыка"]}) == 2
