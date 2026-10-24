"""Коллектор KudaGo: открытый JSON API, HTML не парсим (п. 7.1 спеки).

Документация: https://docs.kudago.com/api/ (GET /public-api/v1.4/events/). Ключ не нужен.

Что делает: постранично забирает события города за диапазон дат, оставляет только те, у которых есть показ
в диапазоне (проверка на нашей стороне: в доках семантика actual_since/actual_until описана двусмысленно),
и превращает каждое в RawEvent. Нормализация и дедупликация — дальше по конвейеру.

Условия лицензии KudaGo (docs.kudago.com, «Лицензионное соглашение»):
  * везде, где показываются данные, нужна прямая индексируемая ссылка на карточку первоисточника — её адрес
    кладём в RawEvent.url (поле site_url), дальше он попадает в EventIn.url и EventIn.sources;
  * данные нельзя передавать третьим лицам на коммерческой основе; «kudago» нельзя использовать в названии продукта.

robots.txt: для `User-agent: *` там `Disallow: /public-api`, хотя сам API опубликован для разработчиков.
Учёт robots.txt включается настройкой `settings.COLLECTORS_RESPECT_ROBOTS` (переменная окружения
COLLECTORS_RESPECT_ROBOTS, по умолчанию 0: решение владельца продукта от 24.10.2026, на MVP агрегаторы собираем
бесплатно, проверяя спрос). Явный аргумент конструктора `respect_robots` сильнее настройки. При включённом учёте
коллектор останавливается с понятной ошибкой, не сделав ни одного запроса к API. Технические блокировки (403) не обходим.
"""
from __future__ import annotations

import logging
import re
import time as _time
from collections.abc import Callable
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from urllib import robotparser

import httpx

from leisure import settings
from leisure.normalize.schema import RawEvent

from ._common import MSK, CollectStats, get_with_retries
from ._common import clean_text as _clean
from ._common import join_text as _join_text
from .base import Collector, CollectorError, register

log = logging.getLogger(__name__)


API_URL = "https://kudago.com/public-api/v1.4/events/"
ROBOTS_URL = "https://kudago.com/robots.txt"
# Только ASCII: заголовки HTTP. Имя бота — чтобы владельцы источника видели, кто ходит.
USER_AGENT = "LeisurePlannerBot/0.1 (event planner for Moscow; polite, rate-limited, via public API)"

CITY_SLUGS = {"Москва": "msk"}

# Поля из документации (список событий). place и dates раскрываем через expand, иначе придут только id и метки времени.
FIELDS = (
    "id,title,short_title,dates,place,description,body_text,categories,tagline,"
    "age_restriction,price,is_free,site_url,tags"
)
EXPAND = "place,dates"

PAGE_SIZE = 100          # максимум по документации
MAX_PAGES = 10           # потолок 1000 карточек за запуск: на неделю по Москве хватает, дальше — повод разобраться
PAUSE_SEC = 1.0          # вежливая пауза между страницами
TIMEOUT_SEC = 20.0
RETRIES = 2              # повторы только для сетевых сбоев и 429/5xx; 4xx (в т. ч. 403) не повторяем

MAX_TEXT_CHARS = 4000    # описание длиннее обрезаем: LLM-нормализатору хватает, токены экономим
MAX_DATES_IN_TEXT = 14   # сколько показов перечислять в date_text

ENDLESS_TS = 4102444800  # 2100-01-01 UTC: всё, что дальше, — «бессрочно» (запасная эвристика к флагу is_endless)


class _Occurrence:
    """Один элемент поля dates: показ или период. start/end = None означает «без начала / без конца»."""

    __slots__ = ("start", "end", "start_date", "start_time", "end_date", "end_time")

    def __init__(self, start, end, start_date, start_time, end_date, end_time):
        self.start: datetime | None = start
        self.end: datetime | None = end
        self.start_date: str = start_date
        self.start_time: str = start_time
        self.end_date: str = end_date
        self.end_time: str = end_time

    def intersects(self, window_start: datetime, window_end: datetime) -> bool:
        """Окно [window_start, window_end): показ пересекает его, если начался до конца окна и не кончился до начала."""
        return (self.start is None or self.start < window_end) and (self.end is None or self.end >= window_start)


def _ts_to_msk(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value), MSK)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _hhmm(value: Any) -> str:
    """'13:00:00' → '13:00'; всё остальное → ''."""
    m = re.match(r"^(\d{1,2}):(\d{2})", value) if isinstance(value, str) else None
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else ""


def _parse_occurrences(dates: Any) -> list[_Occurrence]:
    out: list[_Occurrence] = []
    for d in dates if isinstance(dates, list) else []:
        if not isinstance(d, dict):
            continue
        start_ts, end_ts = d.get("start"), d.get("end")
        startless = bool(d.get("is_startless")) or start_ts is None or _num(start_ts) <= 0
        endless = bool(d.get("is_endless")) or (end_ts is not None and _num(end_ts) >= ENDLESS_TS)
        if startless and end_ts is None and not endless:
            continue  # ни начала, ни конца — разобрать нечего
        start = None if startless else _ts_to_msk(start_ts)
        if endless:
            end = None
        elif end_ts is None:
            end = start  # одиночный показ
        else:
            end = _ts_to_msk(end_ts)
        if (not startless and start is None) or (not endless and end is None):
            continue  # метка времени не разобралась — пропускаем показ, а не выдумываем дату
        start_time = _hhmm(d["start_time"]) if "start_time" in d else _midnight_free(start)
        end_time = _hhmm(d["end_time"]) if "end_time" in d else _midnight_free(end)
        out.append(_Occurrence(
            start, end,
            d["start_date"] if isinstance(d.get("start_date"), str) else (start.date().isoformat() if start else ""),
            start_time,
            d["end_date"] if isinstance(d.get("end_date"), str) else (end.date().isoformat() if end else ""),
            end_time,
        ))
    return out


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _midnight_free(dt: datetime | None) -> str:
    """Время из метки: полночь считаем «времени нет» (у выставок и периодов так и приходит)."""
    return "" if dt is None or (dt.hour == 0 and dt.minute == 0) else dt.strftime("%H:%M")


def _fmt_occurrence(o: _Occurrence) -> str:
    if o.start is None and o.end is None:
        return "бессрочно"
    if o.start is None:
        return f"до {o.end_date}"
    if o.end is None:
        return f"с {o.start_date}, дата окончания не указана"
    t0 = f" {o.start_time}" if o.start_time else ""
    same_day = o.start_date == o.end_date or not o.end_date
    if same_day or o.end == o.start:
        t1 = f"–{o.end_time}" if o.end_time and o.end_time != o.start_time else ""
        return f"{o.start_date}{t0}{t1}"
    if o.end - o.start < timedelta(hours=24):  # ночная вечеринка: 23:00 → 06:00 следующего дня
        t1 = f" {o.end_time}" if o.end_time else ""
        return f"{o.start_date}{t0} — {o.end_date}{t1}"
    hours = f", часы {o.start_time}–{o.end_time}" if o.start_time and o.end_time else ""
    return f"период с {o.start_date} по {o.end_date}{hours}"


@register
class KudaGoCollector(Collector):
    name = "kudago"
    cities = ("Москва",)

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        respect_robots: bool | None = None,
        page_size: int = PAGE_SIZE,
        max_pages: int = MAX_PAGES,
        pause_sec: float = PAUSE_SEC,
        retries: int = RETRIES,
        timeout: float = TIMEOUT_SEC,
        sleep: Callable[[float], None] = _time.sleep,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self.respect_robots = settings.COLLECTORS_RESPECT_ROBOTS if respect_robots is None else respect_robots
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
        slug = CITY_SLUGS.get(city)
        if slug is None:
            raise CollectorError(f"KudaGo-коллектор: город «{city}» не настроен (есть: {', '.join(CITY_SLUGS)})")
        if date_from > date_to:
            raise ValueError("date_from позже date_to")
        window_start = datetime.combine(date_from, time.min, tzinfo=MSK)
        window_end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=MSK)
        params = {
            "location": slug, "lang": "ru", "text_format": "plain", "fields": FIELDS, "expand": EXPAND,
            "order_by": "id",  # стабильный порядок: страницы не «плывут», пока мы листаем
            "actual_since": int(window_start.timestamp()), "actual_until": int(window_end.timestamp()) - 1,
            "page_size": self.page_size,
        }
        self.stats = CollectStats()
        own_client = self._client is None
        client = self._client or httpx.Client(timeout=httpx.Timeout(self.timeout), follow_redirects=True)
        try:
            if self.respect_robots:
                self._check_robots(client)
            return self._collect_pages(client, params, window_start, window_end)
        finally:
            if own_client:
                client.close()

    # ─── сеть ───

    def _headers(self) -> dict[str, str]:
        return {"User-Agent": USER_AGENT, "Accept": "application/json"}

    def _get(self, client: httpx.Client, url: str, params: dict | None = None) -> httpx.Response:
        return get_with_retries(
            client, url, params=params, headers=self._headers(), retries=self.retries, sleep=self._sleep,
            source="KudaGo", http_error=self._http_error,
        )

    @staticmethod
    def _http_error(resp: httpx.Response) -> str:
        if resp.status_code in (401, 403):
            return (
                f"KudaGo ответил {resp.status_code}: доступ к API закрыт для этого адреса (похоже на блокировку по "
                "IP или региону на стороне источника). Защиту не обходим — проверьте сеть/прокси или запустите сбор "
                "с другого хоста."
            )
        if resp.status_code == 404:
            return "KudaGo ответил 404: адрес API изменился? Сверьтесь с https://docs.kudago.com/api/."
        return f"KudaGo ответил HTTP {resp.status_code}."

    def _check_robots(self, client: httpx.Client) -> None:
        """RFC 9309: 200 — разбираем; 401/403 — закрыто; прочие 4xx — ограничений нет; сбой/5xx — не рискуем."""
        resp = self._get_robots(client)
        if resp.status_code in (401, 403):
            raise CollectorError("KudaGo: robots.txt недоступен (401/403) — по правилам считаем доступ закрытым.")
        if resp.status_code >= 500:
            raise CollectorError(f"KudaGo: robots.txt не прочитан (HTTP {resp.status_code}), сбор отложен.")
        if resp.status_code != 200:
            return
        parser = robotparser.RobotFileParser()
        parser.parse(resp.text.splitlines())
        if not parser.can_fetch(USER_AGENT, API_URL):
            raise CollectorError(
                "KudaGo: robots.txt запрещает /public-api для нашего бота. Мы уважаем robots.txt, поэтому сбор "
                "остановлен. Отключить учёт можно только решением владельца: COLLECTORS_RESPECT_ROBOTS=0 "
                "или KudaGoCollector(respect_robots=False)."
            )

    def _get_robots(self, client: httpx.Client) -> httpx.Response:
        try:
            return client.get(ROBOTS_URL, headers=self._headers())
        except httpx.TransportError as exc:
            raise CollectorError(f"KudaGo: robots.txt недоступен ({type(exc).__name__}: {exc}).") from exc

    # ─── постраничный сбор ───

    def _collect_pages(self, client, params, window_start, window_end) -> list[RawEvent]:
        out: list[RawEvent] = []
        seen: set[Any] = set()
        collected_at = self._clock().isoformat(timespec="seconds")
        for page in range(1, self.max_pages + 1):
            resp = self._get(client, API_URL, {**params, "page": page})
            try:
                data = resp.json()
            except ValueError as exc:
                raise CollectorError("KudaGo вернул не JSON (страница %d)." % page) from exc
            results = data.get("results") if isinstance(data, dict) else None
            if not isinstance(results, list):
                raise CollectorError(f"KudaGo: неожиданный формат ответа (страница {page}): нет списка results.")
            self.stats.pages = page
            if isinstance(data.get("count"), int):
                self.stats.total_in_api = data["count"]
            for item in results:
                self.stats.fetched += 1
                if not isinstance(item, dict):
                    self.stats.skipped += 1
                    continue
                if item.get("id") in seen:
                    self.stats.duplicates += 1
                    continue
                seen.add(item.get("id"))
                try:
                    raw = self._to_raw(item, window_start, window_end, collected_at)
                except (KeyError, TypeError, ValueError, AttributeError) as exc:
                    log.warning("KudaGo: карточка id=%s пропущена: %s", item.get("id"), exc)
                    self.stats.skipped += 1
                    continue
                if raw is None:
                    continue
                out.append(raw)
                self.stats.kept += 1
            if not data.get("next"):
                break
            if page == self.max_pages:
                self.stats.truncated = True
                log.warning("KudaGo: достигнут лимит страниц (%d), в API есть ещё карточки", self.max_pages)
                break
            self._sleep(self.pause_sec)
        return out

    # ─── разбор карточки ───

    def _to_raw(self, item: dict, window_start: datetime, window_end: datetime, collected_at: str) -> RawEvent | None:
        title = _clean(item.get("title")) or _clean(item.get("short_title"))
        url = item.get("site_url")
        if not title or not isinstance(url, str) or not url.startswith(("http://", "https://")):
            self.stats.skipped += 1  # без названия или ссылки на первоисточник карточка бесполезна (и нарушает лицензию)
            return None
        inside = [o for o in _parse_occurrences(item.get("dates")) if o.intersects(window_start, window_end)]
        if not inside:
            self.stats.outside_window += 1
            return None
        inside.sort(key=lambda o: (o.start is not None, o.start or window_start))
        shown = [_fmt_occurrence(o) for o in inside[:MAX_DATES_IN_TEXT]]
        if len(inside) > MAX_DATES_IN_TEXT:
            shown.append(f"… и ещё {len(inside) - MAX_DATES_IN_TEXT}")
        place = item.get("place") if isinstance(item.get("place"), dict) else {}
        lat, lon = self._coords(place)
        age = item.get("age_restriction")
        return RawEvent(
            source=self.name,
            url=url,
            title=title,
            date_text="; ".join(shown),
            text=self._text(item),
            venue=_clean(place.get("title")),  # place_name не заполняем: отдельного названия у места в API нет
            price_text=self._price(item),
            collected_at=collected_at,
            address=_clean(place.get("address")),
            metro=_clean(place.get("subway")),
            lat=lat,
            lon=lon,
            age_restriction=_clean(str(age)) if age is not None else "",
            categories=[str(c) for c in item.get("categories") or [] if isinstance(c, (str, int))],
        )

    @staticmethod
    def _price(item: dict) -> str:
        price = _clean(item.get("price"))
        if price:
            return price
        return "бесплатно" if item.get("is_free") is True else ""  # цены нет и не бесплатно — оставляем пусто

    @staticmethod
    def _coords(place: dict) -> tuple[float | None, float | None]:
        """Координаты места; вне допустимых диапазонов или не числа — обе None (не угадываем)."""
        c = place.get("coords")
        if not isinstance(c, dict):
            return None, None
        lat, lon = c.get("lat"), c.get("lon")
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (lat, lon)):
            return None, None
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None, None
        return round(float(lat), 5), round(float(lon), 5)

    @staticmethod
    def _text(item: dict) -> str:
        """Свободный текст: тэглайн, описание, полный текст. Адрес, метро, возраст и категории едут отдельными полями."""
        body = _join_text(_clean(item.get("tagline")), _clean(item.get("description")), _clean(item.get("body_text")))
        if len(body) > MAX_TEXT_CHARS:
            body = body[:MAX_TEXT_CHARS].rsplit(" ", 1)[0] + "…"
        tags = [str(v) for v in item.get("tags") or [] if isinstance(v, (str, int))]  # отдельного поля под тэги нет
        return "\n".join(p for p in (body, f"Теги KudaGo: {', '.join(tags)}" if tags else "") if p)
