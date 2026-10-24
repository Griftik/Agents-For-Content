"""collect_all: падение одного источника не прерывает остальные, сводка по источникам."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import pytest

from leisure.collectors import base
from leisure.collectors.base import Collector, CollectorError, CollectResult, collect_all, register
from leisure.normalize.schema import RawEvent

FROM, TO = date(2026, 10, 23), date(2026, 10, 25)


@dataclass
class _Stats:
    pages: int = 0


def raw(source: str, n: int) -> RawEvent:
    return RawEvent(source=source, url=f"https://{source}.example/{n}", title=f"Событие {n}")


@pytest.fixture
def registry(monkeypatch):
    reg: dict = {}
    monkeypatch.setattr(base, "REGISTRY", reg)
    return reg


def make_collectors():
    @register
    class Broken(Collector):
        name = "broken"

        def collect(self, city, date_from, date_to):
            raise CollectorError("источник недоступен (403)")

    @register
    class Good(Collector):
        name = "good"

        def __init__(self):
            self.stats = _Stats()

        def collect(self, city, date_from, date_to):
            self.stats.pages = 2
            return [raw("good", 1), raw("good", 2)]

    return Broken, Good


def test_one_source_fails_others_continue(registry):
    make_collectors()
    result = collect_all("Москва", FROM, TO)
    assert isinstance(result, CollectResult)
    events, sources = result                                   # распаковка как кортеж
    assert [e.title for e in events] == ["Событие 1", "Событие 2"]
    by = {r.source: r for r in sources}
    assert by["broken"].ok is False and by["broken"].error == "источник недоступен (403)" and by["broken"].count == 0
    assert by["good"].ok is True and by["good"].count == 2 and by["good"].error == "" and by["good"].stats == {"pages": 2}
    assert [r.source for r in result.failed] == ["broken"]


def test_failing_source_after_good_one_keeps_earlier_events(registry):
    # порядок обратный: хороший первым, упавший вторым — события хорошего остаются
    class Good(Collector):
        name = "good"
        def collect(self, city, date_from, date_to):
            return [raw("good", 1)]
    class Boom(Collector):
        name = "boom"
        def collect(self, city, date_from, date_to):
            raise ZeroDivisionError("division by zero")
    register(Good), register(Boom)
    result = collect_all("Москва", FROM, TO)
    assert len(result.events) == 1
    (failed,) = result.failed
    assert failed.source == "boom" and "неожиданная ошибка ZeroDivisionError: division by zero" in failed.error


def test_failure_is_logged_with_source_name_and_reason(registry, caplog):
    make_collectors()
    with caplog.at_level(logging.WARNING, logger="leisure.collectors.base"):
        collect_all("Москва", FROM, TO)
    assert any("«broken»" in r.getMessage() and "403" in r.getMessage() for r in caplog.records)


def test_constructor_failure_is_contained(registry):
    class BadInit(Collector):
        name = "bad_init"
        def __init__(self):
            raise RuntimeError("нет настроек")
        def collect(self, city, date_from, date_to):
            return []
    register(BadInit)
    result = collect_all("Москва", FROM, TO)
    assert result.events == [] and "нет настроек" in result.failed[0].error


def test_names_filter_and_unknown_names_are_reported(registry):
    make_collectors()
    result = collect_all("Москва", FROM, TO, names=["good", "timepad"])
    assert [r.source for r in result.sources] == ["timepad", "good"]
    assert result.failed[0].source == "timepad" and "не зарегистрирован" in result.failed[0].error
    assert len(result.events) == 2


def test_city_filter(registry):
    make_collectors()
    assert collect_all("Казань", FROM, TO) == ([], [])                 # никто не умеет — молча пусто
    explicit = collect_all("Казань", FROM, TO, names=["good"])         # явно просили — ошибка в сводке
    assert explicit.events == [] and "не поддерживается" in explicit.failed[0].error


def test_keyboard_interrupt_is_not_swallowed(registry):
    class Stop(Collector):
        name = "stop"
        def collect(self, city, date_from, date_to):
            raise KeyboardInterrupt
    register(Stop)
    with pytest.raises(KeyboardInterrupt):
        collect_all("Москва", FROM, TO)


def test_real_registry_roundtrip_with_kudago_robots_refusal(monkeypatch):
    """Настоящий KudaGo-коллектор, сеть подменена: robots.txt запрещает API → ошибка в сводке, а не исключение."""
    import httpx

    from leisure import settings
    from leisure.collectors import kudago

    transport = httpx.MockTransport(lambda r: httpx.Response(200, text="User-agent: *\nDisallow: /public-api\n"))
    monkeypatch.setattr(settings, "COLLECTORS_RESPECT_ROBOTS", True)
    real = httpx.Client
    monkeypatch.setattr(kudago.httpx, "Client", lambda *a, **kw: real(transport=transport))
    result = collect_all("Москва", FROM, TO, names=["kudago"])
    assert result.events == [] and "robots.txt запрещает /public-api" in result.failed[0].error
