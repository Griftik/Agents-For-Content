"""Коллектор Афиши (afisha.ru, разметка JSON-LD). Фикстуры — ЖИВЫЕ ответы сайта, снятые 2026-10-24 (fixtures/collectors_live_snapshots.json):
три страницы разделов (остались только блоки разметки schema.org, без правок) и настоящий robots.txt. Сети нет: httpx.MockTransport."""
from __future__ import annotations

import gzip
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest

from leisure.collectors import load_collectors
from leisure.collectors.afisha import PAGES, AfishaCollector, canonical_url
from leisure.collectors.base import REGISTRY, CollectorError, collect_all
from leisure.normalize.llm import build_prompt

FIX = Path(__file__).with_name("fixtures")


def load(name: str) -> str:
    gz = FIX / f"{name}.gz"
    return gzip.open(gz, "rt", encoding="utf-8").read() if gz.exists() else (FIX / name).read_text(encoding="utf-8")


ROUTES = {"/msk/party/": "afisha_party.html", "/msk/events/": "afisha_events.html", "/msk/excursions/": "afisha_excursions.html"}
LIVE_PAGES = {"party": "Вечеринки", "events": "", "excursions": "Экскурсии"}
FROM, TO = date(2026, 10, 24), date(2026, 11, 6)
NOW = datetime(2026, 10, 24, 12, 0, 0, tzinfo=timezone.utc)


class FakeSite:
    def __init__(self, routes=ROUTES, robots: str | None = None, overrides: dict[str, httpx.Response] | None = None):
        self.routes, self.overrides = routes, overrides or {}
        self.robots = load("robots_afisha.txt") if robots is None else robots
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.url.host == "www.afisha.ru"
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
    c = AfishaCollector(httpx.Client(transport=httpx.MockTransport(site)), sleep=sleeps.append, clock=lambda: NOW, **kw)
    return c, site, sleeps


# ─── живой снимок ───

def test_live_snapshot_gives_events_with_clean_source_links():
    c, _, sleeps = make()
    events = c.collect("Москва", FROM, TO)
    assert len(events) == 33
    assert (c.stats.pages, c.stats.fetched, c.stats.kept) == (3, 45, 33)
    assert c.stats.outside_window == 10 and c.stats.duplicates == 2
    assert sleeps == [2.0, 2.0]
    assert len({e.url for e in events}) == len(events)
    for e in events:
        assert e.source == "afisha" and e.title and e.date_text
        assert e.url.startswith("https://www.afisha.ru/") and "?" not in e.url  # ?priorityCity=… и ?tab=schedule срезаны


def test_party_card_fields():
    c, _, _ = make()
    e = next(x for x in c.collect("Москва", FROM, TO) if x.url.endswith("/vernite-mne-moy-2007-6053680/"))
    assert e.title == "Верните мне мой 2007"
    assert e.date_text == "2026-10-30 23:00"
    assert e.venue == "Summer Punch" and e.address == "Столешников пер., 8"
    assert e.categories == ["Вечеринки", "музыка"]
    assert e.price_text == ""  # в разметке цена 0: «бесплатно» или «не указана», не угадываем


def test_run_of_a_show_is_a_period_and_unknown_venue_is_left_empty():
    c, _, _ = make()
    events = {x.url: x for x in c.collect("Москва", FROM, TO)}
    run = events["https://www.afisha.ru/performance/podyskivayu-zhenu-nedorogo-85589/"]
    assert run.date_text == "период с 2026-10-24 19:00 по 2027-03-28 19:00"
    assert run.venue == "" and run.address == ""  # в источнике «Неизвестно»
    assert not any("Неизвестно" in (e.venue + e.address) for e in events.values())


def test_exhibition_without_time_shows_dates_only_and_page_hint_is_a_category():
    c, _, _ = make()
    events = c.collect("Москва", FROM, TO)
    assert any(e.date_text == "период с 2025-12-31 по 2026-12-29" for e in events)
    assert "Экскурсии" in {c for e in events for c in e.categories}
    assert {"спорт", "театр", "выставка"} <= {c for e in events for c in e.categories}


def test_description_goes_to_text_and_prompt_gets_venue():
    c, _, _ = make()
    e = next(x for x in c.collect("Москва", FROM, TO) if x.title == "Вальс-бостон")
    assert e.text.startswith("Мюзикл по хитам")
    assert "Театр Эстрады" in build_prompt(e, "2026-10-24", "2026-11-06")


def test_far_window_gives_nothing_but_counts_it():
    c, _, _ = make()
    assert c.collect("Москва", date(2030, 1, 1), date(2030, 1, 7)) == []
    assert c.stats.outside_window > 0


# ─── robots.txt ───

def test_robots_allow_sections_and_are_read_once():
    c, site, _ = make()
    c.collect("Москва", FROM, TO)
    assert [r.url.path for r in site.requests].count("/robots.txt") == 1
    assert c.stats.blocked_by_robots == 0


def test_robots_closing_a_section_skips_it():
    c, site, _ = make(FakeSite(robots="User-agent: *\nDisallow: /msk/party/\n"))
    c.collect("Москва", FROM, TO)
    assert c.stats.blocked_by_robots == 1 and "/msk/party/" not in {r.url.path for r in site.requests}


def test_robots_closing_everything_is_a_source_error():
    c, _, _ = make(FakeSite(robots="User-agent: *\nDisallow: /\n"))
    with pytest.raises(CollectorError, match="закрыто robots.txt"):
        c.collect("Москва", FROM, TO)


# ─── сбои и разметка ───

def test_blocked_with_403_is_not_bypassed():
    site = FakeSite(routes={}, overrides={f"/msk/{p}/": httpx.Response(403) for p in LIVE_PAGES})
    c, _, _ = make(site)
    with pytest.raises(CollectorError, match="Защиту не обходим"):
        c.collect("Москва", FROM, TO)


def test_one_bad_page_does_not_kill_the_others():
    c, _, _ = make(FakeSite(overrides={"/msk/events/": httpx.Response(404)}))
    events = c.collect("Москва", FROM, TO)
    assert events and c.stats.failed_pages == 1


def test_markup_without_events_is_reported():
    site = FakeSite(overrides={f"/msk/{p}/": httpx.Response(200, text="<html>Афиша переехала</html>") for p in LIVE_PAGES})
    c, _, _ = make(site)
    with pytest.raises(CollectorError, match="разметка изменилась"):
        c.collect("Москва", FROM, TO)


def test_cards_without_title_date_or_link_are_skipped():
    block = (
        '<script type="application/ld+json">[{"@type":"MusicEvent","name":"Ок","url":"https://www.afisha.ru/concert/ok-1/?x=1",'
        '"startDate":"2026-10-25T20:00:00+03:00","location":{"name":"Клуб","address":{"streetAddress":"Улица, 1"}},'
        '"offers":[{"price":"900"},{"price":500},{"price":"abc"}]},'
        '{"@type":"MusicEvent","name":"","url":"https://www.afisha.ru/concert/a/","startDate":"2026-10-25T20:00:00+03:00"},'
        '{"@type":"MusicEvent","name":"Без даты","url":"https://www.afisha.ru/concert/b/"},'
        '{"@type":"MusicEvent","name":"Без ссылки","startDate":"2026-10-25T20:00:00+03:00"},'
        '{"@type":"MusicEvent","name":"Не http","url":"ftp://x/y","startDate":"2026-10-25T20:00:00+03:00"}]</script>'
    )
    c, _, _ = make(FakeSite(routes={}, overrides={"/msk/party/": httpx.Response(200, text=block)}), pages={"party": "Вечеринки"})
    events = c.collect("Москва", FROM, TO)
    assert [(e.title, e.url, e.price_text, e.address) for e in events] == [
        ("Ок", "https://www.afisha.ru/concert/ok-1/", "от 500 ₽", "Улица, 1")]
    assert c.stats.skipped == 4


def test_other_city_and_reversed_dates_rejected_without_requests():
    c, site, _ = make()
    with pytest.raises(CollectorError, match="не поддерживается"):
        c.collect("Сочи", FROM, TO)
    with pytest.raises(ValueError):
        c.collect("Москва", TO, FROM)
    assert site.requests == []


@pytest.mark.parametrize("url, expected", [
    ("https://www.afisha.ru/concert/x-1/?priorityCity=msk", "https://www.afisha.ru/concert/x-1/"),
    ("https://www.afisha.ru/performance/y-2/?tab=schedule#top", "https://www.afisha.ru/performance/y-2/"),
    ("http://www.afisha.ru/a/", "http://www.afisha.ru/a/"),
    ("/relative/", ""), ("ftp://x/y", ""), (None, ""), (123, ""),
])
def test_canonical_url(url, expected):
    assert canonical_url(url) == expected


# ─── реестр и конвейер ───

def test_registered_and_picked_up_by_collect_all(monkeypatch):
    assert "afisha" in load_collectors() and REGISTRY["afisha"] is AfishaCollector
    site = FakeSite()

    class OnFixtures(AfishaCollector):
        def __init__(self):
            super().__init__(httpx.Client(transport=httpx.MockTransport(site)), pages=LIVE_PAGES, sleep=lambda s: None)

    monkeypatch.setitem(REGISTRY, "afisha", OnFixtures)
    result = collect_all("Москва", FROM, TO, names=["afisha"])
    assert result.sources[0].ok and result.sources[0].count == 33 and result.sources[0].stats["duplicates"] == 2


def test_default_sections_are_verified_ones_and_schedule_duplicate_is_excluded():
    assert {"concerts", "theatre", "exhibitions", "party", "standup"} <= set(PAGES)
    assert "schedule_theatre" not in PAGES  # повторяет /theatre/
