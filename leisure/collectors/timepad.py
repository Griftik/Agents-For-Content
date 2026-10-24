"""Коллектор Timepad: REST API v1, GET https://api.timepad.ru/v1/events (п. 7.1 спеки).

Документация: https://dev.timepad.ru/api/get-v1-events/. В документации сказано, что публичные события отдаются
без аутентификации, но на практике (проверено 2026-10-24) запрос без токена получает 403
{"response_status": {"error_code": 403, "message": "Запрос требует указание токена"}}. Поэтому токен обязателен:
переменная окружения TIMEPAD_TOKEN (получить: https://dev.timepad.ru/api/oauth/, достаточно права view_events),
передаётся заголовком `Authorization: Bearer <токен>`. Без токена коллектор сразу отдаёт CollectorError «нужен токен»,
сеть не трогает. Токен никогда не попадает в логи и сообщения.

Что берём: события города, у которых дата начала попадает в диапазон (фильтры starts_at_min / starts_at_max
работают по дате начала, поэтому длинные события, начавшиеся до диапазона, API не вернёт), и на нашей стороне
повторно проверяем пересечение с диапазоном и город. Площадки как отдельного поля у Timepad нет, только
`location.address`: `RawEvent.venue` остаётся пустым, адрес едет в `address` (название места нормализатор достанет из него).
Организатор уходит в текст. robots.txt не читаем: это официальный API с токеном, а не обход сайта.
Ссылка на карточку первоисточника (`url`) в RawEvent обязательна; события без неё пропускаем.
"""
from __future__ import annotations

import logging
import os
import time as _time
from collections.abc import Callable
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import httpx

from leisure import settings  # noqa: F401  — при импорте подгружает .env, откуда берётся TIMEPAD_TOKEN
from leisure.normalize.schema import RawEvent

from ._common import MSK, CollectStats, get_with_retries
from ._common import clean_text as _clean
from ._common import join_text as _join_text
from .base import Collector, CollectorError, register

log = logging.getLogger(__name__)

API_URL = "https://api.timepad.ru/v1/events"
TOKEN_ENV = "TIMEPAD_TOKEN"
TOKEN_HELP = "https://dev.timepad.ru/api/oauth/"
USER_AGENT = "LeisurePlannerBot/0.1 (event planner for Moscow; polite, rate-limited, via official API)"

CITY_NAMES = {"Москва": "Москва"}  # значение параметра cities

PAGE_SIZE = 100          # максимум по документации (1 ≤ limit ≤ 100)
MAX_PAGES = 10           # потолок 1000 карточек за запуск
PAUSE_SEC = 1.5          # в документации «количество запросов в минуту ограничено»: ходим не чаще одного в 1.5 с
TIMEOUT_SEC = 20.0
RETRIES = 2
MAX_TEXT_CHARS = 4000

_PLACEHOLDER_TOKENS = {"", "REPLACE_ME"}


def _parse_dt(value: Any) -> datetime | None:
    """ISO-дата из ответа ('…+0300', '…+03:00', 'Z' или без пояса); без пояса считаем московским."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=MSK)).astimezone(MSK)


def _fmt_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


def format_dates(start: datetime, end: datetime | None) -> str:
    """'2026-10-24 19:00–21:00' · ночью '… — …' · от суток и дольше 'период с … по …'."""
    if end is None or end <= start:
        return _fmt_dt(start)
    if end.date() == start.date():
        return f"{_fmt_dt(start)}–{end.strftime('%H:%M')}"
    if end - start < timedelta(hours=24):
        return f"{_fmt_dt(start)} — {_fmt_dt(end)}"
    return f"период с {_fmt_dt(start)} по {_fmt_dt(end)}"


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 else None


def _rub(x: float) -> str:
    return f"{int(x)} ₽" if float(x).is_integer() else f"{x:.2f} ₽"


def format_price(item: dict) -> str:
    """Минимум из билетов; нет билетов — сводка registration_data; нет и её — пусто (не бесплатно по умолчанию)."""
    prices = [p for t in item.get("ticket_types") or [] if isinstance(t, dict) and t.get("is_active", True) is not False
              for p in [_num(t.get("price"))] if p is not None]
    if not prices:
        reg = item.get("registration_data") if isinstance(item.get("registration_data"), dict) else {}
        lo, hi = _num(reg.get("price_min")), _num(reg.get("price_max"))
        prices = [p for p in (lo, hi) if p is not None]
    if not prices:
        return ""
    lo, hi = min(prices), max(prices)
    if hi == 0:
        return "бесплатно"
    if lo == hi:
        return _rub(lo)
    return f"от {_rub(lo)}" + (f", платные до {_rub(hi)}" if lo == 0 else f" (до {_rub(hi)})")


@register
class TimepadCollector(Collector):
    name = "timepad"
    cities = ("Москва",)

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        token: str | None = None,
        page_size: int = PAGE_SIZE,
        max_pages: int = MAX_PAGES,
        pause_sec: float = PAUSE_SEC,
        retries: int = RETRIES,
        timeout: float = TIMEOUT_SEC,
        sleep: Callable[[float], None] = _time.sleep,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        raw_token = os.getenv(TOKEN_ENV, "") if token is None else token
        self._token = "" if raw_token.strip() in _PLACEHOLDER_TOKENS else raw_token.strip()
        self.page_size = max(1, min(page_size, PAGE_SIZE))
        self.max_pages = max(1, max_pages)
        self.pause_sec = pause_sec
        self.retries = max(0, retries)
        self.timeout = timeout
        self._sleep = sleep
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.stats = CollectStats()

    # ─── публичный интерфейс ───

    def collect(self, city: str, date_from: date, date_to: date) -> list[RawEvent]:
        city_name = CITY_NAMES.get(city)
        if city_name is None:
            raise CollectorError(f"Timepad-коллектор: город «{city}» не настроен (есть: {', '.join(CITY_NAMES)})")
        if date_from > date_to:
            raise ValueError("date_from позже date_to")
        if not self._token:
            raise CollectorError(
                f"Timepad: нужен токен API. Задайте переменную окружения {TOKEN_ENV} (получить: {TOKEN_HELP}, "
                "достаточно права view_events). Без токена API отвечает 403."
            )
        window_start = datetime.combine(date_from, time.min, tzinfo=MSK)
        window_end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=MSK)
        params = {
            "cities": city_name, "limit": self.page_size, "sort": "+starts_at",
            "starts_at_min": window_start.isoformat(timespec="seconds"),
            "starts_at_max": (window_end - timedelta(seconds=1)).isoformat(timespec="seconds"),
        }
        self.stats = CollectStats()
        own_client = self._client is None
        client = self._client or httpx.Client(timeout=httpx.Timeout(self.timeout), follow_redirects=True)
        try:
            return self._collect_pages(client, params, city_name, window_start, window_end)
        finally:
            if own_client:
                client.close()

    # ─── сеть ───

    def _headers(self) -> dict[str, str]:
        return {"User-Agent": USER_AGENT, "Accept": "application/json", "Authorization": f"Bearer {self._token}"}

    @staticmethod
    def _http_error(resp: httpx.Response) -> str:
        message = ""
        try:
            body = resp.json()
            message = str((body.get("response_status") or {}).get("message") or "")
        except (ValueError, AttributeError):
            pass
        if resp.status_code in (401, 403):
            return (
                f"Timepad ответил {resp.status_code}" + (f" «{message}»" if message else "") + f": токен недействителен, "
                f"отозван или без права view_events (выпустить новый: {TOKEN_HELP}). Защиту не обходим."
            )
        if resp.status_code == 400:
            return "Timepad ответил 400" + (f" «{message}»" if message else "") + ": параметры запроса не приняты."
        return f"Timepad ответил HTTP {resp.status_code}" + (f" «{message}»" if message else "") + "."

    def _get(self, client: httpx.Client, params: dict) -> httpx.Response:
        return get_with_retries(
            client, API_URL, params=params, headers=self._headers(), retries=self.retries, sleep=self._sleep,
            source="Timepad", http_error=self._http_error,
        )

    # ─── постраничный сбор ───

    def _collect_pages(self, client, params, city_name, window_start, window_end) -> list[RawEvent]:
        out: list[RawEvent] = []
        seen: set[Any] = set()
        collected_at = self._clock().isoformat(timespec="seconds")
        skip = 0
        for page in range(1, self.max_pages + 1):
            resp = self._get(client, {**params, "skip": skip})
            try:
                data = resp.json()
            except ValueError as exc:
                raise CollectorError(f"Timepad вернул не JSON (страница {page}).") from exc
            values = data.get("values") if isinstance(data, dict) else None
            if not isinstance(values, list):
                raise CollectorError(f"Timepad: неожиданный формат ответа (страница {page}): нет списка values.")
            self.stats.pages = page
            total = data.get("total")
            if isinstance(total, int):
                self.stats.total_in_api = total
            for item in values:
                self.stats.fetched += 1
                if not isinstance(item, dict):
                    self.stats.skipped += 1
                    continue
                if item.get("id") in seen:
                    self.stats.duplicates += 1
                    continue
                seen.add(item.get("id"))
                try:
                    raw = self._to_raw(item, city_name, window_start, window_end, collected_at)
                except (KeyError, TypeError, ValueError, AttributeError) as exc:
                    log.warning("Timepad: карточка id=%s пропущена: %s", item.get("id"), exc)
                    self.stats.skipped += 1
                    continue
                if raw is not None:
                    out.append(raw)
                    self.stats.kept += 1
            skip += len(values)
            if not values or not isinstance(total, int) or skip >= total:
                break
            if page == self.max_pages:
                self.stats.truncated = True
                log.warning("Timepad: достигнут лимит страниц (%d), в API есть ещё события", self.max_pages)
                break
            self._sleep(self.pause_sec)
        return out

    # ─── разбор карточки ───

    def _to_raw(self, item: dict, city_name: str, window_start: datetime, window_end: datetime,
                collected_at: str) -> RawEvent | None:
        title = _clean(item.get("name"))
        url = item.get("url")
        start = _parse_dt(item.get("starts_at"))
        if not title or start is None or not isinstance(url, str) or not url.startswith(("http://", "https://")):
            self.stats.skipped += 1  # без названия, даты начала или ссылки на первоисточник карточка бесполезна
            return None
        end = _parse_dt(item.get("ends_at"))
        loc = item.get("location") if isinstance(item.get("location"), dict) else {}
        loc_city = _clean(loc.get("city"))
        if loc_city and loc_city.casefold() != city_name.casefold():
            self.stats.skipped += 1  # онлайн-события и чужие города, просочившиеся мимо фильтра cities
            return None
        if not (start < window_end and (end or start) >= window_start):
            self.stats.outside_window += 1
            return None
        lat, lon = self._coords(loc)
        return RawEvent(
            source=self.name,
            url=url,
            title=title,
            date_text=format_dates(start, end),
            text=self._text(item),
            venue="",  # у Timepad нет отдельного названия площадки, только адресная строка
            price_text=format_price(item),
            collected_at=collected_at,
            address=_clean(loc.get("address")),
            lat=lat,
            lon=lon,
            age_restriction=self._age(item),
            categories=[n for c in item.get("categories") or [] if isinstance(c, dict) for n in [_clean(c.get("name"))] if n],
        )

    @staticmethod
    def _coords(loc: dict) -> tuple[float | None, float | None]:
        """coordinates = [широта, долгота]; вне диапазона или не числа — обе None (не угадываем)."""
        c = loc.get("coordinates")
        if not (isinstance(c, (list, tuple)) and len(c) == 2):
            return None, None
        lat, lon = c
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (lat, lon)):
            return None, None
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None, None
        return round(float(lat), 5), round(float(lon), 5)

    @staticmethod
    def _age(item: dict) -> str:
        """В документации age_limit лежит рядом с meta; смотрим и на верхнем уровне, и внутри meta."""
        meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
        age = item.get("age_limit", meta.get("age_limit"))
        return _clean(str(age)) if age not in (None, "") else ""

    @staticmethod
    def _text(item: dict) -> str:
        body = _join_text(_clean(item.get("description_short")), _clean(item.get("description_html")))
        if len(body) > MAX_TEXT_CHARS:
            body = body[:MAX_TEXT_CHARS].rsplit(" ", 1)[0] + "…"
        org = item.get("organization") if isinstance(item.get("organization"), dict) else {}
        org_name = _clean(org.get("name"))
        return "\n".join(p for p in (body, f"Организатор: {org_name}" if org_name else "") if p)


__all__ = ["TimepadCollector", "format_dates", "format_price"]
