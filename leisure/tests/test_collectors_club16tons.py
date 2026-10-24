"""Коллектор клуба «16 Тонн» (16tons.ru, JSON-LD). Фикстура — ЖИВОЙ ответ главной страницы, снятый 2026-10-24
(остались только блоки разметки, без правок; fixtures/collectors_live_snapshots.json) и настоящий robots.txt. Сети нет."""
from __future__ import annotations

import gzip
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest

from leisure.collectors import load_collectors
from leisure.collectors.base import REGISTRY, CollectorError, collect_all
from leisure.collectors.club16tons import Club16TonsCollector

FIX = Path(__file__).with_name("fixtures")


def load(name: str) -> str:
    gz = FIX / f"{name}.gz"
    return gzip.open(gz, "rt", encoding="utf-8").read() if gz.exists() else (FIX / name).read_text(encoding="utf-8")


FROM, TO = date(2026, 10, 24), date(2026, 11, 6)
NOW = datetime(2026, 10, 24, 12, 0, 0, tzinfo=timezone.utc)


def site(page: str | None = None, robots: str | None = None, status: int = 200):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.host == "www.16tons.ru"
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=load("robots_club16tons.txt") if robots is None else robots)
        return httpx.Response(status, text=load("club16tons_home.html") if page is None else page)

    return httpx.Client(transport=httpx.MockTransport(handler)), requests


def make(**site_kw):
    client, requests = site(**site_kw)
    return Club16TonsCollector(client, sleep=lambda s: None, clock=lambda: NOW), requests


def test_live_snapshot_two_weeks():
    c, requests = make()
    events = c.collect("Москва", FROM, TO)
    assert len(events) == 31
    assert (c.stats.fetched, c.stats.kept, c.stats.outside_window, c.stats.duplicates) == (118, 31, 87, 0)
    assert [r.url.path for r in requests] == ["/robots.txt", "/"]
    for e in events:
        assert e.source == "club16tons" and e.venue == "Клуб 16 Тонн" and e.categories == ["Концерты"]
        assert e.url.startswith("https://www.16tons.ru/concert/")  # страница концерта, а не главная
        assert e.address == "Москва, Пресненский Вал, 6, стр. 1"
    assert len({e.url for e in events}) == 31


def test_known_concert_has_date_without_invented_time_and_price():
    c, _ = make()
    events = {e.url: e for e in c.collect("Москва", FROM, TO)}
    e = events["https://www.16tons.ru/concert/2026-mankun-26oct/"]
    assert e.title == "Мăнкун. Chuvash Seasons"
    assert e.date_text == "2026-10-26"  # в разметке T00:00:00 — клуб время не указывает, не придумываем
    assert e.price_text == "от 1500 ₽" and e.text.startswith("Группа исполняет чувашские народные песни")
    assert "&nbsp;" not in e.text and "\xa0" not in e.text
    assert events["https://www.16tons.ru/concert/2026-garageband-26oct/"].price_text == ""  # в разметке цены нет


def test_window_edges():
    c, _ = make()
    one_day = c.collect("Москва", date(2026, 10, 26), date(2026, 10, 26))
    assert one_day and all(e.date_text == "2026-10-26" for e in one_day)
    assert c.collect("Москва", date(2030, 1, 1), date(2030, 1, 2)) == []


def test_robots_closed_root_stops_before_any_page_request():
    c, requests = make(robots="User-agent: *\nDisallow: /\n")
    with pytest.raises(CollectorError, match="закрыто robots.txt"):
        c.collect("Москва", FROM, TO)
    assert [r.url.path for r in requests] == ["/robots.txt"]


def test_403_is_reported_not_bypassed():
    c, _ = make(status=403)
    with pytest.raises(CollectorError, match="Защиту не обходим"):
        c.collect("Москва", FROM, TO)


def test_page_without_markup_is_reported():
    c, _ = make(page="<html>Сайт на реконструкции</html>")
    with pytest.raises(CollectorError, match="разметка изменилась"):
        c.collect("Москва", FROM, TO)


def test_events_without_concert_page_link_are_skipped_and_duplicates_collapsed():
    block = (
        '<script type="application/ld+json">{"@type":"MusicEvent","name":"Без ссылки","startDate":"2026-10-27T00:00:00+03:00","offers":[{"price":"100"}]}</script>'
        '<script type="application/ld+json">{"@type":"MusicEvent","name":"Ок","startDate":"2026-10-27T20:30:00+03:00","offers":{"price":"700","url":"https://www.16tons.ru/concert/ok/"}}</script>'
        '<script type="application/ld+json">{"@type":"MusicEvent","name":"Ок ещё раз","startDate":"2026-10-27T20:30:00+03:00","offers":[{"url":"https://www.16tons.ru/concert/ok/"}]}</script>'
    )
    c, _ = make(page=block)
    events = c.collect("Москва", FROM, TO)
    assert [(e.title, e.date_text, e.price_text) for e in events] == [("Ок", "2026-10-27 20:30", "от 700 ₽")]
    assert (c.stats.skipped, c.stats.duplicates) == (1, 1)


def test_other_city_and_reversed_dates():
    c, requests = make()
    with pytest.raises(CollectorError, match="не поддерживается"):
        c.collect("Самара", FROM, TO)
    with pytest.raises(ValueError):
        c.collect("Москва", TO, FROM)
    assert requests == []


def test_registered_and_picked_up_by_collect_all(monkeypatch):
    assert "club16tons" in load_collectors() and REGISTRY["club16tons"] is Club16TonsCollector
    client, _ = site()

    class OnFixtures(Club16TonsCollector):
        def __init__(self):
            super().__init__(client)

    monkeypatch.setitem(REGISTRY, "club16tons", OnFixtures)
    result = collect_all("Москва", FROM, TO, names=["club16tons"])
    assert result.sources[0].ok and result.sources[0].count == 31
