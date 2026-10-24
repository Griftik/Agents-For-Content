"""Общий интерфейс коллекторов (п. 7.1 спеки): collect(city, date_from, date_to) → list[RawEvent].

Каждый источник — отдельный модуль collectors/<name>.py с классом-наследником Collector и регистрацией
через декоратор @register. Парсинг HTML — только там, где нет API или RSS. Реализации — неделя 7–8 плана.
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date
from typing import NamedTuple

from leisure.normalize.schema import RawEvent

log = logging.getLogger(__name__)

REGISTRY: dict[str, type["Collector"]] = {}


class CollectorError(RuntimeError):
    """Источник недоступен или ответил не так, как ждали. Сообщение — по-русски, для лога воркера и куратора."""


class Collector(ABC):
    name: str = ""
    cities: tuple[str, ...] = ("Москва",)

    @abstractmethod
    def collect(self, city: str, date_from: date, date_to: date) -> list[RawEvent]:
        """Сырые карточки: заголовок, дата как в источнике, текст, URL."""


def register(cls: type[Collector]) -> type[Collector]:
    if not cls.name:
        raise ValueError("у коллектора должно быть имя")
    REGISTRY[cls.name] = cls
    return cls


@dataclass
class SourceReport:
    """Итог по одному источнику за запуск: что дал или почему молчит. Для воркера и куратора в админке."""

    source: str
    ok: bool
    count: int = 0
    error: str = ""
    seconds: float = 0.0
    stats: dict = field(default_factory=dict)  # счётчики коллектора, если он их ведёт (страницы, вне диапазона, …)


class CollectResult(NamedTuple):
    events: list[RawEvent]
    sources: list[SourceReport]

    @property
    def failed(self) -> list[SourceReport]:
        return [r for r in self.sources if not r.ok]


def _stats_of(collector: Collector | None) -> dict:
    stats = getattr(collector, "stats", None)
    return asdict(stats) if is_dataclass(stats) and not isinstance(stats, type) else {}


def collect_all(
    city: str, date_from: date, date_to: date, names: list[str] | None = None,
) -> CollectResult:
    """Запускает коллекторы по очереди; падение одного источника остальным не мешает.

    `names` — только эти источники; запрошенный, но незарегистрированный (или не умеющий этот город) попадает в сводку
    как ошибка, а не пропадает молча. Возвращает (events, sources): события всех удачных источников и по одной записи
    SourceReport на каждый запущенный источник. Исключения KeyboardInterrupt и SystemExit не перехватываются.
    """
    events: list[RawEvent] = []
    reports: list[SourceReport] = []
    for name in names or []:
        if name not in REGISTRY:
            reports.append(SourceReport(name, False, error="источник не зарегистрирован (вызван ли load_collectors()?)"))
            log.error("collect_all: источник «%s» не зарегистрирован", name)
    for name, cls in REGISTRY.items():
        if names and name not in names:
            continue
        if city not in cls.cities:
            if names:
                reports.append(SourceReport(name, False, error=f"город «{city}» не поддерживается источником"))
            continue
        collector: Collector | None = None
        started = time.monotonic()
        try:
            collector = cls()
            got = collector.collect(city, date_from, date_to)
        except CollectorError as exc:
            error = str(exc)
            log.warning("collect_all: источник «%s» не дал данных: %s", name, error)
        except Exception as exc:  # noqa: BLE001 — любой сбой одного источника не должен ронять остальные
            error = f"неожиданная ошибка {type(exc).__name__}: {exc}"
            log.exception("collect_all: источник «%s» упал: %s", name, error)
        else:
            events.extend(got)
            reports.append(SourceReport(name, True, len(got), seconds=time.monotonic() - started, stats=_stats_of(collector)))
            continue
        reports.append(SourceReport(name, False, error=error, seconds=time.monotonic() - started, stats=_stats_of(collector)))
    return CollectResult(events, reports)
