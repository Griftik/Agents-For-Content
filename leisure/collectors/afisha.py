"""Коллектор Афиши (afisha.ru): разметка schema.org (JSON-LD) на страницах разделов Москвы.

Публичного API у Афиши нет. Зато каждая страница раздела (/msk/concerts/, /msk/theatre/ …) для поисковиков несёт блок
`application/ld+json` с типизированными событиями (MusicEvent, TheaterEvent, ExhibitionEvent, ComedyEvent, SportsEvent,
Event): название, ссылка на карточку, даты начала и конца, площадка с адресом, цена «от». Берём только этот JSON, вёрстку
не разбираем. Проверено 2026-10-24: на раздел приходится от 3 до 117 событий (концерты 111, театр 117, выставки 96).

Ограничения разметки, о которых нужно помнить:
- у спектаклей и выставок `startDate` — ближайшая дата, `endDate` — конец проката; расписание по дням в разметке нет,
  поэтому `date_text` это «период с … по …», а конкретные даты показа нормализатор не выдумывает (confidence «нужно проверить»);
- у части событий площадка «Неизвестно» (так в источнике) — оставляем пустой;
- постоянные экспозиции без `endDate` и со стартом в прошлом в окно не попадают (бессрочность нам неизвестна).

robots.txt (проверено 2026-10-24): разделы `/msk/…/` разрешены (закрыты служебные пути квестов, фильтров, бронирования);
файл читается при каждом запуске. Условия использования (https://www.afisha.ru/article/usloviya-ispolzovaniya/, п. 3.3):
«Сервис предназначен для личного некоммерческого использования»; про автоматический сбор там ничего нет. Сбор идёт по
решению владельца от 24.10.2026 (агрегаторы на MVP бесплатно, спрос проверяем), риск осознанный: README, раздел
«Что решает владелец». Ссылка на карточку первоисточника (`url` без параметров) обязательна.
"""
from __future__ import annotations

import logging
import time as _time
from collections.abc import Callable, Iterator
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

import httpx

from leisure.normalize.schema import RawEvent

from ._common import (
    MSK,
    PageStats,
    RobotsGuard,
    fetch_pages,
    format_span,
    iter_jsonld,
    overlaps,
    parse_iso,
)
from ._common import clean_text as _clean
from .base import Collector, CollectorError, register

log = logging.getLogger(__name__)

BASE = "https://www.afisha.ru/msk"
# Раздел → подсказка категории для нормализатора. /schedule_theatre/ повторяет /theatre/, поэтому не берём.
PAGES: dict[str, str] = {
    "concerts": "Концерты", "theatre": "Театр", "exhibitions": "Выставки", "party": "Вечеринки",
    "standup": "Стендап", "kids": "Детям", "excursions": "Экскурсии", "events": "",
}
TYPE_LABELS = {
    "MusicEvent": "музыка", "TheaterEvent": "театр", "ExhibitionEvent": "выставка", "ComedyEvent": "стендап/комедия",
    "SportsEvent": "спорт", "Event": "",
}
USER_AGENT = "LeisurePlannerBot/0.1 (event planner for Moscow; polite, rate-limited, public pages only)"
PAUSE_SEC = 2.0
TIMEOUT_SEC = 25.0
RETRIES = 2
MAX_TEXT_CHARS = 3000
CITY_NAMES = ("Москва",)
UNKNOWN = "Неизвестно"  # так Афиша пишет площадку и адрес, когда их нет


def _iter_events(page: str) -> Iterator[dict]:
    """События schema.org в любом месте разметки страницы (внутри ItemList, @graph и т. п.)."""
    def walk(node: Any) -> Iterator[dict]:
        if isinstance(node, dict):
            if str(node.get("@type", "")).endswith("Event"):
                yield node
            else:
                for v in node.values():
                    yield from walk(v)
        elif isinstance(node, list):
            for v in node:
                yield from walk(v)

    for block in iter_jsonld(page):
        yield from walk(block)


def _known(value: Any) -> str:
    text = _clean(value)
    return "" if text.casefold() == UNKNOWN.casefold() else text


def _min_price(offers: Any) -> float | None:
    items = offers if isinstance(offers, list) else [offers]
    prices = []
    for o in items:
        raw = o.get("price", o.get("lowPrice")) if isinstance(o, dict) else None
        if isinstance(raw, bool) or raw in (None, ""):
            continue
        try:
            prices.append(float(raw))
        except (TypeError, ValueError):
            continue
    return min(prices) if prices else None


def canonical_url(url: Any) -> str:
    """Адрес карточки без параметров (`?priorityCity=msk`, `?tab=schedule`); не http(s) — пустая строка."""
    if not isinstance(url, str):
        return ""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return ""
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


@register
class AfishaCollector(Collector):
    name = "afisha"
    cities = CITY_NAMES

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        pages: dict[str, str] | None = None,
        respect_robots: bool = True,
        pause_sec: float = PAUSE_SEC,
        retries: int = RETRIES,
        timeout: float = TIMEOUT_SEC,
        sleep: Callable[[float], None] = _time.sleep,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self.pages = PAGES if pages is None else pages
        self.respect_robots = respect_robots
        self.pause_sec, self.retries, self.timeout = pause_sec, max(0, retries), timeout
        self._sleep = sleep
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.stats = PageStats()

    def collect(self, city: str, date_from: date, date_to: date) -> list[RawEvent]:
        if city not in CITY_NAMES:
            raise CollectorError(f"Афиша: город «{city}» не поддерживается (только Москва)")
        if date_from > date_to:
            raise ValueError("date_from позже date_to")
        window_start = datetime.combine(date_from, time.min, tzinfo=MSK)
        window_end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=MSK)
        self.stats = PageStats()
        own_client = self._client is None
        client = self._client or httpx.Client(timeout=httpx.Timeout(self.timeout), follow_redirects=True)
        try:
            guard = RobotsGuard(client, USER_AGENT, "Афиша") if self.respect_robots else None
            pages = fetch_pages(
                client, [f"{BASE}/{p}/" for p in self.pages], guard=guard,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html"}, retries=self.retries, sleep=self._sleep,
                pause_sec=self.pause_sec, source="Афиша", http_error=self._http_error, stats=self.stats,
            )
        finally:
            if own_client:
                client.close()
        return self._parse_pages(pages, window_start, window_end)

    @staticmethod
    def _http_error(resp: httpx.Response) -> str:
        if resp.status_code in (401, 403, 429):
            return f"Афиша ответила {resp.status_code}: доступ ограничен для этого адреса или частоты. Защиту не обходим."
        return f"Афиша ответила HTTP {resp.status_code}."

    def _parse_pages(self, pages: list[tuple[str, str]], window_start: datetime, window_end: datetime) -> list[RawEvent]:
        collected_at = self._clock().isoformat(timespec="seconds")
        out: list[RawEvent] = []
        seen: set[str] = set()
        for page_url, html_text in pages:
            hint = self.pages.get(page_url.rstrip("/").rsplit("/", 1)[-1], "")
            found = 0
            for item in _iter_events(html_text):
                found += 1
                self.stats.fetched += 1
                url = canonical_url(item.get("url"))
                if url in seen:
                    self.stats.duplicates += 1
                    continue
                try:
                    raw = self._to_raw(item, url, hint, window_start, window_end, collected_at)
                except (KeyError, TypeError, ValueError, AttributeError) as exc:
                    log.warning("Афиша: карточка %s пропущена: %s", url or item.get("name"), exc)
                    self.stats.skipped += 1
                    continue
                if url:
                    seen.add(url)
                if raw is not None:
                    out.append(raw)
                    self.stats.kept += 1
            if not found:
                log.warning("Афиша: на %s нет событий schema.org (разметка изменилась?)", page_url)
                self.stats.failed_pages += 1
        if not out and self.stats.failed_pages == len(pages):
            raise CollectorError("Афиша: на страницах нет разметки событий (JSON-LD): разметка изменилась.")
        return out

    def _to_raw(
        self, item: dict, url: str, hint: str, window_start: datetime, window_end: datetime, collected_at: str,
    ) -> RawEvent | None:
        title = _clean(item.get("name"))
        start = parse_iso(item.get("startDate"))
        if not title or start is None or not url:
            self.stats.skipped += 1  # без названия, даты начала или ссылки на карточку она бесполезна
            return None
        end = parse_iso(item.get("endDate"))
        if not overlaps(start, end, window_start, window_end):
            self.stats.outside_window += 1
            return None
        # 00:00 в обоих концах — Афиша не знает времени (выставки), показываем только даты
        with_time = not (start.time() == time.min and (end is None or end.time() == time.min))
        loc = item.get("location") if isinstance(item.get("location"), dict) else {}
        addr = loc.get("address") if isinstance(loc.get("address"), dict) else {}
        price = _min_price(item.get("offers"))
        type_label = TYPE_LABELS.get(str(item.get("@type")), "")
        cats = [c for c in dict.fromkeys([hint, type_label]) if c]
        text = _clean(item.get("description"))
        if len(text) > MAX_TEXT_CHARS:
            text = text[:MAX_TEXT_CHARS].rsplit(" ", 1)[0] + "…"
        return RawEvent(
            source=self.name,
            url=url,
            title=title,
            date_text=format_span(start, end, with_time=with_time),
            text=text,
            venue=_known(loc.get("name")),
            price_text=f"от {price:g} ₽" if price is not None else "",
            collected_at=collected_at,
            address=_known(addr.get("streetAddress")),
            categories=cats,
        )


__all__ = ["AfishaCollector", "canonical_url"]
