"""Общий интерфейс коллекторов (п. 7.1 спеки): collect(city, date_from, date_to) → list[RawEvent].

Каждый источник — отдельный модуль collectors/<name>.py с классом-наследником Collector и регистрацией
через декоратор @register. Парсинг HTML — только там, где нет API или RSS. Реализации — неделя 7–8 плана.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from leisure.normalize.schema import RawEvent

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


def collect_all(city: str, date_from: date, date_to: date, names: list[str] | None = None) -> list[RawEvent]:
    out: list[RawEvent] = []
    for name, cls in REGISTRY.items():
        if names and name not in names:
            continue
        if city not in cls.cities:
            continue
        out.extend(cls().collect(city, date_from, date_to))
    return out
