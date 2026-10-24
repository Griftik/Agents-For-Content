"""Коллектор KudaGo: разбор сохранённой фикстуры, пагинация, ошибки. Сеть не трогаем: httpx.MockTransport."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from leisure import settings
from leisure.collectors import load_collectors
from leisure.collectors.base import REGISTRY, CollectorError
from leisure.collectors.kudago import (
    API_URL,
    MSK,
    PAUSE_SEC,
    KudaGoCollector,
    _fmt_occurrence,
    _parse_occurrences,
)
from leisure.normalize.llm import build_prompt
from leisure.normalize.schema import RawEvent

FIXTURE = json.loads((Path(__file__).with_name("fixtures") / "kudago_events.json").read_text(encoding="utf-8"))
PAGES = FIXTURE["pages"]
FROM, TO = date(2026, 10, 23), date(2026, 10, 25)
ROBOTS_OK = "User-agent: *\nDisallow: /account/\nDisallow: /search/\n"
ROBOTS_NO_API = "User-agent: *\nDisallow: /account/\nDisallow: /public-api\n"
NOW = datetime(2026, 10, 24, 9, 0, tzinfo=timezone.utc)


class FakeKudaGo:
    """Подменяет сервер: отдаёт страницы фикстуры и robots.txt, записывает все запросы."""

    def __init__(self, pages=PAGES, robots: tuple[int, str] = (200, ROBOTS_OK), api_status: int = 200):
        self.pages, self.robots, self.api_status = pages, robots, api_status
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/robots.txt":
            return httpx.Response(self.robots[0], text=self.robots[1])
        assert request.url.path == "/public-api/v1.4/events/"
        if self.api_status != 200:
            return httpx.Response(self.api_status, text="<html>nope</html>")
        page = int(request.url.params.get("page", "1"))
        return httpx.Response(200, json=self.pages[min(page, len(self.pages)) - 1])

    @property
    def api_requests(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path.startswith("/public-api")]


def make(fake: FakeKudaGo | None = None, **kw) -> tuple[KudaGoCollector, FakeKudaGo, list[float]]:
    fake = fake or FakeKudaGo()
    sleeps: list[float] = []
    client = httpx.Client(transport=httpx.MockTransport(fake))
    kw.setdefault("respect_robots", True)  # тесты не зависят от настройки окружения; настройка проверяется отдельно
    return KudaGoCollector(client, sleep=sleeps.append, clock=lambda: NOW, **kw), fake, sleeps


@pytest.fixture
def run():
    col, fake, sleeps = make()
    events = col.collect("Москва", FROM, TO)
    return col, fake, sleeps, {e.url.rstrip("/").rsplit("/", 1)[-1]: e for e in events}, events


# ─── разбор фикстуры ───

def test_filters_dedups_and_counts(run):
    col, fake, sleeps, by_slug, events = run
    assert [e.title for e in events] == [
        "спектакль «Дюймовочка»", "выставка «Шито-вышито»", "вечеринка «Ночь музеев на крыше»",
        "постоянная экспозиция «Москва в миниатюре»", "лекция «Город и память»", "концерт «Осенний джаз»",
    ]
    s = col.stats
    assert (s.pages, s.fetched, s.kept) == (2, 9, 6)
    assert s.outside_window == 1  # «Весенний джаз» 10 октября: API мог отдать, мы отсеяли
    assert s.skipped == 1         # карточка без site_url
    assert s.duplicates == 1      # id 101 на второй странице
    assert s.total_in_api == 7 and not s.truncated
    assert all(isinstance(e, RawEvent) and e.source == "kudago" for e in events)
    assert all(e.collected_at == "2026-10-24T09:00:00+00:00" for e in events)


def test_single_card_fields(run):
    e = run[3]["koncert-dyujmovochka"]
    assert e.url == "http://kudago.com/msk/event/koncert-dyujmovochka/"  # ссылка на первоисточник (лицензия)
    assert e.venue == "Московский международный Дом музыки (ММДМ)"
    assert e.price_text == "от 1200 до 2400 рублей в абонементе"
    assert e.date_text == "2026-10-24 12:00; 2026-10-25 12:00"  # показ 7 ноября в текст не попал
    assert e.text.count("Сказка Андерсена на сцене — для самых маленьких.") == 1  # описание не дублируется в body_text
    assert "<" not in e.text and "&mdash;" not in e.text and "1 час 10 минут" in e.text
    assert e.text.splitlines()[-1] == "Теги KudaGo: play, 6+, performances for children"  # для тэгов поля нет
    # адрес, метро, возраст, координаты и категории — отдельными полями, а не строками текста
    assert (e.address, e.metro) == ("Космодамианская наб., 52, стр. 8", "Павелецкая")
    assert (e.lat, e.lon) == (55.73325, 37.6466)
    assert e.age_restriction == "6+" and e.categories == ["theater"]
    assert e.place_name == ""
    for label in ("Возраст:", "Адрес:", "Метро:", "Координаты:", "Категории"):
        assert label not in e.text


@pytest.mark.parametrize("slug,date_text", [
    ("vystavka-shito-vyshito", "период с 2026-10-01 по 2026-12-31, часы 10:00–21:00"),   # выставка с диапазоном
    ("vecherinka-noch-na-kryshe", "2026-10-24 23:00 — 2026-10-25 06:00"),                # через полночь
    ("moskva-v-miniatyure", "с 2020-03-01, дата окончания не указана"),                  # бессрочно
    ("lekciya-gorod-i-pamyat", "2026-10-23 19:30"),                                      # первый день окна включён
])
def test_date_text_forms(run, slug, date_text):
    assert run[3][slug].date_text == date_text


def test_missing_data_stays_empty_not_invented(run):
    night = run[3]["vecherinka-noch-na-kryshe"]
    assert night.venue == "" and night.price_text == "бесплатно"  # place = null; is_free = true
    assert (night.address, night.metro, night.lat, night.lon) == ("", "", None, None)
    assert night.age_restriction == "18+" and night.categories == ["party"]
    lecture = run[3]["lekciya-gorod-i-pamyat"]
    assert lecture.price_text == ""                                # цены нет, не бесплатно → пусто
    assert lecture.age_restriction == ""
    assert lecture.text.startswith("Лекция & дискуссия.")          # теги и сущности вычищены
    assert run[3]["moskva-v-miniatyure"].price_text == ""


def test_raw_event_goes_into_normalizer_prompt(run):
    prompt = build_prompt(run[3]["vystavka-shito-vyshito"], "2026-10-23", "2026-10-25")
    assert "период с 2026-10-01 по 2026-12-31" in prompt and "Музей декоративного искусства" in prompt
    assert "\nАдрес: ул. Делегатская, 3\n" in prompt and "\nМетро: Цветной бульвар\n" in prompt
    assert "\nКатегории источника: exhibition\n" in prompt


def test_bad_coordinates_are_dropped_not_fatal():
    item = {**PAGES[1]["results"][1], "place": {"title": "Где-то", "coords": {"lat": 955.0, "lon": 37.0}}}
    col, _, _ = make(FakeKudaGo(pages=[{"count": 1, "next": None, "previous": None, "results": [item]}]))
    (e,) = col.collect("Москва", FROM, TO)
    assert (e.lat, e.lon) == (None, None) and e.venue == "Где-то"


# ─── запросы, пагинация, вежливость ───

def test_request_params_headers_and_pause(run):
    _, fake, sleeps, *_ = run
    first, second = fake.api_requests
    q = first.url.params
    assert str(first.url).startswith(API_URL)
    assert q["location"] == "msk" and q["page"] == "1" and q["page_size"] == "100"
    assert q["text_format"] == "plain" and q["order_by"] == "id" and q["lang"] == "ru"
    assert set(q["expand"].split(",")) == {"place", "dates"}
    assert {"id", "title", "dates", "place", "price", "site_url", "age_restriction", "categories"} <= set(q["fields"].split(","))
    assert int(q["actual_since"]) == int(datetime(2026, 10, 23, tzinfo=MSK).timestamp())
    assert int(q["actual_until"]) == int(datetime(2026, 10, 26, tzinfo=MSK).timestamp()) - 1
    assert second.url.params["page"] == "2"
    assert first.headers["User-Agent"].startswith("LeisurePlannerBot/") and first.headers["Accept"] == "application/json"
    assert sleeps == [PAUSE_SEC]  # одна пауза между двумя страницами, после последней пауз нет


def test_page_cap_stops_and_flags_truncation():
    endless_pages = [{**PAGES[0], "next": "https://kudago.com/public-api/v1.4/events/?page=99"}]
    col, fake, sleeps = make(FakeKudaGo(pages=endless_pages), max_pages=3)
    col.collect("Москва", FROM, TO)
    assert len(fake.api_requests) == 3 and col.stats.truncated and col.stats.pages == 3
    assert len(sleeps) == 2


def test_empty_result_is_not_an_error():
    empty = [{"count": 0, "next": None, "previous": None, "results": []}]
    col, fake, _ = make(FakeKudaGo(pages=empty))
    assert col.collect("Москва", FROM, TO) == [] and len(fake.api_requests) == 1


# ─── ошибки ───

def test_403_is_clear_error_without_retries():
    col, fake, sleeps = make(FakeKudaGo(api_status=403))
    with pytest.raises(CollectorError, match=r"403.*(IP|региону).*не обходим"):
        col.collect("Москва", FROM, TO)
    assert len(fake.api_requests) == 1 and sleeps == []


def test_5xx_is_retried_then_reported():
    col, fake, sleeps = make(FakeKudaGo(api_status=503), retries=2)
    with pytest.raises(CollectorError, match=r"недоступен.*503.*попыток: 3"):
        col.collect("Москва", FROM, TO)
    assert len(fake.api_requests) == 3 and len(sleeps) == 2


def test_transient_failure_recovers():
    calls = {"n": 0}
    base = FakeKudaGo(pages=[PAGES[1]])

    def flaky(request):
        if request.url.path.startswith("/public-api"):
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(429, headers={"Retry-After": "7"})
        return base(request)

    sleeps: list[float] = []
    col = KudaGoCollector(httpx.Client(transport=httpx.MockTransport(flaky)), sleep=sleeps.append, clock=lambda: NOW)
    assert len(col.collect("Москва", FROM, TO)) == 2
    assert sleeps == [7.0]  # уважаем Retry-After


def test_timeout_is_reported_as_unavailable():
    def boom(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS_OK)
        raise httpx.ConnectTimeout("timed out", request=request)

    col = KudaGoCollector(httpx.Client(transport=httpx.MockTransport(boom)), sleep=lambda s: None, retries=1)
    with pytest.raises(CollectorError, match=r"недоступен.*ConnectTimeout"):
        col.collect("Москва", FROM, TO)


@pytest.mark.parametrize("pages", [
    [{"unexpected": True}],            # нет results
    [{"results": "строка"}],           # results не список
])
def test_unexpected_json_shape(pages):
    col, _, _ = make(FakeKudaGo(pages=pages))
    with pytest.raises(CollectorError, match="неожиданный формат"):
        col.collect("Москва", FROM, TO)


def test_non_json_body():
    def html_page(request):
        return httpx.Response(200, text=ROBOTS_OK if request.url.path == "/robots.txt" else "<html></html>")

    col = KudaGoCollector(httpx.Client(transport=httpx.MockTransport(html_page)), sleep=lambda s: None)
    with pytest.raises(CollectorError, match="не JSON"):
        col.collect("Москва", FROM, TO)


def test_bad_card_is_skipped_not_fatal():
    broken = {"count": 2, "next": None, "previous": None, "results": [
        "мусор",
        {"id": 1, "title": "ok", "site_url": "http://kudago.com/msk/event/x/", "dates": "не список"},
        PAGES[1]["results"][1],
    ]}
    col, _, _ = make(FakeKudaGo(pages=[broken]))
    events = col.collect("Москва", FROM, TO)
    assert [e.title for e in events] == ["концерт «Осенний джаз»"]
    assert col.stats.skipped == 1 and col.stats.outside_window == 1


def test_unknown_city_and_reversed_dates():
    col, fake, _ = make()
    with pytest.raises(CollectorError, match="Казань"):
        col.collect("Казань", FROM, TO)
    with pytest.raises(ValueError):
        col.collect("Москва", TO, FROM)
    assert fake.requests == []


# ─── robots.txt ───

def test_robots_disallow_stops_before_any_api_call():
    col, fake, _ = make(FakeKudaGo(robots=(200, ROBOTS_NO_API)))
    with pytest.raises(CollectorError, match="robots.txt запрещает /public-api"):
        col.collect("Москва", FROM, TO)
    assert fake.api_requests == []


def test_robots_can_be_waived_explicitly():
    col, fake, _ = make(FakeKudaGo(robots=(200, ROBOTS_NO_API)), respect_robots=False)
    assert len(col.collect("Москва", FROM, TO)) == 6
    assert all(r.url.path != "/robots.txt" for r in fake.requests)


@pytest.mark.parametrize("setting,arg,expected", [
    (False, None, False),   # решение владельца от 24.10.2026: по умолчанию не читаем
    (True, None, True),     # включили в окружении — читаем
    (False, True, True),    # явный аргумент сильнее настройки
    (True, False, False),
])
def test_robots_default_comes_from_settings(monkeypatch, setting, arg, expected):
    monkeypatch.setattr(settings, "COLLECTORS_RESPECT_ROBOTS", setting)
    assert KudaGoCollector(respect_robots=arg).respect_robots is expected


def test_settings_switch_changes_behaviour_end_to_end(monkeypatch):
    for setting, blocked in ((True, True), (False, False)):
        monkeypatch.setattr(settings, "COLLECTORS_RESPECT_ROBOTS", setting)
        fake = FakeKudaGo(robots=(200, ROBOTS_NO_API))
        col = KudaGoCollector(httpx.Client(transport=httpx.MockTransport(fake)), sleep=lambda s: None)
        if blocked:
            with pytest.raises(CollectorError, match="COLLECTORS_RESPECT_ROBOTS"):
                col.collect("Москва", FROM, TO)
            assert fake.api_requests == []
        else:
            assert len(col.collect("Москва", FROM, TO)) == 6
            assert all(r.url.path != "/robots.txt" for r in fake.requests)


def test_settings_default_is_off():
    """Без переменной окружения учёт robots выключен (решение владельца)."""
    import importlib
    import os
    saved = os.environ.pop("COLLECTORS_RESPECT_ROBOTS", None)
    try:
        assert importlib.reload(settings).COLLECTORS_RESPECT_ROBOTS is False
        os.environ["COLLECTORS_RESPECT_ROBOTS"] = "1"
        assert importlib.reload(settings).COLLECTORS_RESPECT_ROBOTS is True
    finally:
        os.environ.pop("COLLECTORS_RESPECT_ROBOTS", None)
        if saved is not None:
            os.environ["COLLECTORS_RESPECT_ROBOTS"] = saved
        importlib.reload(settings)


@pytest.mark.parametrize("status,ok", [(404, True), (403, False), (503, False)])
def test_robots_status_handling(status, ok):
    col, fake, _ = make(FakeKudaGo(robots=(status, "")))
    if ok:
        assert len(col.collect("Москва", FROM, TO)) == 6
    else:
        with pytest.raises(CollectorError, match="robots.txt"):
            col.collect("Москва", FROM, TO)
        assert fake.api_requests == []


# ─── реестр ───

def test_registered_and_discoverable():
    assert "kudago" in load_collectors()
    assert REGISTRY["kudago"] is KudaGoCollector
    assert KudaGoCollector.cities == ("Москва",)


# ─── даты: углы ───

def _ts(*args) -> int:
    return int(datetime(*args, tzinfo=MSK).timestamp())


def test_dates_without_expand_use_timestamps():
    occ = _parse_occurrences([{"start": _ts(2026, 10, 24, 19, 0), "end": _ts(2026, 10, 24, 19, 0)}])
    assert [_fmt_occurrence(o) for o in occ] == ["2026-10-24 19:00"]
    midnight = _parse_occurrences([{"start": _ts(2026, 10, 24), "end": _ts(2026, 10, 24)}])
    assert [_fmt_occurrence(o) for o in midnight] == ["2026-10-24"]  # полночь = «времени нет», а не 00:00


def test_endless_sentinel_without_flag_and_startless():
    occ = _parse_occurrences([{"start": _ts(2026, 1, 1), "end": 253370754000},
                              {"start": -62135433000, "end": _ts(2026, 10, 24, 12), "is_startless": True}])
    assert [_fmt_occurrence(o) for o in occ] == ["с 2026-01-01, дата окончания не указана", "до 2026-10-24"]


def test_window_edges():
    w0, w1 = datetime(2026, 10, 23, tzinfo=MSK), datetime(2026, 10, 26, tzinfo=MSK)
    def hit(start, end):
        return _parse_occurrences([{"start": int(start.timestamp()), "end": int(end.timestamp())}])[0].intersects(w0, w1)
    assert not hit(w1, w1 + timedelta(hours=2))                       # начинается ровно в полночь после окна
    assert hit(w1 - timedelta(minutes=1), w1 + timedelta(hours=2))    # начался в последнюю минуту окна
    assert not hit(w0 - timedelta(hours=3), w0 - timedelta(seconds=1))
    assert hit(w0 - timedelta(hours=3), w0)                           # ночное событие, закончившееся утром 23-го
