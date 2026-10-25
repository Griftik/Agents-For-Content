"""Нормализация правилами (normalize/rules.py): разбор дат коллекторов, категории, цена, аудитория, полный проход карточек
структурированных источников. Карточки — из тех же фикстур, что у тестов коллекторов: живые снимки Мосбилета, Афиши, «16 Тонн»
(2026-10-24) и фикстуры KudaGo/Timepad по документации. Сети и модели нет."""
from __future__ import annotations

from datetime import date

import pytest

from leisure.collectors.club16tons import Club16TonsCollector
from leisure.collectors.pipeline import run_pipeline
from leisure.core.catalog import ALL_CATS, KNOWN_TAGS
from leisure.normalize.rules import (
    MARK,
    RULE_SOURCES,
    RuleError,
    make_router,
    normalize_by_rules,
    parse_date_text,
    pick_category,
    price_from,
)
from leisure.normalize.schema import EventIn, RawEvent
from leisure.tests import test_collectors_afisha as t_afisha
from leisure.tests import test_collectors_club16tons as t_16tons
from leisure.tests import test_collectors_mosbilet as t_mosbilet
from leisure.tests import test_collectors_pipeline as t_pipe

FROM, TO = date(2026, 10, 24), date(2026, 11, 6)


def raw(source="mosbilet", **kw) -> RawEvent:
    base = dict(source=source, url="https://bilet.mos.ru/event/1", title="Концерт в музее", date_text="2026-10-25 19:00–20:30",
                venue="Музей музыки", text="Камерный вечер.", price_text="от 600 ₽", categories=["Концерты"])
    return RawEvent(**{**base, **kw})


# ─── даты ───

def test_single_shows_with_and_without_time():
    s = parse_date_text("2026-10-25 19:00–20:30", FROM, TO)
    assert (s.dates, s.time_text, s.kind, s.from_period) == ([date(2026, 10, 25)], "19:00–20:30", "событие", False)
    s = parse_date_text("2026-10-26", FROM, TO)
    assert s.dates == [date(2026, 10, 26)] and s.time_text == ""
    assert parse_date_text("2026-10-30 23:00", FROM, TO).time_text == "23:00"


def test_several_shows_are_merged_and_differing_times_noted():
    s = parse_date_text("2026-10-24 12:00; 2026-10-25 12:00; 2026-11-07 12:00", FROM, TO)
    assert s.dates == [date(2026, 10, 24), date(2026, 10, 25)]   # 7.11 вне окна
    assert s.time_text == "12:00" and s.mixed_times == []
    s = parse_date_text("2026-10-24 12:00; 2026-10-25 19:00; 2026-10-26 12:00; … и ещё 3", FROM, TO)
    assert s.time_text == "12:00" and s.mixed_times == ["19:00"]


def test_overnight_party():
    s = parse_date_text("2026-10-31 23:00 — 2026-11-01 06:00", FROM, TO)
    assert s.dates == [date(2026, 10, 31)] and s.time_text == "23:00 — 06:00"


def test_run_of_a_show_takes_the_nearest_date_only_and_asks_to_check():
    s = parse_date_text("период с 2026-10-24 19:00 по 2026-12-20 21:30", FROM, TO)
    assert s.dates == [date(2026, 10, 24)] and s.from_period and s.period_end == date(2026, 12, 20)
    assert s.time_text == "19:00–21:30" and s.kind == "событие"
    assert parse_date_text("период с 2026-10-25 19:00 по 2027-03-28 19:00", FROM, TO).time_text == "19:00"


def test_run_started_before_the_window_is_refused_not_invented():
    with pytest.raises(RuleError, match="ни одной даты"):
        parse_date_text("период с 2026-10-01 19:00 по 2026-12-20 21:30", FROM, TO)


def test_exhibition_period_gives_every_day_of_the_window():
    s = parse_date_text("период с 2025-12-31 по 2026-12-29", FROM, TO, exhibition=True)
    assert s.kind == "выставка" and s.dates[0] == FROM and s.dates[-1] == TO and len(s.dates) == 14
    s = parse_date_text("период с 2026-10-20 по 2026-10-27, часы 11:00–20:00", FROM, TO, exhibition=True)
    assert s.dates == [date(2026, 10, 24 + i) for i in range(4)] and s.time_text == "11:00–20:00"


def test_kudago_open_ended_forms():
    assert len(parse_date_text("бессрочно", FROM, TO, exhibition=True).dates) == 14
    assert parse_date_text("до 2026-10-26", FROM, TO, exhibition=True).dates == [date(2026, 10, 24 + i) for i in range(3)]
    assert parse_date_text("с 2026-11-05, дата окончания не указана", FROM, TO, exhibition=True).dates == [date(2026, 11, 5), date(2026, 11, 6)]
    assert parse_date_text("с 2026-11-05, дата окончания не указана", FROM, TO).dates == [date(2026, 11, 5)]
    with pytest.raises(RuleError, match="без даты начала"):
        parse_date_text("до 2026-10-26", FROM, TO)


def test_very_long_period_of_a_non_exhibition_is_treated_as_permanent():
    assert parse_date_text("период с 2026-01-01 по 2028-01-01", FROM, TO).kind == "выставка"


@pytest.mark.parametrize("text", ["", "пост опубликован 2026-10-22 16:14; даты события смотри в тексте поста", "завтра в семь", "2026-10-25 7pm"])
def test_unparseable_date_text_is_refused(text):
    with pytest.raises(RuleError):
        parse_date_text(text, FROM, TO)


# ─── категории, цена, аудитория ───

@pytest.mark.parametrize("source, cats, title, expected", [
    ("kudago", ["theater"], "спектакль «Дюймовочка»", "Театр"),
    ("kudago", ["concert"], "Джазовый вечер", "Джаз"),
    ("kudago", ["education"], "Лекция о городе", "Нетривиальное"),
    ("kudago", ["business-events"], "Встреча", "Конференции и форумы"),
    ("kudago", ["unknown-slug"], "Что-то", "Нетривиальное"),
    ("timepad", ["Образование", "Лекции"], "Лекция «Город и память»", "Нетривиальное"),
    ("timepad", ["ИТ и интернет"], "Митап про бэкенд", "ИИ и технологии"),
    ("timepad", ["Бизнес"], "Бизнес-завтрак с инвестором", "Бизнес-завтраки"),
    ("mosbilet", ["Спектакли"], "Граф Орлов", "Театр"),
    ("mosbilet", ["Мастер-классы"], "Роспись пряников", "Своими руками"),
    ("mosbilet", ["Экскурсии"], "Прогулка по усадьбе Кусково", "Природа и усадьбы"),
    ("mosbilet", ["Лекции"], "Как работают нейросети", "ИИ и технологии"),
    ("afisha", ["Концерты", "музыка"], "Вечер блюза", "Джаз"),
    ("afisha", ["Выставки", "выставка"], "Смена координат", "Современное искусство"),
    ("afisha", ["спорт"], "Волейбол: Динамо против Зенита", "Волейбол: матчи"),
    ("club16tons", ["Концерты"], "Garage band. Акустика", "Концерты"),
])
def test_pick_category(source, cats, title, expected):
    assert pick_category(raw(source, categories=cats, title=title, text="")) == expected
    assert expected in ALL_CATS


def test_services_are_not_events():
    with pytest.raises(RuleError, match="не событие"):
        pick_category(raw(categories=["Бронирование кортов"], title="Корт на час"))


@pytest.mark.parametrize("text, expected", [
    ("бесплатно", 0), ("вход свободный", 0), ("от 600 ₽", 600), ("от 600 до 3000 ₽", 600), ("1 500 ₽", 1500),
    ("от 1200 до 2400 рублей в абонементе", 1200), ("", None), ("цена на странице не указана", None),
])
def test_price_from(text, expected):
    assert price_from(text) == expected


def test_audience_by_age_and_kids_categories():
    assert normalize_by_rules(raw(age_restriction="6+"), FROM, TO).audience_kids is True
    assert normalize_by_rules(raw(age_restriction="18+"), FROM, TO).audience_kids is False
    kids = normalize_by_rules(raw(categories=["Для детей"], title="Сказка"), FROM, TO)
    assert kids.audience_kids and not kids.audience_30plus and "дети" in kids.tags


# ─── полная карточка ───

def test_full_card_fields_and_mark():
    e = normalize_by_rules(raw(address="Кудринская пл., 46", metro="Баррикадная", lat=55.76, lon=37.58, age_restriction="12+",
                               text="Камерный вечер.\nРаздел афиши: Концерты\nОрганизатор: Музей музыки\nПринимается Пушкинская карта."), FROM, TO)
    assert isinstance(e, EventIn) and e.status == "draft" and e.note.startswith(MARK)
    assert e.category == "Концерты" and e.kind == "событие" and e.dates == [date(2026, 10, 25)]
    assert e.time_text == "19:00–20:30" and e.start_time.isoformat() == "19:00:00" and e.end_time.isoformat() == "20:30:00"
    assert e.venue == "Музей музыки" and e.address == "Кудринская пл., 46" and e.metro == "Баррикадная" and (e.lat, e.lon) == (55.76, 37.58)
    assert e.price_from == 600 and e.price_text == "от 600 ₽"
    assert e.description == "Камерный вечер. Организатор: Музей музыки"   # служебные строки коллектора убраны
    assert "принимается Пушкинская карта" in e.note
    assert e.confidence == "подтверждено" and e.crowd == "людно" and e.why_fit_hint == ""
    assert {"музыка", "эстетика", "вечер"} <= set(e.tags) and set(e.tags) <= KNOWN_TAGS
    assert e.url == e.sources[0] == "https://bilet.mos.ru/event/1" and e.slug.endswith("-2026-10-25")


def test_confidence_drops_honestly():
    assert normalize_by_rules(raw(date_text="2026-10-26"), FROM, TO).confidence == "вероятно"          # нет времени
    assert normalize_by_rules(raw(venue=""), FROM, TO).confidence == "нужно проверить"                   # нет площадки
    e = normalize_by_rules(raw(date_text="период с 2026-10-24 19:00 по 2026-12-20 21:30"), FROM, TO)
    assert e.confidence == "нужно проверить" and "период проката до 2026-12-20" in e.note and e.dates == [FROM]


def test_exhibition_card_is_daily_with_kind_exhibition():
    e = normalize_by_rules(raw(source="afisha", url="https://www.afisha.ru/exhibition/x-1/", title="Смена координат",
                               categories=["Выставки", "выставка"], date_text="период с 2026-10-15 по 2026-11-11", price_text=""), FROM, TO)
    assert e.kind == "выставка" and e.category == "Современное искусство" and len(e.dates) == 14
    assert e.confidence == "вероятно" and e.aesthetics == 4 and "день" in e.tags and e.price_from is None


def test_keyword_tags_come_from_retag_rules():
    e = normalize_by_rules(raw(title="Ретрит выходного дня: медитация в тишине парка", categories=["Встречи"], text=""), FROM, TO)
    assert {"покой", "тишина"} <= set(e.tags) and e.category == "Природа и усадьбы"


def test_free_text_sources_and_bad_links_are_refused():
    with pytest.raises(RuleError, match="LLM"):
        normalize_by_rules(raw(source="telegram", url="https://t.me/x/1", date_text="пост опубликован 2026-10-22"), FROM, TO)
    with pytest.raises(RuleError, match="первоисточник"):
        normalize_by_rules(raw(url="ftp://x"), FROM, TO)


def test_router_uses_rules_for_structured_sources_and_llm_otherwise():
    calls = []

    def llm(r, a, b):
        calls.append(r.source)
        return normalize_by_rules(raw(), a, b)

    router = make_router(llm)
    assert router(raw(), "2026-10-24", "2026-11-06").note.startswith(MARK) and calls == []
    router(raw(source="telegram", url="https://t.me/x/1"), "2026-10-24", "2026-11-06")
    assert calls == ["telegram"]
    with pytest.raises(RuleError, match="OPENROUTER_KEY"):
        make_router(None)(raw(source="telegram", url="https://t.me/x/1"), "2026-10-24", "2026-11-06")
    assert RULE_SOURCES == {"kudago", "timepad", "mosbilet", "afisha", "club16tons"}


# ─── живые снимки и фикстуры коллекторов ───

def collect_fixture_cards() -> list[RawEvent]:
    cards: list[RawEvent] = []
    c, _, _ = t_mosbilet.make()
    cards += c.collect("Москва", FROM, TO)
    c, _, _ = t_afisha.make()
    cards += c.collect("Москва", FROM, TO)
    client, _ = t_16tons.site()
    cards += Club16TonsCollector(client).collect("Москва", FROM, TO)
    cards += t_pipe.fixture_collect("Москва", FROM, TO).events       # KudaGo и Timepad по фикстурам документации
    return cards


def test_live_snapshots_normalize_mostly_and_refusals_are_explained():
    cards = collect_fixture_cards()
    ok, refused = [], {}
    for card in cards:
        try:
            ok.append((card, normalize_by_rules(card, FROM, TO)))
        except RuleError as exc:
            refused[card.url] = str(exc)
    assert len(cards) >= 130 and len(ok) >= 0.85 * len(cards), refused
    assert all(e.status == "draft" and e.note.startswith(MARK) and e.dates and e.url for _, e in ok)
    assert all(FROM <= d <= TO for _, e in ok for d in e.dates)
    by_source = {s: sum(1 for c, _ in ok if c.source == s) for s in RULE_SOURCES}
    assert all(by_source[s] > 0 for s in RULE_SOURCES), by_source
    assert {e.category for _, e in ok} >= {"Театр", "Концерты", "Современное искусство", "Своими руками", "Нетривиальное"}
    for reason in refused.values():   # отказы только по понятным причинам
        assert any(k in reason for k in ("ни одной даты", "не событие", "без даты начала"))


def test_kudago_and_timepad_fixture_cards():
    cards = t_pipe.fixture_collect("Москва", FROM, TO).events
    kg = normalize_by_rules(next(c for c in cards if c.source == "kudago"), FROM, TO)
    tp = normalize_by_rules(next(c for c in cards if c.source == "timepad" and "Город и память" in c.title), FROM, TO)
    assert kg.category and kg.venue and kg.dates and kg.note.startswith(MARK)
    assert tp.time_text == "19:00–21:00" and tp.price_from == 500 and tp.address.startswith("Москва") and tp.confidence == "нужно проверить"  # у Timepad нет названия площадки


def test_pipeline_without_key_writes_rule_drafts_and_reports_free_text_cards_as_waiting(tmp_path, monkeypatch):
    written: list[EventIn] = []
    cards = collect_fixture_cards()
    cards.append(RawEvent(source="telegram", url="https://t.me/quda_today/1", title="Анонс", date_text="пост опубликован", text="x" * 50))
    from leisure.collectors.base import CollectResult, SourceReport
    def collect(*a, **k):
        return CollectResult(cards, [SourceReport(s, True, sum(1 for c in cards if c.source == s)) for s in sorted({c.source for c in cards})])

    report = run_pipeline("Москва", FROM, TO, raw_dir=tmp_path, collect=collect, key_present=lambda: False,
                          load_existing_events=lambda *a: [], write=lambda evs: written.extend(evs) or (len(evs), 0))
    assert "только правила" in report.mode and "ждут LLM" in report.mode
    assert report.total_drafts == len(written) > 100
    assert report.sources["telegram"].norm_errors == 1 and "OPENROUTER_KEY" in report.sources["telegram"].first_norm_error
    assert all(e.status == "draft" and e.note.startswith(MARK) for e in written)
    assert len({e.slug for e in written}) == len(written)


def test_pipeline_normalizer_llm_without_key_still_dry_runs(tmp_path):
    report = run_pipeline("Москва", FROM, TO, raw_dir=tmp_path, collect=t_pipe.fixture_collect, key_present=lambda: False, normalizer="llm",
                          load_existing_events=t_pipe.forbidden, write=t_pipe.forbidden)
    assert "нет OPENROUTER_KEY" in report.mode and report.total_drafts == 0
    with pytest.raises(ValueError):
        run_pipeline("Москва", FROM, TO, raw_dir=tmp_path, collect=t_pipe.fixture_collect, normalizer="magic")
