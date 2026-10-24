"""Коллектор Мосбилета (bilet.mos.ru). Фикстуры — ЖИВЫЕ ответы сайта, снятые 2026-10-24 (см. fixtures/collectors_live_snapshots.json):
страницы разделов целиком в части данных (блок серверной выдачи Next.js без правок) и настоящий robots.txt. Сети нет: httpx.MockTransport."""
from __future__ import annotations

import gzip
import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest

from leisure.collectors import load_collectors
from leisure.collectors.base import REGISTRY, CollectorError, collect_all
from leisure.collectors.mosbilet import BASE, PAGES, MosbiletCollector, format_price
from leisure.normalize.llm import build_prompt

FIX = Path(__file__).with_name("fixtures")


def load(name: str) -> str:
    gz = FIX / f"{name}.gz"
    return gzip.open(gz, "rt", encoding="utf-8").read() if gz.exists() else (FIX / name).read_text(encoding="utf-8")


ROUTES = {
    "/": "mosbilet_home.html", "/koncerty/": "mosbilet_koncerty.html", "/sport/": "mosbilet_sport.html",
    "/rechnye-progulki/": "mosbilet_rechnye-progulki.html",
}
LIVE_PAGES = ("", "koncerty", "sport", "rechnye-progulki")
FROM, TO = date(2026, 10, 24), date(2026, 10, 31)
NOW = datetime(2026, 10, 24, 12, 0, 0, tzinfo=timezone.utc)


class FakeSite:
    def __init__(self, routes=ROUTES, robots: str | None = None, overrides: dict[str, httpx.Response] | None = None):
        self.routes, self.overrides = routes, overrides or {}
        self.robots = load("robots_mosbilet.txt") if robots is None else robots
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.url.host == "bilet.mos.ru"
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=self.robots)
        if request.url.path in self.overrides:
            return self.overrides[request.url.path]
        name = self.routes.get(request.url.path)
        return httpx.Response(200, text=load(name)) if name else httpx.Response(404, text="нет такой страницы")


def make(site: FakeSite | None = None, **kw):
    site = site or FakeSite()
    sleeps: list[float] = []
    kw.setdefault("pages", LIVE_PAGES)
    c = MosbiletCollector(httpx.Client(transport=httpx.MockTransport(site)), sleep=sleeps.append, clock=lambda: NOW, **kw)
    return c, site, sleeps


# ─── живой снимок ───

def test_live_snapshot_gives_events_with_source_link_and_structured_fields():
    c, _, sleeps = make()
    events = c.collect("Москва", FROM, TO)
    assert len(events) == 43
    assert (c.stats.pages, c.stats.kept, c.stats.fetched) == (4, 43, 87)
    assert c.stats.skipped == 7 and c.stats.duplicates == 9 and c.stats.outside_window == 28  # 7 — экспозиции без дат на главной
    assert len({e.url for e in events}) == len(events)
    for e in events:
        assert e.source == "mosbilet" and e.title and e.date_text
        assert e.url.startswith("https://bilet.mos.ru/event/") and e.url.rsplit("/", 1)[1].isdigit()
        assert e.collected_at == "2026-10-24T12:00:00+00:00"
    assert sleeps == [1.5, 1.5, 1.5]
    assert sum(1 for e in events if e.lat is not None and e.lon is not None) == 43
    assert {"Концерты", "Спектакли", "Лекции"} <= {c for e in events for c in e.categories}


def test_known_concert_card_from_the_live_page():
    c, _, _ = make()
    e = next(x for x in c.collect("Москва", FROM, TO) if x.url.endswith("/730000257"))
    assert e.title == "Две звезды одной эпохи"
    assert e.date_text == "2026-10-24 17:00–18:30"
    assert e.venue == "Музей П.И. Чайковского в Москве"
    assert (e.lat, e.lon) == (55.75826, 37.58551) and e.age_restriction == "12+"
    assert e.categories == ["Концерты"] and e.price_text == ""  # цены в источнике нет — не гадаем
    assert "Организатор: Российский национальный музей музыки" in e.text and "Раздел афиши: Концерты" in e.text


def test_free_events_are_marked_and_run_is_a_period():
    c, _, _ = make()
    events = {e.url.rsplit("/", 1)[1]: e for e in c.collect("Москва", FROM, TO)}
    assert events["722903257"].price_text == "бесплатно"
    assert events["348463257"].date_text == "период с 2026-10-24 19:00 по 2026-12-20 21:30"
    assert events["348463257"].price_text == "от 1000 ₽" and "Пушкинская карта" in events["348463257"].text


def test_pipeline_prompt_gets_structured_fields():
    c, _, _ = make()
    e = next(x for x in c.collect("Москва", FROM, TO) if x.url.endswith("/730000257"))
    prompt = build_prompt(e, "2026-10-24", "2026-10-31")
    assert "Музей П.И. Чайковского в Москве" in prompt and "55.75826" in prompt and "12+" in prompt


def test_window_outside_data_gives_nothing_but_counts_it():
    c, _, _ = make()
    assert c.collect("Москва", date(2030, 1, 1), date(2030, 1, 7)) == []
    assert c.stats.outside_window > 0 and c.stats.kept == 0


def test_window_filters_by_overlap_not_by_start_only():
    c, _, _ = make()
    wide = {e.url for e in c.collect("Москва", FROM, date(2026, 12, 31))}
    narrow = {e.url for e in c.collect("Москва", FROM, FROM)}
    assert narrow < wide


# ─── robots.txt ───

def test_robots_from_the_live_file_allow_our_pages_and_are_read_once():
    c, site, _ = make()
    c.collect("Москва", FROM, TO)
    robots_hits = [r for r in site.requests if r.url.path == "/robots.txt"]
    assert len(robots_hits) == 1
    assert all(not r.url.query for r in site.requests)  # `?page=N` закрыт robots.txt: параметров не шлём вообще


def test_closed_section_is_skipped_not_fetched():
    c, site, _ = make(FakeSite(robots="User-agent: *\nDisallow: /sport/\n"))
    events = c.collect("Москва", FROM, TO)
    assert events and c.stats.blocked_by_robots == 1
    assert "/sport/" not in {r.url.path for r in site.requests}


def test_everything_closed_is_a_source_error():
    c, site, _ = make(FakeSite(robots="User-agent: *\nDisallow: /\n"))
    with pytest.raises(CollectorError, match="закрыто robots.txt"):
        c.collect("Москва", FROM, TO)
    assert [r.url.path for r in site.requests] == ["/robots.txt"]


def test_robots_can_be_turned_off_explicitly():
    c, site, _ = make(FakeSite(robots="User-agent: *\nDisallow: /\n"), respect_robots=False)
    assert c.collect("Москва", FROM, TO)
    assert "/robots.txt" not in {r.url.path for r in site.requests}


# ─── сбои ───

def test_one_failing_page_does_not_kill_the_others():
    site = FakeSite(overrides={"/sport/": httpx.Response(500, text="упали")})
    c, _, sleeps = make(site, retries=1)
    events = c.collect("Москва", FROM, TO)
    assert events and c.stats.failed_pages == 1 and c.stats.pages == 3
    assert 2.0 in sleeps  # повтор после 500 с паузой


def test_blocked_everywhere_says_so_and_does_not_bypass():
    site = FakeSite(routes={}, overrides={p: httpx.Response(403) for p in ("/", "/koncerty/", "/sport/", "/rechnye-progulki/")})
    c, _, _ = make(site)
    with pytest.raises(CollectorError, match="403.*Защиту не обходим"):
        c.collect("Москва", FROM, TO)


def test_page_without_next_data_is_reported_as_changed_markup():
    site = FakeSite(overrides={p: httpx.Response(200, text="<html><body>Технические работы</body></html>") for p in ROUTES})
    c, _, _ = make(site)
    with pytest.raises(CollectorError, match="вёрстка изменилась"):
        c.collect("Москва", FROM, TO)


def test_broken_card_is_skipped_and_counted():
    page = {"props": {"pageProps": {"items": [
        {"id": 1, "title": "Нормальное", "dateFrom": "2026-10-25 19:00:00", "dateTo": "2026-10-25 20:00:00", "url": "/event/1"},
        {"id": 2, "title": "", "dateFrom": "2026-10-25 19:00:00"},
        {"id": 3, "title": "Без даты", "dateFrom": ""},
        {"id": 1, "title": "Дубль", "dateFrom": "2026-10-25 19:00:00"},
        {"id": None, "title": "Без номера", "dateFrom": "2026-10-25 19:00:00"},
        {"id": 4, "title": "Вне Москвы по координатам", "dateFrom": "2026-10-25 19:00:00", "venueLat": "999", "venueLon": "37"},
    ]}}}
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(page)}</script>'
    c, _, _ = make(FakeSite(routes={}, overrides={"/": httpx.Response(200, text=html)}), pages=("",))
    events = c.collect("Москва", FROM, TO)
    assert [e.title for e in events] == ["Нормальное", "Вне Москвы по координатам"]
    assert events[1].lat is None and events[1].lon is None  # координаты вне диапазона не берём
    assert (c.stats.skipped, c.stats.duplicates) == (3, 1)


def test_other_city_and_reversed_dates_are_rejected():
    c, site, _ = make()
    with pytest.raises(CollectorError, match="не поддерживается"):
        c.collect("Казань", FROM, TO)
    with pytest.raises(ValueError):
        c.collect("Москва", TO, FROM)
    assert site.requests == []


@pytest.mark.parametrize("item, expected", [
    ({"isFree": True, "priceFrom": 500}, "бесплатно"),
    ({"priceFrom": 0}, "бесплатно"),
    ({"priceFrom": 600}, "от 600 ₽"),
    ({"priceFrom": 600, "priceTo": 3000}, "от 600 до 3000 ₽"),
    ({"priceFrom": 600, "priceTo": 600}, "от 600 ₽"),
    ({"priceFrom": None}, ""),
    ({}, ""),
])
def test_format_price(item, expected):
    assert format_price(item) == expected


# ─── реестр и конвейер ───

def test_registered_and_picked_up_by_collect_all(monkeypatch):
    assert "mosbilet" in load_collectors() and REGISTRY["mosbilet"] is MosbiletCollector
    site = FakeSite()

    class OnFixtures(MosbiletCollector):
        def __init__(self):
            super().__init__(httpx.Client(transport=httpx.MockTransport(site)), pages=LIVE_PAGES, sleep=lambda s: None)

    monkeypatch.setitem(REGISTRY, "mosbilet", OnFixtures)
    result = collect_all("Москва", FROM, TO, names=["mosbilet"])
    assert result.sources[0].ok and result.sources[0].count == 43 and result.sources[0].stats["kept"] == 43
    assert len(result.events) == 43


def test_default_page_list_is_the_verified_one():
    assert PAGES[0] == "" and "koncerty" in PAGES and len(PAGES) == len(set(PAGES))
    assert BASE == "https://bilet.mos.ru"
