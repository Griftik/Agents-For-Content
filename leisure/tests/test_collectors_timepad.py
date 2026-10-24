"""Коллектор Timepad: разбор фикстуры, токен, пагинация, ошибки. Сеть подменена httpx.MockTransport."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest

from leisure.collectors import load_collectors
from leisure.collectors.base import REGISTRY, CollectorError
from leisure.collectors.timepad import (
    API_URL,
    MSK,
    PAUSE_SEC,
    TimepadCollector,
    _parse_dt,
    format_dates,
    format_price,
)
from leisure.normalize.llm import build_prompt

FIXTURE = json.loads((Path(__file__).with_name("fixtures") / "timepad_events.json").read_text(encoding="utf-8"))
PAGES = FIXTURE["pages"]
FROM, TO = date(2026, 10, 23), date(2026, 10, 25)
TOKEN = "secret-token-123"
NOW = datetime(2026, 10, 24, 9, 0, tzinfo=timezone.utc)
NO_TOKEN_BODY = {"response_status": {"error_code": 403, "message": "Запрос требует указание токена"}}


class FakeTimepad:
    def __init__(self, pages=PAGES, status: int = 200, body=None):
        self.pages, self.status, self.body = pages, status, body
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.url.host == "api.timepad.ru" and request.url.path == "/v1/events"
        if self.status != 200:
            return httpx.Response(self.status, json=self.body) if self.body else httpx.Response(self.status, text="x")
        skip = int(request.url.params.get("skip", "0"))
        return httpx.Response(200, json=self.pages[0 if skip == 0 else min(1, len(self.pages) - 1)])


def make(fake: FakeTimepad | None = None, **kw):
    fake = fake or FakeTimepad()
    sleeps: list[float] = []
    kw.setdefault("token", TOKEN)
    col = TimepadCollector(httpx.Client(transport=httpx.MockTransport(fake)), sleep=sleeps.append, clock=lambda: NOW, **kw)
    return col, fake, sleeps


@pytest.fixture
def run():
    col, fake, sleeps = make()
    events = col.collect("Москва", FROM, TO)
    return col, fake, sleeps, {e.url.rstrip("/").rsplit("/", 1)[-1]: e for e in events}, events


def test_filters_dedups_and_counts(run):
    col, _, _, by_id, events = run
    assert sorted(by_id) == ["5001", "5002", "5005", "5007"]
    s = col.stats
    assert (s.pages, s.fetched, s.kept, s.total_in_api) == (2, 8, 4, 8)
    assert (s.outside_window, s.skipped, s.duplicates, s.truncated) == (1, 2, 1, False)  # 5003; 5004 и 5006; 5001 дважды
    assert all(e.source == "timepad" and e.collected_at == "2026-10-24T09:00:00+00:00" for e in events)


def test_full_card(run):
    e = run[3]["5001"]
    assert e.url == "https://lektorij.timepad.ru/event/5001/" and e.title == "Лекция «Город и память»"
    assert e.date_text == "2026-10-24 19:00–21:00"
    assert e.price_text == "от 500 ₽ (до 1500 ₽)"                      # снятый с продажи билет в 99 ₽ не считается
    assert e.address == "Москва, ул. Большая Никитская, 13, Клуб «Лекторий»" and e.venue == ""
    assert (e.lat, e.lon) == (55.7558, 37.6024)
    assert e.age_restriction == "16+" and e.categories == ["Образование", "Лекции"]
    assert e.text.splitlines() == [
        "Разговор об истории московских дворов.", "", "Лектор покажет архивные карты & фотографии.", "2 часа",
        "вопросы после", "Организатор: Лекторий",
    ]
    assert "<" not in e.text


def test_other_cards(run):
    by = run[3]
    assert by["5002"].date_text == "период с 2026-10-25 10:00 по 2026-10-26 18:00" and by["5002"].price_text == "бесплатно"
    assert by["5005"].price_text == "300 ₽" and by["5005"].date_text == "2026-10-23 19:30"   # цена из registration_data
    assert by["5007"].date_text == "2026-10-25 20:00"                                       # дата без пояса — московская
    assert by["5007"].price_text == "" and by["5007"].age_restriction == "" and by["5007"].categories == []
    assert (by["5007"].lat, by["5007"].lon) == (None, None)


def test_raw_event_goes_into_prompt(run):
    prompt = build_prompt(run[3]["5001"], "2026-10-23", "2026-10-25")
    assert "\nАдрес: Москва, ул. Большая Никитская, 13, Клуб «Лекторий»\n" in prompt
    assert "\nВозрастное ограничение: 16+\n" in prompt and "\nКатегории источника: Образование, Лекции\n" in prompt


# ─── токен ───

def test_no_token_is_a_clear_error_and_no_request(monkeypatch):
    monkeypatch.delenv("TIMEPAD_TOKEN", raising=False)
    fake = FakeTimepad()
    col = TimepadCollector(httpx.Client(transport=httpx.MockTransport(fake)))
    with pytest.raises(CollectorError, match=r"нужен токен.*TIMEPAD_TOKEN"):
        col.collect("Москва", FROM, TO)
    assert fake.requests == []


@pytest.mark.parametrize("value", ["", "  ", "REPLACE_ME"])
def test_blank_and_placeholder_tokens_count_as_missing(monkeypatch, value):
    monkeypatch.setenv("TIMEPAD_TOKEN", value)
    with pytest.raises(CollectorError, match="нужен токен"):
        TimepadCollector(httpx.Client(transport=httpx.MockTransport(FakeTimepad()))).collect("Москва", FROM, TO)


def test_token_from_environment_goes_into_bearer_header(monkeypatch):
    monkeypatch.setenv("TIMEPAD_TOKEN", "  env-token  ")
    fake = FakeTimepad(pages=[{"total": 0, "values": []}])
    TimepadCollector(httpx.Client(transport=httpx.MockTransport(fake))).collect("Москва", FROM, TO)
    assert fake.requests[0].headers["Authorization"] == "Bearer env-token"


def test_explicit_token_beats_environment(monkeypatch):
    monkeypatch.setenv("TIMEPAD_TOKEN", "env-token")
    col, fake, _ = make(FakeTimepad(pages=[{"total": 0, "values": []}]), token="arg-token")
    col.collect("Москва", FROM, TO)
    assert fake.requests[0].headers["Authorization"] == "Bearer arg-token"


def test_token_never_leaks_into_errors_or_logs(caplog):
    col, _, _ = make(FakeTimepad(status=503), retries=1)
    with caplog.at_level(logging.DEBUG), pytest.raises(CollectorError) as ei:
        col.collect("Москва", FROM, TO)
    assert TOKEN not in str(ei.value) and TOKEN not in caplog.text


# ─── запросы ───

def test_request_params_and_pause(run):
    _, fake, sleeps, *_ = run
    first, second = fake.requests
    q = first.url.params
    assert str(first.url).startswith(API_URL)
    assert q["cities"] == "Москва" and q["limit"] == "100" and q["skip"] == "0" and q["sort"] == "+starts_at"
    assert q["starts_at_min"] == "2026-10-23T00:00:00+03:00" and q["starts_at_max"] == "2026-10-25T23:59:59+03:00"
    assert second.url.params["skip"] == "6"                       # сдвиг по числу реально полученных карточек
    assert first.headers["Authorization"] == f"Bearer {TOKEN}" and first.headers["User-Agent"].startswith("LeisurePlannerBot/")
    assert sleeps == [PAUSE_SEC]


def test_page_cap():
    endless = [{"total": 10_000, "values": PAGES[0]["values"]}]
    col, fake, sleeps = make(FakeTimepad(pages=endless), max_pages=3)
    col.collect("Москва", FROM, TO)
    assert len(fake.requests) == 3 and col.stats.truncated and len(sleeps) == 2


def test_empty_result_is_not_an_error():
    col, fake, _ = make(FakeTimepad(pages=[{"total": 0, "values": []}]))
    assert col.collect("Москва", FROM, TO) == [] and len(fake.requests) == 1


# ─── ошибки ───

def test_403_with_token_reports_message_and_does_not_retry():
    col, fake, sleeps = make(FakeTimepad(status=403, body=NO_TOKEN_BODY))
    with pytest.raises(CollectorError, match=r"403 «Запрос требует указание токена».*токен недействителен"):
        col.collect("Москва", FROM, TO)
    assert len(fake.requests) == 1 and sleeps == []


def test_5xx_retried_then_reported():
    col, fake, sleeps = make(FakeTimepad(status=502), retries=2)
    with pytest.raises(CollectorError, match=r"Timepad недоступен.*502.*попыток: 3"):
        col.collect("Москва", FROM, TO)
    assert len(fake.requests) == 3 and len(sleeps) == 2


def test_timeout_reported():
    def boom(request):
        raise httpx.ConnectTimeout("timed out", request=request)

    col = TimepadCollector(httpx.Client(transport=httpx.MockTransport(boom)), token=TOKEN, retries=0, sleep=lambda s: None)
    with pytest.raises(CollectorError, match="ConnectTimeout"):
        col.collect("Москва", FROM, TO)


@pytest.mark.parametrize("pages", [[{"total": 1}], [{"values": "x"}]])
def test_unexpected_shape(pages):
    col, _, _ = make(FakeTimepad(pages=pages))
    with pytest.raises(CollectorError, match="неожиданный формат"):
        col.collect("Москва", FROM, TO)


def test_non_json_body():
    col = TimepadCollector(httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html>"))),
                           token=TOKEN, sleep=lambda s: None)
    with pytest.raises(CollectorError, match="не JSON"):
        col.collect("Москва", FROM, TO)


def test_bad_card_and_bad_coordinates_do_not_break_the_run():
    good = PAGES[1]["values"][1]
    bad_coords = {**good, "id": 1, "location": {"city": "Москва", "address": "Москва", "coordinates": [955, 37]}}
    col, _, _ = make(FakeTimepad(pages=[{"total": 3, "values": ["мусор", {"id": 2, "name": "x", "starts_at": "вчера"}, bad_coords]}]))
    (e,) = col.collect("Москва", FROM, TO)
    assert (e.lat, e.lon) == (None, None) and e.address == "Москва"
    assert col.stats.skipped == 2


def test_unknown_city_and_reversed_dates():
    col, fake, _ = make()
    with pytest.raises(CollectorError, match="Казань"):
        col.collect("Казань", FROM, TO)
    with pytest.raises(ValueError):
        col.collect("Москва", TO, FROM)
    assert fake.requests == []


def test_registered():
    assert "timepad" in load_collectors() and REGISTRY["timepad"] is TimepadCollector


# ─── форматирование ───

@pytest.mark.parametrize("item,expected", [
    ({"ticket_types": [{"price": 0}]}, "бесплатно"),
    ({"ticket_types": [{"price": 0}, {"price": 800}]}, "от 0 ₽, платные до 800 ₽"),
    ({"ticket_types": [{"price": 1200}]}, "1200 ₽"),
    ({"ticket_types": [{"price": 99.5}, {"price": 200}]}, "от 99.50 ₽ (до 200 ₽)"),
    ({"ticket_types": [{"price": 300, "is_active": False}], "registration_data": {"price_min": 500, "price_max": 500}}, "500 ₽"),
    ({"ticket_types": []}, ""),                                   # неизвестно ≠ бесплатно
    ({"ticket_types": [{"price": None}], "registration_data": None}, ""),
])
def test_format_price(item, expected):
    assert format_price(item) == expected


def test_format_dates_and_parse():
    a = datetime(2026, 10, 24, 23, 0, tzinfo=MSK)
    assert format_dates(a, None) == "2026-10-24 23:00"
    assert format_dates(a, datetime(2026, 10, 25, 5, 0, tzinfo=MSK)) == "2026-10-24 23:00 — 2026-10-25 05:00"
    assert _parse_dt("2026-10-24T19:00:00+0300") == _parse_dt("2026-10-24T16:00:00Z") == _parse_dt("2026-10-24T19:00:00")
    assert _parse_dt("") is None and _parse_dt("вчера") is None and _parse_dt(None) is None
