"""Конвейер подхватывает новые коллекторы (mosbilet, afisha, club16tons, telegram): сухой прогон и боевой путь на заглушках.
Источники — настоящие классы на ЖИВЫХ снимках ответов (fixtures/collectors_live_snapshots.json), HTTP подменён, сети нет."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

import httpx
import pytest

from leisure.collectors import base, load_collectors
from leisure.collectors.afisha import AfishaCollector
from leisure.collectors.club16tons import Club16TonsCollector
from leisure.collectors.mosbilet import MosbiletCollector
from leisure.collectors.pipeline import run_pipeline
from leisure.collectors.telegram import TelegramCollector
from leisure.normalize.llm import make_slug
from leisure.normalize.schema import EventIn, RawEvent
from leisure.tests import test_collectors_afisha as t_afisha
from leisure.tests import test_collectors_club16tons as t_16tons
from leisure.tests import test_collectors_mosbilet as t_mosbilet
from leisure.tests import test_collectors_telegram as t_tg

FROM, TO = date(2026, 10, 24), date(2026, 10, 31)
NOW = datetime(2026, 10, 24, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def registry(monkeypatch):
    class Mos(MosbiletCollector):
        def __init__(self):
            super().__init__(httpx.Client(transport=httpx.MockTransport(t_mosbilet.FakeSite())), pages=t_mosbilet.LIVE_PAGES, sleep=lambda s: None)

    class Afisha(AfishaCollector):
        def __init__(self):
            super().__init__(httpx.Client(transport=httpx.MockTransport(t_afisha.FakeSite())), pages=t_afisha.LIVE_PAGES, sleep=lambda s: None)

    class Tons(Club16TonsCollector):
        def __init__(self):
            client, _ = t_16tons.site()
            super().__init__(client, sleep=lambda s: None)

    class Tg(TelegramCollector):
        def __init__(self):
            super().__init__(httpx.Client(transport=httpx.MockTransport(t_tg.FakeTelegram())), channels=t_tg.CHANNELS, enabled=True, sleep=lambda s: None)

    reg = {"mosbilet": Mos, "afisha": Afisha, "club16tons": Tons, "telegram": Tg}
    monkeypatch.setattr(base, "REGISTRY", reg)
    return reg


def forbidden(*a, **kw):
    raise AssertionError("в сухом прогоне это не должно вызываться")


def stub_normalize(raw: RawEvent, date_from: str, date_to: str) -> EventIn:
    return EventIn(slug=make_slug(raw.title, date_from), title=raw.title, category="Концерты", dates=[date.fromisoformat(date_from)],
                   venue=raw.venue, address=raw.address, url=raw.url, sources=[raw.url], status="draft")


def test_dry_run_collects_all_four_and_summarises_each(registry, tmp_path):
    report = run_pipeline("Москва", FROM, TO, dry_run=True, raw_dir=tmp_path, now=lambda: NOW,
                          normalize=forbidden, load_existing_events=forbidden, write=forbidden)
    got = {name: s.collected for name, s in report.sources.items()}
    assert got == {"mosbilet": 43, "afisha": 31, "club16tons": 17, "telegram": 35}      # недельное окно 24–31.10 на живых снимках
    assert all(not s.error for s in report.sources.values())
    (saved,) = tmp_path.glob("raw_*.json")
    data = json.loads(saved.read_text(encoding="utf-8"))
    assert {c["source"] for c in data["cards"]} == set(got)
    assert all(c["url"].startswith("https://") for c in data["cards"])        # ссылка на первоисточник есть у каждой карточки
    assert sum(1 for r in data["sources"] if r["ok"]) == 4


def test_full_run_with_stubs_writes_drafts_for_every_source(registry, tmp_path):
    written: list[EventIn] = []
    report = run_pipeline("Москва", FROM, TO, raw_dir=tmp_path, now=lambda: NOW, normalize=stub_normalize, key_present=lambda: True,
                          load_existing_events=lambda *a: [], write=lambda evs: written.extend(evs) or (len(evs), 0))
    assert written and all(e.status == "draft" and e.url and e.sources for e in written)
    assert len({e.slug for e in written}) == len(written)
    assert all(report.sources[name].drafts > 0 for name in registry)
    assert not report.db_error


def test_all_four_are_discovered_by_load_collectors():
    loaded = load_collectors()
    assert {"mosbilet", "afisha", "club16tons", "telegram"} <= set(loaded)
