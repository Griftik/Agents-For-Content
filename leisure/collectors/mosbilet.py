"""Коллектор Мосбилета: официальная афиша города bilet.mos.ru (на неё же переведён раздел mos.ru/afisha).

Источник: страницы разделов (/koncerty/, /spektakli/, /lekcii/ …). Это сайт на Next.js: события уже лежат в HTML
внутри `<script id="__NEXT_DATA__">` (серверная выдача, поле `dehydratedState`), отдельного API мы не трогаем.
Из HTML берём только этот JSON, вёрстку не разбираем.

Что отдаёт страница (проверено 2026-10-24): первые 12 ближайших событий раздела (остальные подгружаются внутренним
запросом при прокрутке; `?page=N` закрыт robots.txt: `Disallow: *?*`, поэтому глубже не ходим) и блоки главной.
Поэтому коллектор даёт «ближайшие дни» по каждому разделу, а не весь горизонт; полный объём — вопрос к Мосбилету
(официальный API или выгрузка), см. README. Карточка: название, дата начала и конца, площадка с координатами,
цена «от», возрастное ограничение, сфера, организатор, флаги «бесплатно» и «Пушкинская карта».

robots.txt (проверено 2026-10-24): закрыты `*?*`, `*/*?utm_source=*` и `/max*`; наши страницы без параметров
разрешены. Файл читается при каждом запуске, закрытая страница пропускается. Условий использования на сайте не
нашли (ссылок в подвале страницы нет): юридический риск не оценён, решение владельца (README, раздел «Что решает владелец»).
Ссылка на карточку события (`https://bilet.mos.ru/event/<id>`) обязательна: события без id пропускаем. Карточки без дат
(постоянные экспозиции музеев на главной: `dateFrom` пустой) тоже пропускаем и считаем в `stats.skipped`: даты выдумывать нельзя.
"""
from __future__ import annotations

import logging
import time as _time
from collections.abc import Callable, Iterator
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import httpx

from leisure.normalize.schema import RawEvent

from ._common import (
    MSK,
    PageStats,
    RobotsGuard,
    fetch_pages,
    format_span,
    next_data,
    overlaps,
    parse_iso,
)
from ._common import clean_text as _clean
from .base import Collector, CollectorError, register

log = logging.getLogger(__name__)

BASE = "https://bilet.mos.ru"
# Главная + разделы, у которых в __NEXT_DATA__ есть список событий (проверено 2026-10-24).
PAGES = (
    "", "koncerty", "spektakli", "premieres", "lekcii", "master-klassy", "ekskursii", "dlya-detey", "museums",
    "rechnye-progulki", "zoopark", "sport",
)
USER_AGENT = "LeisurePlannerBot/0.1 (event planner for Moscow; polite, rate-limited, public pages only)"
PAUSE_SEC = 1.5
TIMEOUT_SEC = 20.0
RETRIES = 2
MAX_TEXT_CHARS = 3000
CITY_NAMES = ("Москва",)  # Мосбилет — только Москва


def _iter_events(node: Any) -> Iterator[dict]:
    """Все словари вида события (есть id, title, dateFrom) в любом месте дерева dehydratedState."""
    if isinstance(node, dict):
        if {"id", "title", "dateFrom"} <= node.keys():
            yield node
        else:
            for v in node.values():
                yield from _iter_events(v)
    elif isinstance(node, list):
        for v in node:
            yield from _iter_events(v)


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def format_price(item: dict) -> str:
    """'бесплатно' · 'от 600 ₽' · 'от 600 до 3000 ₽'; цены нет — пустая строка (не гадаем)."""
    low, high = _num(item.get("priceFrom")), _num(item.get("priceTo"))
    if item.get("isFree") or low == 0:
        return "бесплатно"
    if low is None:
        return ""
    if high and high > low:
        return f"от {low:g} до {high:g} ₽"
    return f"от {low:g} ₽"


@register
class MosbiletCollector(Collector):
    name = "mosbilet"
    cities = CITY_NAMES

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        pages: tuple[str, ...] = PAGES,
        respect_robots: bool = True,
        pause_sec: float = PAUSE_SEC,
        retries: int = RETRIES,
        timeout: float = TIMEOUT_SEC,
        sleep: Callable[[float], None] = _time.sleep,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self.pages = pages
        self.respect_robots = respect_robots
        self.pause_sec, self.retries, self.timeout = pause_sec, max(0, retries), timeout
        self._sleep = sleep
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.stats = PageStats()

    def collect(self, city: str, date_from: date, date_to: date) -> list[RawEvent]:
        if city not in CITY_NAMES:
            raise CollectorError(f"Мосбилет: город «{city}» не поддерживается (только Москва)")
        if date_from > date_to:
            raise ValueError("date_from позже date_to")
        window_start = datetime.combine(date_from, time.min, tzinfo=MSK)
        window_end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=MSK)
        self.stats = PageStats()
        own_client = self._client is None
        client = self._client or httpx.Client(timeout=httpx.Timeout(self.timeout), follow_redirects=True)
        try:
            guard = RobotsGuard(client, USER_AGENT, "Мосбилет") if self.respect_robots else None
            urls = [f"{BASE}/{p}/" if p else f"{BASE}/" for p in self.pages]
            pages = fetch_pages(
                client, urls, guard=guard, headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
                retries=self.retries, sleep=self._sleep, pause_sec=self.pause_sec, source="Мосбилет",
                http_error=self._http_error, stats=self.stats,
            )
        finally:
            if own_client:
                client.close()
        return self._parse_pages(pages, window_start, window_end)

    @staticmethod
    def _http_error(resp: httpx.Response) -> str:
        if resp.status_code in (401, 403):
            return f"Мосбилет ответил {resp.status_code}: доступ закрыт для этого адреса. Защиту не обходим."
        return f"Мосбилет ответил HTTP {resp.status_code}."

    def _parse_pages(self, pages: list[tuple[str, str]], window_start: datetime, window_end: datetime) -> list[RawEvent]:
        collected_at = self._clock().isoformat(timespec="seconds")
        out: list[RawEvent] = []
        seen: set[Any] = set()
        for url, html_text in pages:
            data = next_data(html_text)
            if data is None:
                log.warning("Мосбилет: на %s нет __NEXT_DATA__ (вёрстка изменилась?)", url)
                self.stats.failed_pages += 1
                continue
            for item in _iter_events((data.get("props") or {}).get("pageProps") or {}):
                self.stats.fetched += 1
                if item["id"] in seen:
                    self.stats.duplicates += 1
                    continue
                seen.add(item["id"])
                try:
                    raw = self._to_raw(item, window_start, window_end, collected_at)
                except (KeyError, TypeError, ValueError, AttributeError) as exc:
                    log.warning("Мосбилет: карточка id=%s пропущена: %s", item.get("id"), exc)
                    self.stats.skipped += 1
                    continue
                if raw is not None:
                    out.append(raw)
                    self.stats.kept += 1
        if not out and self.stats.failed_pages == len(pages):
            raise CollectorError("Мосбилет: на страницах нет данных событий (__NEXT_DATA__ не найден): вёрстка изменилась.")
        return out

    def _to_raw(self, item: dict, window_start: datetime, window_end: datetime, collected_at: str) -> RawEvent | None:
        title = _clean(item.get("title"))
        start = parse_iso(item.get("dateFrom"))
        event_id = item.get("id")
        if not title or start is None or not isinstance(event_id, (int, str)) or isinstance(event_id, bool):
            self.stats.skipped += 1  # без названия, даты начала или номера (а значит и ссылки на первоисточник) карточка бесполезна
            return None
        end = parse_iso(item.get("dateTo"))
        if not overlaps(start, end, window_start, window_end):
            self.stats.outside_window += 1
            return None
        with_time = not (start.time() == time.min and (end is None or end.time() == time.min))
        lat, lon = _num(item.get("venueLat")), _num(item.get("venueLon"))
        if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            lat = lon = None
        sphere = _clean(item.get("sphere"))
        org = _clean(item.get("foundationTitle"))
        venue = _clean(item.get("venueTitle"))
        notes = [
            _clean(item.get("description")),
            f"Раздел афиши: {sphere}" if sphere else "",
            f"Организатор: {org}" if org and org != venue else "",
            "Принимается Пушкинская карта." if item.get("isPushkinCard") else "",
            "Для детей." if item.get("isForKids") else "",
            "Вход по регистрации через MosID." if item.get("isRegistrationWithMosId") else "",
        ]
        text = "\n".join(n for n in notes if n)
        if len(text) > MAX_TEXT_CHARS:
            text = text[:MAX_TEXT_CHARS].rsplit(" ", 1)[0] + "…"
        return RawEvent(
            source=self.name,
            url=f"{BASE}/event/{event_id}",
            title=title,
            date_text=format_span(start, end, with_time=with_time),
            text=text,
            venue=venue,
            price_text=format_price(item),
            collected_at=collected_at,
            lat=round(lat, 5) if lat is not None else None,
            lon=round(lon, 5) if lon is not None else None,
            age_restriction=_clean(item.get("restrictionAge")),
            categories=[sphere] if sphere else [],
        )


__all__ = ["MosbiletCollector", "format_price"]
