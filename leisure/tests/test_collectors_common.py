"""Общие помощники коллекторов: robots.txt по RFC 9309, JSON-LD, __NEXT_DATA__, даты, постраничная выкачка."""
from __future__ import annotations

from datetime import datetime

import httpx
import pytest

from leisure.collectors._common import (
    MSK,
    PageStats,
    RedirectBlocked,
    RobotsGuard,
    RobotsRules,
    fetch_pages,
    format_span,
    get_checking_robots,
    iter_jsonld,
    next_data,
    overlaps,
    parse_iso,
)
from leisure.collectors.base import CollectorError

UA = "LeisurePlannerBot/0.1 (event planner for Moscow; polite)"


# ─── robots.txt ───

def test_robots_star_group_with_wildcards_and_longest_match():
    rules = RobotsRules("User-agent: *\nDisallow: *?*\nDisallow: /max*\nAllow: /max/open\nDisallow: /a$\n", UA)
    assert rules.allows("https://x.example/koncerty/")
    assert not rules.allows("https://x.example/koncerty/?page=2")
    assert not rules.allows("https://x.example/maximum")
    assert rules.allows("https://x.example/max/open")  # Allow (9 символов) длиннее Disallow: /max* (5)
    assert not rules.allows("https://x.example/a") and rules.allows("https://x.example/ab")


def test_robots_bot_name_is_matched_whole_not_as_substring():
    """Стандартный robotparser считал бы группу «Bot» своей для любого *Bot: у bilet.mos.ru так закрывался весь сайт."""
    text = "User-agent: Bot\nDisallow: /\n\nUser-agent: IS\nDisallow: /\n\nUser-agent: *\nDisallow: /private/\n"
    rules = RobotsRules(text, UA)
    assert rules.allows("https://x.example/") and not rules.allows("https://x.example/private/x")


def test_robots_own_group_beats_star_and_empty_disallow_allows_everything():
    text = "User-agent: *\nDisallow: /\n\nUser-agent: LeisurePlannerBot\nDisallow:\n"
    assert RobotsRules(text, UA).allows("https://x.example/anything")
    assert not RobotsRules("User-agent: *\nDisallow: /\n", UA).allows("https://x.example/")


def test_robots_groups_with_several_agents_and_comments():
    text = "# комментарий\nUser-agent: a\nUser-agent: leisureplannerbot  # мы\nDisallow: /x/\n\nUser-agent: *\nDisallow:\n"
    rules = RobotsRules(text, UA)
    assert not rules.allows("https://x.example/x/1") and rules.allows("https://x.example/y")


def test_robots_equal_length_allow_wins():
    assert RobotsRules("User-agent: *\nDisallow: /p\nAllow: /p\n", UA).allows("https://x.example/p")


def guard(status: int, body: str = "", exc: Exception | None = None) -> RobotsGuard:
    def handler(request):
        if exc:
            raise exc
        return httpx.Response(status, text=body)
    return RobotsGuard(httpx.Client(transport=httpx.MockTransport(handler)), UA, "Тест")


def test_guard_statuses_follow_rfc_9309():
    assert guard(200, "User-agent: *\nDisallow: /x\n").allows("https://h.example/y")
    assert not guard(200, "User-agent: *\nDisallow: /x\n").allows("https://h.example/x")
    assert guard(404).allows("https://h.example/x")           # robots.txt нет — ограничений нет
    assert not guard(403).allows("https://h.example/x")       # доступ к robots.txt закрыт — считаем закрытым всё
    with pytest.raises(CollectorError, match="не прочитан"):
        guard(503).allows("https://h.example/x")
    with pytest.raises(CollectorError, match="недоступен"):
        guard(200, exc=httpx.ConnectError("нет сети")).allows("https://h.example/x")


def test_guard_reads_robots_once_per_host():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, text="User-agent: *\nDisallow: /x\n")

    g = RobotsGuard(httpx.Client(transport=httpx.MockTransport(handler)), UA, "Тест")
    for path in ("/a", "/b", "/x"):
        g.allows(f"https://h.example{path}")
    g.allows("https://other.example/a")
    assert calls == ["https://h.example/robots.txt", "https://other.example/robots.txt"]


# ─── встроенные данные страниц ───

def test_iter_jsonld_flattens_lists_and_graph_and_skips_broken_blocks():
    page = (
        '<script type="application/ld+json">{"@type":"A"}</script>'
        '<script type="application/ld+json">[{"@type":"B"},{"@type":"C"}]</script>'
        '<script type="application/ld+json">{"@graph":[{"@type":"D"},{"@type":"E"}]}</script>'
        '<script type="application/ld+json">{сломано</script>'
        '<script type="text/javascript">var x = 1;</script>'
    )
    assert [o["@type"] for o in iter_jsonld(page)] == ["A", "B", "C", "D", "E"]
    assert list(iter_jsonld("<html>без разметки</html>")) == []


def test_next_data_returns_dict_or_none():
    assert next_data('<script id="__NEXT_DATA__" type="application/json">{"props": {"a": 1}}</script>') == {"props": {"a": 1}}
    assert next_data("<html></html>") is None
    assert next_data('<script id="__NEXT_DATA__">{оборвано</script>') is None
    assert next_data('<script id="__NEXT_DATA__">[1, 2]</script>') is None


# ─── даты ───

@pytest.mark.parametrize("value, expected", [
    ("2026-10-24T19:00:00+03:00", datetime(2026, 10, 24, 19, 0, tzinfo=MSK)),
    ("2026-10-24T16:00:00Z", datetime(2026, 10, 24, 19, 0, tzinfo=MSK)),
    ("2026-10-24 19:00:00", datetime(2026, 10, 24, 19, 0, tzinfo=MSK)),   # без пояса — московское время
    ("2026-10-24", datetime(2026, 10, 24, 0, 0, tzinfo=MSK)),
    ("2026-10-24T13:14:42+00:00", datetime(2026, 10, 24, 16, 14, 42, tzinfo=MSK)),
])
def test_parse_iso(value, expected):
    assert parse_iso(value) == expected


@pytest.mark.parametrize("value", [None, "", "   ", "завтра", 42, "2026-13-45"])
def test_parse_iso_garbage_is_none(value):
    assert parse_iso(value) is None


def test_format_span_variants():
    a = datetime(2026, 10, 24, 19, 0, tzinfo=MSK)
    assert format_span(a, None) == "2026-10-24 19:00"
    assert format_span(a, datetime(2026, 10, 24, 21, 30, tzinfo=MSK)) == "2026-10-24 19:00–21:30"
    assert format_span(a, datetime(2026, 10, 25, 5, 0, tzinfo=MSK)) == "2026-10-24 19:00 — 2026-10-25 05:00"
    assert format_span(a, datetime(2026, 12, 20, 21, 0, tzinfo=MSK)) == "период с 2026-10-24 19:00 по 2026-12-20 21:00"
    assert format_span(a, datetime(2026, 10, 24, 21, 0, tzinfo=MSK), with_time=False) == "2026-10-24"
    assert format_span(a, datetime(2026, 11, 2, 0, 0, tzinfo=MSK), with_time=False) == "период с 2026-10-24 по 2026-11-02"


def test_overlaps_treats_missing_end_as_a_moment():
    w0, w1 = datetime(2026, 10, 24, tzinfo=MSK), datetime(2026, 10, 25, tzinfo=MSK)
    assert overlaps(datetime(2026, 10, 24, 19, tzinfo=MSK), None, w0, w1)
    assert not overlaps(datetime(2026, 10, 25, 0, 0, tzinfo=MSK), None, w0, w1)          # начало ровно на конце окна
    assert not overlaps(datetime(2021, 6, 2, tzinfo=MSK), None, w0, w1)                  # бессрочная экспозиция без конца
    assert overlaps(datetime(2026, 9, 1, tzinfo=MSK), datetime(2026, 12, 1, tzinfo=MSK), w0, w1)


# ─── постраничная выкачка ───

def run_fetch(handler, urls, **kw):
    stats = PageStats()
    client = httpx.Client(transport=httpx.MockTransport(handler))
    sleeps: list[float] = []
    pages = fetch_pages(
        client, urls, guard=kw.get("guard"), headers={}, retries=1, sleep=sleeps.append, pause_sec=1.5, source="Тест",
        http_error=lambda r: f"HTTP {r.status_code}", stats=stats,
    )
    return pages, stats, sleeps


def test_fetch_pages_pauses_between_requests_and_survives_one_bad_page():
    def handler(request):
        return httpx.Response(404 if request.url.path == "/b" else 200, text=request.url.path)

    pages, stats, sleeps = run_fetch(handler, ["https://h.example/a", "https://h.example/b", "https://h.example/c"])
    assert [p[0] for p in pages] == ["https://h.example/a", "https://h.example/c"]
    assert (stats.pages, stats.failed_pages) == (2, 1)
    assert sleeps == [1.5, 1.5]  # перед второй и третьей страницей; 404 не повторяется


def test_fetch_pages_skips_what_robots_closes_and_counts_it():
    g = guard(200, "User-agent: *\nDisallow: /b\n")
    pages, stats, _ = run_fetch(lambda r: httpx.Response(200, text="ok"), ["https://h.example/a", "https://h.example/b"], guard=g)
    assert len(pages) == 1 and stats.blocked_by_robots == 1


def test_fetch_pages_all_failed_raises_with_first_reason():
    with pytest.raises(CollectorError, match="ни одна страница не получена.*HTTP 403"):
        run_fetch(lambda r: httpx.Response(403), ["https://h.example/a", "https://h.example/b"])


# ─── редирект на закрытый robots.txt адрес: запрос не отправляем, страницу не читаем ───

ROBOTS_NO_QUERY = "User-agent: *\nDisallow: /*?*\nDisallow: /private/\n"


def redirecting_site(routes: dict[str, httpx.Response]):
    """host.example: /robots.txt закрывает адреса с параметрами и /private/; routes — ответы по пути."""
    log: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        log.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS_NO_QUERY)
        return routes.get(request.url.path, httpx.Response(404))

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)  # клиент ходит по редиректам сам, если не мешать
    return client, log, RobotsGuard(client, UA, "Тест")


def fetch(client, guard, url="https://h.example/events"):
    return get_checking_robots(client, url, guard=guard, headers={}, retries=0, sleep=lambda s: None, source="Тест",
                               http_error=lambda r: f"HTTP {r.status_code}")


def test_redirect_to_a_closed_address_is_not_requested_at_all():
    """Случай Добро.ру: /events (разрешён) перенаправляет на /search?t=e… (закрыт `Disallow: /*?*`)."""
    client, log, guard = redirecting_site({
        "/events": httpx.Response(302, headers={"location": "/search?t=e&d_c=1"}),
        "/search": httpx.Response(200, text="выдача, которую читать нельзя"),
    })
    with pytest.raises(RedirectBlocked, match="закрыт robots.txt; не читаем"):
        fetch(client, guard)
    assert not any("/search" in u for u in log)               # запрос на закрытый адрес не уходил
    assert isinstance(RedirectBlocked("x"), CollectorError)   # для воркера это обычная ошибка источника


def test_redirect_to_an_allowed_address_is_followed_and_cross_host_robots_are_checked():
    client, log, guard = redirecting_site({
        "/old": httpx.Response(301, headers={"location": "https://h.example/new"}),
        "/new": httpx.Response(200, text="ok"),
        "/go-private": httpx.Response(302, headers={"location": "/private/x"}),
    })
    assert fetch(client, guard, "https://h.example/old").text == "ok"
    with pytest.raises(RedirectBlocked):
        fetch(client, guard, "https://h.example/go-private")
    assert not any("/private/x" in u for u in log)


def test_redirect_chain_is_limited_and_empty_location_is_an_error():
    client, _, guard = redirecting_site({"/a": httpx.Response(302, headers={"location": "/a"}), "/b": httpx.Response(302)})
    with pytest.raises(CollectorError, match="редиректов подряд"):
        fetch(client, guard, "https://h.example/a")
    with pytest.raises(CollectorError, match="без адреса"):
        fetch(client, guard, "https://h.example/b")


def test_fetch_pages_counts_blocked_redirect_as_closed_not_as_failure():
    client, log, guard = redirecting_site({
        "/events": httpx.Response(302, headers={"location": "/search?t=e"}),
        "/ok": httpx.Response(200, text="страница"),
    })
    stats = PageStats()
    pages = fetch_pages(client, ["https://h.example/events", "https://h.example/ok"], guard=guard, headers={}, retries=0,
                        sleep=lambda s: None, pause_sec=0, source="Тест", http_error=lambda r: str(r.status_code), stats=stats)
    assert [p[0] for p in pages] == ["https://h.example/ok"]
    assert (stats.blocked_by_robots, stats.failed_pages) == (1, 0)
    assert not any("search" in u for u in log)
