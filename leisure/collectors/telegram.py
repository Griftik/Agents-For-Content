"""Коллектор Telegram-каналов по публичному веб-превью `https://t.me/s/<канал>` (путь без ключей).

Два пути к постам каналов:
1. Публичное превью t.me/s/<канал>: обычный HTML без входа, около 20 последних постов на страницу, дальше
   `?before=<id>`. Работает без `api_id`/`api_hash`; проверено 2026-10-24 на всех каналах из реестра. Этот коллектор.
2. MTProto (Telethon): нужны `api_id`/`api_hash` с my.telegram.org и вход под аккаунтом владельца. Решение владельца
   отложено, поэтому это заглушка `TelegramMtprotoCollector`: она не зарегистрирована и сразу отвечает CollectorError.

Каналы берутся из реестра `seed/sources.json` (записи `access: "tg"`, у которых `tg.preview_public` и `tg.active`).

Что делает коллектор: по каждому каналу забирает свежие посты за окно (плюс неделя назад: анонсы выходят заранее) и
отдаёт каждый пост как сырую карточку. Пост — свободный текст, а не карточка события: дата события, площадка и цена
лежат в тексте, поэтому `date_text` говорит «пост опубликован …», а извлечение и confidence «нужно проверить» на
нормализаторе. Дайджест из нескольких событий нормализатор сейчас сводит к одному: известное ограничение.
Ссылка на первоисточник — постоянная ссылка на пост `https://t.me/<канал>/<номер>`.

robots.txt: у t.me его нет (404, проверено 2026-10-24), у telegram.org тоже; наш бот всё равно читает его при запуске.

ВАЖНО, юридическое: условия Telegram (https://telegram.org/tos и https://telegram.org/tos/content-licensing) запрещают
«scraping, indexing, harvesting, aggregation» данных для ИИ и ограничивают доступ к пользовательскому контенту
«обычным, законным и предусмотренным использованием». Наша цель (афиша для людей, LLM только структурирует текст,
обучения нет) прямо не названа, но риск не нулевой, поэтому коллектор по умолчанию ВЫКЛЮЧЕН: включает владелец
переменной `TELEGRAM_PREVIEW_ENABLED=1` (или `TelegramCollector(enabled=True)`). Выключенный коллектор честно
сообщает об этом в сводке запуска, а не молчит.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time as _time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode

import httpx

from leisure import (
    settings,  # noqa: F401  — при импорте подгружает .env, откуда берётся TELEGRAM_PREVIEW_ENABLED
)
from leisure.normalize.schema import RawEvent

from ._common import MSK, PageStats, RobotsGuard, get_with_retries, parse_iso
from ._common import clean_text as _clean
from .base import Collector, CollectorError, register

log = logging.getLogger(__name__)

ENABLE_ENV = "TELEGRAM_PREVIEW_ENABLED"
PREVIEW_URL = "https://t.me/s/{channel}"
SOURCES_PATH = Path(__file__).resolve().parents[1] / "seed" / "sources.json"
USER_AGENT = "LeisurePlannerBot/0.1 (event planner for Moscow; polite, rate-limited, public preview pages only)"
PAUSE_SEC = 2.0
TIMEOUT_SEC = 20.0
RETRIES = 2
MAX_PAGES = 2             # ~20 постов на страницу: две страницы покрывают неделю-две у большинства каналов
LOOKBACK_DAYS = 7         # анонс выходит заранее: посты за неделю до начала окна ещё могут быть про события окна
MIN_TEXT_CHARS = 40       # короче — это подпись к картинке или «доброе утро», не анонс
MAX_TEXT_CHARS = 4000
MTPROTO_MESSAGE = (
    "Telegram через MTProto: нужны api_id/api_hash (получить на my.telegram.org) и вход под аккаунтом владельца. "
    "Решение по доступам отложено; без ключей работает публичное превью t.me/s/ (TelegramCollector)."
)
DISABLED_MESSAGE = (
    f"Telegram-превью выключено до решения владельца: условия Telegram ограничивают сбор данных (telegram.org/tos, "
    f"раздел о лицензировании контента). Включить: {ENABLE_ENV}=1 или TelegramCollector(enabled=True)."
)

_POST_ID_RE = re.compile(r"^(?P<channel>[A-Za-z0-9_]{3,64})/(?P<id>\d+)$")
_EMOJI_PREFIX_RE = re.compile(r"^[\W_]+", re.UNICODE)


@dataclass
class Post:
    channel: str
    post_id: int
    published: datetime | None = None
    text: str = ""
    links: list[str] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"https://t.me/{self.channel}/{self.post_id}"


class _PreviewParser(HTMLParser):
    """Разбор t.me/s/<канал>: посты (`div.tgme_widget_message[data-post]`), их текст, дата и внешние ссылки."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.posts: list[Post] = []
        self.before: int | None = None
        self._cur: Post | None = None
        self._text_depth = 0
        self._parts: list[str] = []
        self._in_date_link = False

    @staticmethod
    def _classes(attrs: dict) -> set[str]:
        return set((attrs.get("class") or "").split())

    def handle_starttag(self, tag: str, attrs_list: list) -> None:
        attrs = dict(attrs_list)
        cls = self._classes(attrs)
        if tag == "a" and "tme_messages_more" in cls and (attrs.get("data-before") or "").isdigit():
            self.before = int(attrs["data-before"])
        if tag == "div" and "tgme_widget_message" in cls and attrs.get("data-post"):
            m = _POST_ID_RE.match(attrs["data-post"])
            self._finish_text()
            self._cur = Post(m["channel"], int(m["id"])) if m else None
            if self._cur:
                self.posts.append(self._cur)
            return
        if self._cur is None:
            return
        if tag == "div" and self._text_depth:
            self._text_depth += 1
        elif tag == "div" and "tgme_widget_message_text" in cls and "js-message_reply_text" not in cls:
            self._text_depth = 1
            self._parts = []
        elif tag == "a" and "tgme_widget_message_date" in cls:
            self._in_date_link = True
        elif tag == "time" and self._in_date_link and attrs.get("datetime"):
            self._cur.published = parse_iso(attrs["datetime"])
        elif tag == "br" and self._text_depth:
            self._parts.append("\n")
        elif tag == "a" and self._text_depth:
            href = attrs.get("href") or ""
            if href.startswith(("http://", "https://")) and "//t.me/" not in href and href not in self._cur.links:
                self._cur.links.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._in_date_link = False
        if tag == "div" and self._text_depth:
            self._text_depth -= 1
            if self._text_depth == 0:
                self._finish_text()

    def handle_data(self, data: str) -> None:
        if self._text_depth:
            self._parts.append(data)

    def _finish_text(self) -> None:
        if self._cur is not None and self._parts:
            self._cur.text = _clean("".join(self._parts))
        self._parts = []
        self._text_depth = 0


def parse_preview(page: str) -> tuple[list[Post], int | None]:
    """Посты страницы превью (в порядке страницы: от старых к новым) и `before` для следующей, более старой страницы."""
    parser = _PreviewParser()
    parser.feed(page)
    parser.close()
    return parser.posts, parser.before


def load_channels(path: Path = SOURCES_PATH) -> list[dict]:
    """Каналы реестра, которые можно собирать через превью: access=tg, tg.preview_public и tg.active."""
    data = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for s in data.get("sources", []):
        tg = s.get("tg") or {}
        if s.get("access") == "tg" and s.get("username") and tg.get("preview_public") and tg.get("active"):
            out.append(s)
    return out


def make_title(text: str, limit: int = 140) -> str:
    """Первая содержательная строка поста без ведущих эмодзи и знаков; длиннее limit — обрезаем по слову."""
    for line in text.splitlines():
        line = _EMOJI_PREFIX_RE.sub("", line).strip()
        if len(line) >= 3:
            return line if len(line) <= limit else line[:limit].rsplit(" ", 1)[0].rstrip(",.;:—-") + "…"
    return ""


def _enabled_by_env() -> bool:
    return os.environ.get(ENABLE_ENV, "0").strip() == "1"


@register
class TelegramCollector(Collector):
    name = "telegram"
    cities = ("Москва",)

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        channels: list[dict] | None = None,
        enabled: bool | None = None,
        mode: str = "preview",
        respect_robots: bool = True,
        max_pages: int = MAX_PAGES,
        lookback_days: int = LOOKBACK_DAYS,
        pause_sec: float = PAUSE_SEC,
        retries: int = RETRIES,
        timeout: float = TIMEOUT_SEC,
        sleep: Callable[[float], None] = _time.sleep,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._channels = channels
        self.enabled = _enabled_by_env() if enabled is None else enabled
        self.mode = mode
        self.respect_robots = respect_robots
        self.max_pages = max(1, max_pages)
        self.lookback_days = lookback_days
        self.pause_sec, self.retries, self.timeout = pause_sec, max(0, retries), timeout
        self._sleep = sleep
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.stats = PageStats()

    # ─── публичный интерфейс ───

    def collect(self, city: str, date_from: date, date_to: date) -> list[RawEvent]:
        if self.mode == "mtproto":
            raise CollectorError(MTPROTO_MESSAGE)
        if not self.enabled:
            raise CollectorError(DISABLED_MESSAGE)
        if date_from > date_to:
            raise ValueError("date_from позже date_to")
        channels = self._channels if self._channels is not None else load_channels()
        if not channels:
            raise CollectorError("Telegram: в реестре нет каналов с публичным превью (seed/sources.json).")
        keep_from = datetime.combine(date_from - timedelta(days=self.lookback_days), time.min, tzinfo=MSK)
        keep_to = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=MSK)
        self.stats = PageStats()
        own_client = self._client is None
        client = self._client or httpx.Client(timeout=httpx.Timeout(self.timeout), follow_redirects=True)
        try:
            guard = RobotsGuard(client, USER_AGENT, "Telegram") if self.respect_robots else None
            return self._collect_channels(client, guard, channels, keep_from, keep_to)
        finally:
            if own_client:
                client.close()

    # ─── сеть ───

    def _headers(self) -> dict[str, str]:
        return {"User-Agent": USER_AGENT, "Accept": "text/html"}

    @staticmethod
    def _http_error(resp: httpx.Response) -> str:
        if resp.status_code in (401, 403, 429):
            return f"Telegram ответил {resp.status_code}: превью закрыто или частота слишком высока. Защиту не обходим."
        return f"Telegram ответил HTTP {resp.status_code}."

    def _fetch(self, client: httpx.Client, channel: str, before: int | None) -> str:
        url = PREVIEW_URL.format(channel=channel)
        if before:
            url += "?" + urlencode({"before": before})
        resp = get_with_retries(
            client, url, params=None, headers=self._headers(), retries=self.retries, sleep=self._sleep,
            source="Telegram", http_error=self._http_error,
        )
        if "/s/" not in resp.url.path:  # превью выключено: t.me редиректит на обычную страницу канала
            raise CollectorError(f"Telegram: у канала @{channel} нет публичного превью (редирект на {resp.url}).")
        return resp.text

    # ─── сбор ───

    def _collect_channels(self, client, guard, channels, keep_from: datetime, keep_to: datetime) -> list[RawEvent]:
        collected_at = self._clock().isoformat(timespec="seconds")
        out: list[RawEvent] = []
        seen: set[str] = set()
        problems: list[str] = []
        first = True
        for ch in channels:
            name = ch["username"]
            url = PREVIEW_URL.format(channel=name)
            if guard is not None and not guard.allows(url):
                self.stats.blocked_by_robots += 1
                problems.append(f"@{name}: закрыто robots.txt")
                continue
            before: int | None = None
            for page_no in range(1, self.max_pages + 1):
                if not first:
                    self._sleep(self.pause_sec)
                first = False
                try:
                    page = self._fetch(client, name, before)
                except CollectorError as exc:
                    self.stats.failed_pages += 1
                    problems.append(str(exc))
                    log.warning("Telegram: @%s (страница %d): %s", name, page_no, exc)
                    break
                self.stats.pages += 1
                posts, older = parse_preview(page)
                if not posts:  # на первой странице это беда (канал закрыт или удалён), на следующих — просто конец ленты
                    if page_no == 1:
                        self.stats.failed_pages += 1
                        problems.append(f"@{name}: на странице превью нет постов")
                        log.warning("Telegram: у @%s на странице превью нет постов", name)
                    break
                for post in posts:
                    self.stats.fetched += 1
                    if post.url in seen:  # лента сдвинулась между двумя загрузками страниц: один пост на стыке дважды
                        self.stats.duplicates += 1
                        continue
                    seen.add(post.url)
                    raw = self._to_raw(post, ch, keep_from, keep_to, collected_at)
                    if raw is not None:
                        out.append(raw)
                        self.stats.kept += 1
                dated = [p.published for p in posts if p.published]
                if not older or not dated or min(dated) < keep_from or page_no == self.max_pages:
                    if older and dated and min(dated) >= keep_from and page_no == self.max_pages:
                        self.stats.truncated = True
                    break
                before = older
        if self.stats.pages == 0:
            raise CollectorError("Telegram: ни одна страница превью не получена. " + (problems[0] if problems else ""))
        return out

    def _to_raw(self, post: Post, ch: dict, keep_from: datetime, keep_to: datetime, collected_at: str) -> RawEvent | None:
        if post.published is None or len(post.text) < MIN_TEXT_CHARS:
            self.stats.skipped += 1  # без даты публикации или почти без текста (картинка с подписью) разбирать нечего
            return None
        if not (keep_from <= post.published < keep_to):
            self.stats.outside_window += 1
            return None
        title = make_title(post.text)
        if not title:
            self.stats.skipped += 1
            return None
        text = post.text if len(post.text) <= MAX_TEXT_CHARS else post.text[:MAX_TEXT_CHARS].rsplit(" ", 1)[0] + "…"
        header = f"Канал: {ch.get('name') or ch['username']} (@{ch['username']})"
        links = f"Ссылки в посте: {', '.join(post.links[:3])}" if post.links else ""
        tg = ch.get("tg") or {}
        return RawEvent(
            source=self.name,
            url=post.url,
            title=title,
            date_text=f"пост опубликован {post.published.strftime('%Y-%m-%d %H:%M')}; даты события смотри в тексте поста",
            text="\n".join(p for p in (header, text, links) if p),
            venue=_clean(tg.get("own_venue")),
            collected_at=collected_at,
        )


class TelegramMtprotoCollector(Collector):
    """Заглушка пути через Telethon. Не зарегистрирована: пока нет api_id/api_hash и входа, ей нечего собирать."""

    name = "telegram_mtproto"

    def collect(self, city: str, date_from: date, date_to: date) -> list[RawEvent]:
        raise CollectorError(MTPROTO_MESSAGE)


__all__ = ["TelegramCollector", "TelegramMtprotoCollector", "load_channels", "make_title", "parse_preview"]
