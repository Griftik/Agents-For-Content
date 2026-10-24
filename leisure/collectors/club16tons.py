"""Коллектор клуба «16 Тонн» (16tons.ru): афиша концертов из разметки schema.org на главной странице.

Клуб на Пресненском Валу, живая музыка. Одна страница отдаёт весь анонс на полгода вперёд (проверено 2026-10-24:
118 блоков `application/ld+json` типа MusicEvent), у каждого есть название, дата, описание, цена и ссылка на
страницу концерта в `offers[].url`. Отдельного API и RSS нет. Берём только JSON-LD, вёрстку не разбираем.

Особенности:
- время начала в разметке всегда `T00:00:00` (клуб его туда не кладёт), поэтому в `date_text` только дата, а время
  нормализатор не придумывает: confidence «нужно проверить», если оно не названо в описании;
- цена — по минимальному предложению; отдельно «Входной билет» и прочие позиции не различаем.

robots.txt (проверено 2026-10-24): корень разрешён. Условий использования нет, есть строка в подвале «При цитировании
ссылка на сайт обязательна»: ссылка на страницу концерта у нас всегда. Файл robots.txt читается при каждом запуске.
"""
from __future__ import annotations

import logging
import time as _time
from collections.abc import Callable
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
    iter_jsonld,
    overlaps,
    parse_iso,
)
from ._common import clean_text as _clean
from .base import Collector, CollectorError, register

log = logging.getLogger(__name__)

PAGE_URL = "https://www.16tons.ru/"
USER_AGENT = "LeisurePlannerBot/0.1 (event planner for Moscow; polite, rate-limited, public pages only)"
TIMEOUT_SEC = 25.0
RETRIES = 2
MAX_TEXT_CHARS = 3000
CITY_NAMES = ("Москва",)


def _offers(item: dict) -> list[dict]:
    offers = item.get("offers")
    return [o for o in (offers if isinstance(offers, list) else [offers]) if isinstance(o, dict)]


def _price(offers: list[dict]) -> float | None:
    prices = []
    for o in offers:
        try:
            prices.append(float(o["price"]))
        except (KeyError, TypeError, ValueError):
            continue
    return min(prices) if prices else None


@register
class Club16TonsCollector(Collector):
    name = "club16tons"
    cities = CITY_NAMES

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        respect_robots: bool = True,
        retries: int = RETRIES,
        timeout: float = TIMEOUT_SEC,
        sleep: Callable[[float], None] = _time.sleep,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self.respect_robots = respect_robots
        self.retries, self.timeout = max(0, retries), timeout
        self._sleep = sleep
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.stats = PageStats()

    def collect(self, city: str, date_from: date, date_to: date) -> list[RawEvent]:
        if city not in CITY_NAMES:
            raise CollectorError(f"16 Тонн: город «{city}» не поддерживается (клуб в Москве)")
        if date_from > date_to:
            raise ValueError("date_from позже date_to")
        window_start = datetime.combine(date_from, time.min, tzinfo=MSK)
        window_end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=MSK)
        self.stats = PageStats()
        own_client = self._client is None
        client = self._client or httpx.Client(timeout=httpx.Timeout(self.timeout), follow_redirects=True)
        try:
            guard = RobotsGuard(client, USER_AGENT, "16 Тонн") if self.respect_robots else None
            pages = fetch_pages(
                client, [PAGE_URL], guard=guard, headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
                retries=self.retries, sleep=self._sleep, pause_sec=0.0, source="16 Тонн",
                http_error=self._http_error, stats=self.stats,
            )
        finally:
            if own_client:
                client.close()
        return self._parse_page(pages[0][1], window_start, window_end)

    @staticmethod
    def _http_error(resp: httpx.Response) -> str:
        if resp.status_code in (401, 403, 429):
            return f"16 Тонн ответил {resp.status_code}: доступ ограничен. Защиту не обходим."
        return f"16 Тонн ответил HTTP {resp.status_code}."

    def _parse_page(self, html_text: str, window_start: datetime, window_end: datetime) -> list[RawEvent]:
        collected_at = self._clock().isoformat(timespec="seconds")
        out: list[RawEvent] = []
        seen: set[str] = set()
        found = 0
        for item in iter_jsonld(html_text):
            if not str(item.get("@type", "")).endswith("Event"):
                continue
            found += 1
            self.stats.fetched += 1
            try:
                raw = self._to_raw(item, window_start, window_end, collected_at)
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                log.warning("16 Тонн: карточка «%s» пропущена: %s", item.get("name"), exc)
                self.stats.skipped += 1
                continue
            if raw is None:
                continue
            if raw.url in seen:
                self.stats.duplicates += 1
                continue
            seen.add(raw.url)
            out.append(raw)
            self.stats.kept += 1
        if not found:
            raise CollectorError("16 Тонн: на странице нет разметки событий (JSON-LD): разметка изменилась.")
        return out

    def _to_raw(self, item: dict, window_start: datetime, window_end: datetime, collected_at: str) -> RawEvent | None:
        title = _clean(item.get("name"))
        start = parse_iso(item.get("startDate"))
        offers = _offers(item)
        url = next((o["url"] for o in offers if isinstance(o.get("url"), str) and o["url"].startswith(("http://", "https://"))), "")
        if not title or start is None or not url:
            self.stats.skipped += 1  # без названия, даты или страницы концерта карточка бесполезна
            return None
        end = parse_iso(item.get("endDate"))
        if not overlaps(start, end, window_start, window_end):
            self.stats.outside_window += 1
            return None
        loc: Any = item.get("location") if isinstance(item.get("location"), dict) else {}
        addr = loc.get("address") if isinstance(loc.get("address"), dict) else {}
        text = _clean(item.get("description"))
        if len(text) > MAX_TEXT_CHARS:
            text = text[:MAX_TEXT_CHARS].rsplit(" ", 1)[0] + "…"
        price = _price(offers)
        return RawEvent(
            source=self.name,
            url=url,
            title=title,
            date_text=format_span(start, end, with_time=start.time() != time.min or bool(end and end.time() != time.min)),
            text=text,
            venue=_clean(loc.get("name")),
            price_text=f"от {price:g} ₽" if price is not None else "",
            collected_at=collected_at,
            address=", ".join(p for p in (_clean(addr.get("addressLocality")), _clean(addr.get("streetAddress"))) if p),
            categories=["Концерты"],
        )


__all__ = ["Club16TonsCollector"]
