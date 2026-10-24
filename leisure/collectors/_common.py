"""Общее для коллекторов: часовой пояс, счётчики запуска, очистка текста, GET с повторами.

Модуль не источник (имя с подчёркиванием, load_collectors его пропускает); источники импортируют отсюда,
а не друг из друга.
"""
from __future__ import annotations

import html
import json
import logging
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib import robotparser
from urllib.parse import urlsplit

import httpx

from .base import CollectorError

log = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3), "MSK")  # в Москве UTC+3 круглый год с 2014 года, tzdata не нужен

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
RETRY_AFTER_CAP_SEC = 30.0

_BLOCK_END_RE = re.compile(r"(?i)<br\s*/?>|</(?:p|div|li|ul|ol|h[1-6]|tr)>")


@dataclass
class CollectStats:
    """Итоги последнего запуска — для отчёта воркера («сколько дал источник»)."""

    pages: int = 0
    total_in_api: int | None = None
    fetched: int = 0
    kept: int = 0
    outside_window: int = 0
    skipped: int = 0
    duplicates: int = 0
    truncated: bool = False


def clean_text(value: Any) -> str:
    """Текст без тегов и сущностей, с нормальными пробелами; концы блоков (<p>, <br>, <li>) становятся переводами строк."""
    if not isinstance(value, str):
        return ""
    s = _BLOCK_END_RE.sub("\n", value)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s).replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\s*\n\s*", "\n", s)
    return re.sub(r"\n{2,}", "\n\n", s).strip()


def join_text(*parts: str) -> str:
    """Склеивает абзацы без повторов: описание часто целиком входит в полный текст."""
    out: list[str] = []
    for p in parts:
        if p and not any(p in q for q in out):
            out = [q for q in out if q not in p] + [p]
    return "\n\n".join(out)


def get_with_retries(
    client: httpx.Client, url: str, *, params: dict | None, headers: dict[str, str], retries: int,
    sleep: Callable[[float], None], source: str, http_error: Callable[[httpx.Response], str],
) -> httpx.Response:
    """GET: повторы только для сетевых сбоев и 429/5xx (с учётом Retry-After); прочие 4xx — сразу CollectorError."""
    reason = "нет ответа"
    for attempt in range(retries + 1):
        wait = 2.0 * (attempt + 1)
        try:
            resp = client.get(url, params=params, headers=headers)
        except httpx.TransportError as exc:  # таймауты, обрывы, DNS, отказ соединения
            reason = f"{type(exc).__name__}: {exc}"
        else:
            if resp.status_code == 200:
                return resp
            if resp.status_code not in RETRY_STATUSES:
                raise CollectorError(http_error(resp))
            reason = f"HTTP {resp.status_code}"
            retry_after = resp.headers.get("Retry-After", "")
            if retry_after.isdigit():
                wait = min(float(retry_after), RETRY_AFTER_CAP_SEC)
        if attempt < retries:
            log.warning("%s: %s, повтор через %.0f с", source, reason, wait)
            sleep(wait)
    raise CollectorError(f"{source} недоступен ({reason}); попыток: {retries + 1}. Повторите сбор позже.")


# ─── разбор HTML-страниц со встроенными данными (JSON-LD, __NEXT_DATA__) ───

_LD_RE = re.compile(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I)
_NEXT_RE = re.compile(r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', re.S | re.I)


def iter_jsonld(page: str) -> Iterator[dict]:
    """Все объекты schema.org со страницы: блоки `application/ld+json`, списки и `@graph` раскрыты на плоский поток.

    Битый блок пропускается (на странице их несколько, один плохой не должен ронять остальные).
    """
    def walk(node: Any) -> Iterator[dict]:
        if isinstance(node, list):
            for x in node:
                yield from walk(x)
        elif isinstance(node, dict):
            if isinstance(node.get("@graph"), list):
                yield from walk(node["@graph"])
            else:
                yield node

    for m in _LD_RE.finditer(page):
        try:
            data = json.loads(m.group(1).strip())
        except ValueError:
            log.warning("JSON-LD: блок не разобран, пропущен")
            continue
        yield from walk(data)


def next_data(page: str) -> dict | None:
    """Содержимое `<script id="__NEXT_DATA__">` (серверная выдача Next.js) или None, если его нет или оно битое."""
    m = _NEXT_RE.search(page)
    if not m:
        return None
    try:
        data = json.loads(m.group(1).strip())
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def parse_iso(value: Any) -> datetime | None:
    """ISO-дата/время ('…+03:00', 'Z', без пояса или только дата) → московское время; мусор → None."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    if " " in text and "T" not in text:
        text = text.replace(" ", "T", 1)
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=MSK)).astimezone(MSK)


def format_span(start: datetime, end: datetime | None, *, with_time: bool = True) -> str:
    """'2026-10-24 19:00–21:00' · ночью '… — …' · от суток и дольше 'период с … по …'. with_time=False — только даты."""
    def fmt(dt: datetime) -> str:
        return dt.strftime("%Y-%m-%d %H:%M" if with_time else "%Y-%m-%d")

    if end is None or end <= start:
        return fmt(start)
    if end.date() == start.date():
        return f"{fmt(start)}–{end.strftime('%H:%M')}" if with_time else fmt(start)
    if with_time and end - start < timedelta(hours=24):
        return f"{fmt(start)} — {fmt(end)}"
    return f"период с {fmt(start)} по {fmt(end)}"


def overlaps(start: datetime, end: datetime | None, window_start: datetime, window_end: datetime) -> bool:
    """Событие [start, end] пересекает окно [window_start, window_end); без конца считаем его моментом."""
    return start < window_end and (end or start) >= window_start


# ─── robots.txt ───


class RobotsGuard:
    """Читает robots.txt хоста один раз за запуск и отвечает, можно ли нашему боту открыть страницу (RFC 9309).

    200 — разбираем; 401/403 — всё закрыто; прочие 4xx (в том числе 404) — ограничений нет; сетевой сбой и 5xx —
    CollectorError (не рискуем и не гадаем). Запрет страницы — не ошибка источника: вызывающий пропускает страницу.
    """

    def __init__(self, client: httpx.Client, user_agent: str, source: str) -> None:
        self._client, self._ua, self._source = client, user_agent, source
        self._parsers: dict[str, robotparser.RobotFileParser | bool] = {}  # True — всё разрешено, False — всё закрыто

    def allows(self, url: str) -> bool:
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self._parsers:
            self._parsers[base] = self._load(base)
        rules = self._parsers[base]
        return rules if isinstance(rules, bool) else rules.can_fetch(self._ua, url)

    def _load(self, base: str) -> robotparser.RobotFileParser | bool:
        try:
            resp = self._client.get(f"{base}/robots.txt", headers={"User-Agent": self._ua})
        except httpx.TransportError as exc:
            raise CollectorError(f"{self._source}: robots.txt недоступен ({type(exc).__name__}: {exc}), сбор отложен.") from exc
        if resp.status_code in (401, 403):
            log.warning("%s: robots.txt отвечает %d, считаем доступ закрытым", self._source, resp.status_code)
            return False
        if resp.status_code >= 500:
            raise CollectorError(f"{self._source}: robots.txt не прочитан (HTTP {resp.status_code}), сбор отложен.")
        if resp.status_code != 200:
            return True
        parser = robotparser.RobotFileParser()
        parser.parse(resp.text.splitlines())
        return parser


# ─── постраничная выкачка HTML ───


@dataclass
class PageStats(CollectStats):
    """Счётчики HTML-коллекторов: к общим добавлены страницы, закрытые robots.txt, и страницы, которые не открылись."""

    blocked_by_robots: int = 0
    failed_pages: int = 0


def fetch_pages(
    client: httpx.Client, urls: list[str], *, guard: RobotsGuard | None, headers: dict[str, str], retries: int,
    sleep: Callable[[float], None], pause_sec: float, source: str, http_error: Callable[[httpx.Response], str],
    stats: PageStats,
) -> list[tuple[str, str]]:
    """Скачивает страницы по одной с паузой. Закрытую robots.txt или не открывшуюся страницу пропускает и считает.

    Если не удалось получить ни одной — CollectorError с причиной первой неудачи: источник «молчит», а не отдаёт пустоту.
    """
    out: list[tuple[str, str]] = []
    problems: list[str] = []
    first = True
    for url in urls:
        if guard is not None and not guard.allows(url):
            stats.blocked_by_robots += 1
            problems.append(f"{url}: закрыто robots.txt")
            log.warning("%s: %s закрыт robots.txt, пропускаем", source, url)
            continue
        if not first:
            sleep(pause_sec)
        first = False
        try:
            resp = get_with_retries(
                client, url, params=None, headers=headers, retries=retries, sleep=sleep, source=source,
                http_error=http_error,
            )
        except CollectorError as exc:
            stats.failed_pages += 1
            problems.append(str(exc))
            log.warning("%s: страница %s не получена: %s", source, url, exc)
            continue
        stats.pages += 1
        out.append((url, resp.text))
    if not out:
        raise CollectorError(f"{source}: ни одна страница не получена. " + (problems[0] if problems else "список страниц пуст"))
    return out
