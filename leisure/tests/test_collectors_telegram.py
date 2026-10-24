"""Telegram по публичному превью t.me/s/<канал>. Фикстуры — ЖИВЫЕ страницы превью, снятые 2026-10-24 (каналы quda_today и kozlovclub;
страницы целиком, без правок; fixtures/collectors_live_snapshots.json). Сети нет: httpx.MockTransport."""
from __future__ import annotations

import gzip
import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest

from leisure.collectors import load_collectors
from leisure.collectors.base import REGISTRY, CollectorError, collect_all
from leisure.collectors.telegram import (
    ENABLE_ENV,
    MIN_TEXT_CHARS,
    TelegramCollector,
    TelegramMtprotoCollector,
    load_channels,
    make_title,
    parse_preview,
)

FIX = Path(__file__).with_name("fixtures")


def load(name: str) -> str:
    gz = FIX / f"{name}.gz"
    return gzip.open(gz, "rt", encoding="utf-8").read() if gz.exists() else (FIX / name).read_text(encoding="utf-8")


FROM, TO = date(2026, 10, 24), date(2026, 10, 31)
NOW = datetime(2026, 10, 24, 12, 0, 0, tzinfo=timezone.utc)
CHANNELS = [
    {"username": "quda_today", "name": "Куда сегодня (quda_today)"},
    {"username": "kozlovclub", "name": "Джаз-клуб Козлова", "tg": {"own_venue": "Клуб Алексея Козлова"}},
]


class FakeTelegram:
    """quda_today: страница 1 и страница `?before=` (обе живые); kozlovclub: одна страница, дальше пусто."""

    def __init__(self, robots_status: int = 404, robots: str = "", overrides: dict[str, httpx.Response] | None = None):
        self.robots_status, self.robots, self.overrides = robots_status, robots, overrides or {}
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.url.host == "t.me"
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(self.robots_status, text=self.robots)
        if path in self.overrides:
            return self.overrides[path]
        before = request.url.params.get("before")
        if path == "/s/quda_today":
            return httpx.Response(200, text=load("tg_quda_today_before.html" if before else "tg_quda_today.html"))
        if path == "/s/kozlovclub" and not before:
            return httpx.Response(200, text=load("tg_kozlovclub.html"))
        return httpx.Response(200, text="<html><body>пусто</body></html>")


def make(fake: FakeTelegram | None = None, **kw):
    fake = fake or FakeTelegram()
    sleeps: list[float] = []
    kw.setdefault("channels", CHANNELS)
    kw.setdefault("enabled", True)
    c = TelegramCollector(httpx.Client(transport=httpx.MockTransport(fake), follow_redirects=True), sleep=sleeps.append,
                          clock=lambda: NOW, **kw)
    return c, fake, sleeps


# ─── разбор живых страниц ───

def test_parse_live_preview_pages():
    posts, before = parse_preview(load("tg_quda_today.html"))
    assert len(posts) == 13 and before == 10296
    first = posts[0]
    assert (first.channel, first.post_id, first.url) == ("quda_today", 10296, "https://t.me/quda_today/10296")
    assert first.published == datetime.fromisoformat("2026-10-22T16:14:42+03:00")
    assert first.text.startswith("добавляем немного хоррора к ужину")
    assert "\n📍Meteorite, покровка 20/1с1\n" in first.text      # <br/> стали переводами строк, эмодзи сохранились
    assert "<" not in first.text and "&#33;" not in first.text
    assert first.links == ["https://www.instagram.com/meteorite.bistro?cplk=cnBscGU0ZXQ2eTVo"]  # хэштеги и t.me не ссылки
    older, before2 = parse_preview(load("tg_quda_today_before.html"))
    assert (len(older), before2) == (15, 10276) and max(p.post_id for p in older) < first.post_id


def test_posts_without_text_have_empty_text_and_every_post_has_a_date():
    posts, _ = parse_preview(load("tg_kozlovclub.html"))
    assert len(posts) == 8 and all(p.published for p in posts)
    assert all(p.channel == "kozlovclub" for p in posts)


def test_parse_of_a_page_without_posts():
    assert parse_preview("<html>нет такого канала</html>") == ([], None)


def test_make_title():
    assert make_title("🎤 25 ОКТЯБРЯ | МАРИАМ МЕРАБОВА\nдальше") == "25 ОКТЯБРЯ | МАРИАМ МЕРАБОВА"
    assert make_title("\n\n⚡\nВторая строка") == "Вторая строка"
    long = make_title("слово " * 60)
    assert len(long) <= 141 and long.endswith("…")
    assert make_title("🎉🎉") == ""


# ─── сбор ───

def test_live_snapshot_collects_posts_of_the_window_with_permalinks():
    c, fake, sleeps = make()
    events = c.collect("Москва", FROM, TO)
    assert len(events) == 35
    assert (c.stats.pages, c.stats.fetched, c.stats.kept) == (4, 36, 35)      # quda_today: 2 страницы (13+15 постов), kozlovclub: 8 + пустой конец ленты
    assert c.stats.skipped == 1 and c.stats.truncated is True                 # 1 пост — почти без текста; у quda_today за второй страницей есть ещё
    assert sleeps == [2.0, 2.0, 2.0]
    for e in events:
        assert e.source == "telegram" and e.url.startswith("https://t.me/") and e.url.rsplit("/", 1)[1].isdigit()
        assert e.date_text.startswith("пост опубликован 2026-10-") and "даты события смотри в тексте" in e.date_text
        assert e.text.startswith("Канал: ")
    assert len({e.url for e in events}) == len(events)
    assert [r.url.path for r in fake.requests].count("/robots.txt") == 1
    assert any(r.url.params.get("before") == "10296" for r in fake.requests)      # вторая страница — по `before` из первой


def test_own_venue_of_a_venue_channel_goes_to_card_and_links_to_text():
    c, _, _ = make()
    events = {e.url: e for e in c.collect("Москва", FROM, TO)}
    e = events["https://t.me/kozlovclub/10091"]
    assert e.title == "25 ОКТЯБРЯ | МАРИАМ МЕРАБОВА" and e.venue == "Клуб Алексея Козлова"
    assert "Ссылки в посте: https://kozlovclub.ru/event/mariam-merabova-15/" in e.text
    quda = events["https://t.me/quda_today/10296"]
    assert quda.venue == "" and "Канал: Куда сегодня (quda_today) (@quda_today)" in quda.text


def test_window_only_keeps_recent_posts_and_stops_paging_when_old_enough():
    c, fake, _ = make(channels=CHANNELS[:1])
    assert c.collect("Москва", date(2026, 12, 1), date(2026, 12, 7)) == []   # все посты старше окна минус неделя
    assert c.stats.outside_window == 13 - c.stats.skipped and c.stats.pages == 1
    assert not any(r.url.query for r in fake.requests)                        # на старую страницу не пошли


def test_lookback_week_keeps_announcements_made_before_the_window():
    window = (date(2026, 10, 25), date(2026, 10, 31))   # посты quda_today на странице 1 вышли 22-24.10, до начала окна
    with_lookback, _, _ = make(channels=CHANNELS[:1], max_pages=1)
    without, _, _ = make(channels=CHANNELS[:1], max_pages=1, lookback_days=0)
    assert len(with_lookback.collect("Москва", *window)) == 12
    assert without.collect("Москва", *window) == [] and without.stats.outside_window == 12


def test_short_posts_and_posts_without_date_are_skipped():
    def post(i, text, dt='datetime="2026-10-24T10:00:00+00:00"'):
        time_tag = f"<time {dt}>10:00</time>" if dt else ""
        return (f'<div class="tgme_widget_message_wrap"><div class="tgme_widget_message js-widget_message" data-post="chan_x/{i}">'
                f'<div class="tgme_widget_message_text js-message_text">{text}</div>'
                f'<a class="tgme_widget_message_date" href="https://t.me/chan_x/{i}">{time_tag}</a></div></div>')

    page = "<html><body>" + post(1, "ок") + post(2, "Вечеринка в клубе " + "x" * MIN_TEXT_CHARS) + post(3, "Текст без даты " + "y" * 60, dt="") + "</body></html>"
    c, _, _ = make(FakeTelegram(overrides={"/s/chan_x": httpx.Response(200, text=page)}), channels=[{"username": "chan_x", "name": "Тест"}])
    events = c.collect("Москва", FROM, TO)
    assert [e.url for e in events] == ["https://t.me/chan_x/2"] and c.stats.skipped == 2


def test_same_post_on_two_pages_is_not_doubled():
    page = load("tg_kozlovclub.html")
    fake = FakeTelegram(overrides={"/s/kozlovclub": httpx.Response(200, text=page)})
    c, _, _ = make(fake, channels=CHANNELS[1:])
    events = c.collect("Москва", FROM, TO)          # обе страницы одинаковые: превью «поехало» между запросами
    assert c.stats.duplicates == 8 and len({e.url for e in events}) == len(events)


# ─── включение и заглушка ───

def test_disabled_by_default_and_says_why(monkeypatch):
    monkeypatch.delenv(ENABLE_ENV, raising=False)
    c = TelegramCollector(httpx.Client(transport=httpx.MockTransport(FakeTelegram())), channels=CHANNELS)
    with pytest.raises(CollectorError, match=f"выключено.*{ENABLE_ENV}=1"):
        c.collect("Москва", FROM, TO)


def test_env_switch_enables(monkeypatch):
    monkeypatch.setenv(ENABLE_ENV, "1")
    fake = FakeTelegram()
    c = TelegramCollector(httpx.Client(transport=httpx.MockTransport(fake)), channels=CHANNELS[:1], sleep=lambda s: None, clock=lambda: NOW)
    assert c.collect("Москва", FROM, TO)
    monkeypatch.setenv(ENABLE_ENV, "0")
    with pytest.raises(CollectorError):
        TelegramCollector(channels=CHANNELS).collect("Москва", FROM, TO)


def test_mtproto_stub_asks_for_api_id_and_login():
    with pytest.raises(CollectorError, match="api_id/api_hash.*вход"):
        TelegramCollector(mode="mtproto", channels=CHANNELS).collect("Москва", FROM, TO)
    with pytest.raises(CollectorError, match="api_id/api_hash"):
        TelegramMtprotoCollector().collect("Москва", FROM, TO)
    assert "telegram_mtproto" not in REGISTRY  # заглушку не регистрируем: всегда падала бы в сводке


# ─── robots.txt и сбои ───

def test_robots_missing_404_means_no_restrictions_and_closed_means_closed():
    c, _, _ = make(FakeTelegram(robots_status=404))
    assert c.collect("Москва", FROM, TO)
    c, fake, _ = make(FakeTelegram(robots_status=200, robots="User-agent: *\nDisallow: /s/\n"))
    with pytest.raises(CollectorError, match="ни одна страница превью не получена.*закрыто robots.txt"):
        c.collect("Москва", FROM, TO)
    assert c.stats.blocked_by_robots == 2 and [r.url.path for r in fake.requests] == ["/robots.txt"]


def test_channel_without_public_preview_is_reported_and_others_still_work():
    fake = FakeTelegram(overrides={"/s/kozlovclub": httpx.Response(302, headers={"location": "https://t.me/kozlovclub"})})

    def handler(request):
        if request.url.path == "/kozlovclub":
            return httpx.Response(200, text="<html>Обычная страница канала</html>")
        return fake(request)

    c = TelegramCollector(httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True), channels=CHANNELS, enabled=True,
                          sleep=lambda s: None, clock=lambda: NOW)
    events = c.collect("Москва", FROM, TO)
    assert events and all("quda_today" in e.url for e in events)
    assert c.stats.failed_pages == 1


def test_429_everywhere_is_reported_and_not_hammered():
    fake = FakeTelegram(overrides={"/s/quda_today": httpx.Response(429), "/s/kozlovclub": httpx.Response(429)})
    c, fake, _ = make(fake, retries=0)
    with pytest.raises(CollectorError, match="HTTP 429"):
        c.collect("Москва", FROM, TO)
    assert len([r for r in fake.requests if r.url.path.startswith("/s/")]) == 2   # по одному запросу на канал, без штурма


def test_empty_channel_list_and_bad_dates():
    c, _, _ = make(channels=[])
    with pytest.raises(CollectorError, match="нет каналов"):
        c.collect("Москва", FROM, TO)
    c, _, _ = make()
    with pytest.raises(ValueError):
        c.collect("Москва", TO, FROM)


# ─── реестр каналов и конвейер ───

def test_channels_come_from_the_registry_only_public_and_active():
    channels = load_channels()
    names = {c["username"] for c in channels}
    assert len(channels) >= 30 and {"quda_today", "kozlovclub", "garagemca", "mscculture"} <= names
    assert all(c["tg"]["preview_public"] and c["tg"]["active"] for c in channels)
    data = json.loads((Path(__file__).parents[1] / "seed" / "sources.json").read_text(encoding="utf-8"))
    inactive = {s["username"] for s in data["sources"] if s["type"] == "tg" and not s["tg"]["active"]}
    assert inactive and not inactive & names


def test_registered_and_picked_up_by_collect_all(monkeypatch):
    assert "telegram" in load_collectors() and REGISTRY["telegram"] is TelegramCollector
    fake = FakeTelegram()

    class OnFixtures(TelegramCollector):
        def __init__(self):
            super().__init__(httpx.Client(transport=httpx.MockTransport(fake)), channels=CHANNELS, enabled=True, sleep=lambda s: None)

    monkeypatch.setitem(REGISTRY, "telegram", OnFixtures)
    result = collect_all("Москва", FROM, TO, names=["telegram"])
    assert result.sources[0].ok and result.sources[0].count == 35


def test_disabled_telegram_shows_up_in_run_summary_not_silently(monkeypatch):
    monkeypatch.delenv(ENABLE_ENV, raising=False)
    load_collectors()
    result = collect_all("Москва", FROM, TO, names=["telegram"])
    assert not result.sources[0].ok and "выключено" in result.sources[0].error
