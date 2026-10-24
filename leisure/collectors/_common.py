"""Общее для коллекторов: часовой пояс, счётчики запуска, очистка текста, GET с повторами.

Модуль не источник (имя с подчёркиванием, load_collectors его пропускает); источники импортируют отсюда,
а не друг из друга.
"""
from __future__ import annotations

import html
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta, timezone
from typing import Any

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
