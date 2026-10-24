"""Конвейер сбора: чистые шаги и сухой прогон. База и сеть не нужны: LLM, чтение и запись подменяются заглушками."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest

from leisure import settings
from leisure.collectors import pipeline
from leisure.collectors.base import CollectResult, SourceReport
from leisure.collectors.kudago import KudaGoCollector
from leisure.collectors.pipeline import (
    Item,
    PipelineReport,
    dedupe,
    has_openrouter_key,
    known_urls,
    normalize_cards,
    run_pipeline,
    unique_slugs,
)
from leisure.collectors.timepad import TimepadCollector
from leisure.normalize.llm import make_slug
from leisure.normalize.schema import EventIn, RawEvent

FIX = Path(__file__).with_name("fixtures")
KG = json.loads((FIX / "kudago_events.json").read_text(encoding="utf-8"))["pages"]
TP = json.loads((FIX / "timepad_events.json").read_text(encoding="utf-8"))["pages"]
FROM, TO = date(2026, 10, 23), date(2026, 10, 25)
NOW = datetime(2026, 10, 24, 12, 0, 0, tzinfo=timezone.utc)


def fixture_collect(city, date_from, date_to, names=None) -> CollectResult:
    """Настоящие коллекторы на фикстурах с подменой HTTP: сеть не трогаем."""
    def kudago(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /x\n")
        return httpx.Response(200, json=KG[int(request.url.params["page"]) - 1])

    def timepad(request):
        return httpx.Response(200, json=TP[0 if request.url.params["skip"] == "0" else 1])

    events, reports = [], []
    for name, col in (
        ("kudago", KudaGoCollector(httpx.Client(transport=httpx.MockTransport(kudago)), respect_robots=True, sleep=lambda s: None)),
        ("timepad", TimepadCollector(httpx.Client(transport=httpx.MockTransport(timepad)), token="t", sleep=lambda s: None)),
    ):
        if names and name not in names:
            continue
        got = col.collect(city, date_from, date_to)
        events += got
        reports.append(SourceReport(name, True, len(got)))
    return CollectResult(events, reports)


def stub_normalize(raw: RawEvent, date_from: str, date_to: str) -> EventIn:
    """Заглушка LLM: переносит поля как есть, всё остальное по умолчанию."""
    return EventIn(
        slug=make_slug(raw.title, date_from), title=raw.title, category="Театр", dates=[date.fromisoformat(date_from)],
        venue=raw.venue, address=raw.address, url=raw.url, sources=[raw.url], status="draft",
    )


def ev(title, venue="Большой театр", url="https://a.example/1", **kw) -> EventIn:
    base = dict(slug=make_slug(title, "2026-10-24"), title=title, category="Театр", dates=[date(2026, 10, 24)], venue=venue,
                url=url, sources=[url])
    return EventIn(**{**base, **kw})


def forbidden(*a, **kw):
    raise AssertionError("в сухом прогоне это не должно вызываться")


# ─── сухой прогон ───

def test_dry_run_on_fixtures_saves_raw_and_touches_nothing_else(tmp_path):
    report = run_pipeline("Москва", FROM, TO, dry_run=True, raw_dir=tmp_path, now=lambda: NOW, collect=fixture_collect,
                          normalize=forbidden, load_existing_events=forbidden, write=forbidden)
    assert report.mode.startswith("сухой прогон (--dry-run)")
    assert (report.sources["kudago"].collected, report.sources["timepad"].collected) == (6, 4)
    assert report.total_drafts == 0 and not report.db_error
    (saved,) = tmp_path.glob("raw_*.json")
    assert saved.name == "raw_2026-10-23_2026-10-25_20261024T120000.json" and str(saved) == report.raw_file
    data = json.loads(saved.read_text(encoding="utf-8"))
    assert len(data["cards"]) == 10 and {c["source"] for c in data["cards"]} == {"kudago", "timepad"}
    assert [s["source"] for s in data["sources"]] == ["kudago", "timepad"]
    text = report.render()
    assert "источник" in text and "ИТОГО" in text and "kudago" in text and "сырые карточки:" in text


def test_missing_openrouter_key_falls_back_to_dry_run(tmp_path):
    report = run_pipeline("Москва", FROM, TO, raw_dir=tmp_path, collect=fixture_collect, key_present=lambda: False,
                          normalize=forbidden, load_existing_events=forbidden, write=forbidden)
    assert "нет OPENROUTER_KEY" in report.mode and len(list(tmp_path.glob("raw_*.json"))) == 1


def test_has_openrouter_key_follows_settings(monkeypatch):
    monkeypatch.delenv("OPENROUTER_KEY", raising=False)
    monkeypatch.setattr(settings, "_opt", lambda name, default="": "")
    assert has_openrouter_key() is False
    monkeypatch.setattr(settings, "_opt", lambda name, default="": "sk-test")
    assert has_openrouter_key() is True


def test_silent_source_is_visible_in_summary(tmp_path):
    def collect(*a, **kw):
        return CollectResult(fixture_collect(a[0], a[1], a[2], ["kudago"]).events,
                             [SourceReport("kudago", True, 6), SourceReport("timepad", False, error="Timepad: нужен токен API")])
    report = run_pipeline("Москва", FROM, TO, dry_run=True, raw_dir=tmp_path, collect=collect)
    assert report.sources["timepad"].error == "Timepad: нужен токен API"
    assert "источник «timepad» молчит: Timepad: нужен токен API" in report.render()


# ─── боевой путь на заглушках ───

def test_full_run_with_stubs_creates_drafts(tmp_path):
    written: list[EventIn] = []
    report = run_pipeline("Москва", FROM, TO, raw_dir=tmp_path, collect=fixture_collect, normalize=stub_normalize,
                          key_present=lambda: True, load_existing_events=lambda *a: [],
                          write=lambda evs: written.extend(evs) or (len(evs), 0))
    # 10 карточек, но «Лекция «Город и память»» есть и в KudaGo, и в Timepad (у Timepad площадка не указана):
    # дедупликация оставляет полнее заполненную KudaGo-карточку и переносит в неё ссылку Timepad
    assert len(written) == 9 and all(e.status == "draft" for e in written)
    assert len({e.slug for e in written}) == 9                        # slug уникальны
    assert (report.sources["kudago"].drafts, report.sources["timepad"].drafts) == (6, 3)
    assert (report.sources["kudago"].duplicates, report.sources["timepad"].duplicates) == (0, 1)
    lecture = next(e for e in written if "Город и память" in e.title)
    assert sorted(u.split("/")[2] for u in lecture.sources) == ["kudago.com", "lektorij.timepad.ru"]
    assert report.mode == "боевой" and not report.db_error


def test_url_already_in_db_is_not_sent_to_llm(tmp_path):
    existing = [{"slug": "old", "title": "Старое", "url": "http://kudago.com/msk/event/koncert-dyujmovochka/", "sources": [],
                 "venue": "", "city": "Москва", "dates": ["2026-10-24"]}]
    calls = []
    def counting(raw, a, b):
        calls.append(raw.url)
        return stub_normalize(raw, a, b)
    report = run_pipeline("Москва", FROM, TO, raw_dir=tmp_path, collect=fixture_collect, normalize=counting,
                          key_present=lambda: True, load_existing_events=lambda *a: existing, write=lambda e: (len(e), 0))
    assert "http://kudago.com/msk/event/koncert-dyujmovochka/" not in calls and len(calls) == 9
    assert report.sources["kudago"].known_in_db == 1


def test_db_failures_are_reported_not_raised(tmp_path):
    def broken_read(*a):
        raise ConnectionError("нет базы")
    r = run_pipeline("Москва", FROM, TO, raw_dir=tmp_path, collect=fixture_collect, normalize=forbidden, key_present=lambda: True,
                     load_existing_events=broken_read, write=forbidden)
    assert "не удалось прочитать события из базы: ConnectionError" in r.db_error

    def broken_write(evs):
        raise RuntimeError("диск")
    r = run_pipeline("Москва", FROM, TO, raw_dir=tmp_path, collect=fixture_collect, normalize=stub_normalize, key_present=lambda: True,
                     load_existing_events=lambda *a: [], write=broken_write)
    assert "RuntimeError: диск" in r.db_error and r.total_drafts == 0 and "ОШИБКА записи в базу" in r.render()


def test_normalization_errors_are_counted_and_do_not_stop_the_rest():
    report = PipelineReport("Москва", FROM, TO, "боевой")
    cards = [RawEvent(source="kudago", url=f"https://k.example/{i}", title=f"Событие {i}") for i in range(4)]
    def flaky(raw, a, b):
        if raw.title in ("Событие 1", "Событие 3"):
            raise ValueError("не JSON")
        return stub_normalize(raw, a, b)
    items = normalize_cards(cards, flaky, FROM, TO, report)
    assert [i.event.title for i in items] == ["Событие 0", "Событие 2"]
    st = report.sources["kudago"]
    assert st.norm_errors == 2 and st.first_norm_error == "ValueError: не JSON"


def test_max_cards_caps_llm_calls():
    report = PipelineReport("Москва", FROM, TO, "боевой")
    cards = [RawEvent(source="kudago", url=f"https://k.example/{i}", title=f"Событие {i}") for i in range(5)]
    assert len(normalize_cards(cards, stub_normalize, FROM, TO, report, max_cards=2)) == 2


# ─── дедупликация ───

def test_duplicates_among_new_keep_the_best_and_merge_sources():
    poor = Item(ev("спектакль «Дюймовочка»", "Дом музыки", "http://kudago.com/msk/event/a/"), "kudago")
    rich = Item(ev("Дюймовочка", "Дом музыки", "https://tp.example/e/1", address="Космодамианская наб., 52", price_text="от 500 ₽",
                   confidence="подтверждено"), "timepad")
    other = Item(ev("Лекция о дзене", "Культурный центр", "https://tp.example/e/2"), "timepad")
    report = PipelineReport("Москва", FROM, TO, "боевой")
    out = dedupe([poor, rich, other], [], report)
    assert [i.event.title for i in out] == ["Дюймовочка", "Лекция о дзене"]
    assert out[0].event.sources == ["https://tp.example/e/1", "http://kudago.com/msk/event/a/"]   # ссылки обеих карточек сохранены
    assert report.sources["kudago"].duplicates == 1 and "timepad" not in report.sources


def test_new_events_matching_db_events_are_dropped_both_draft_and_published():
    existing = [
        {"slug": "x1", "title": "Щелкунчик", "venue": "Большой театр", "city": "Москва", "dates": ["2026-10-24"], "status": "published"},
        {"slug": "x2", "title": "Лекция о дзене", "venue": "Культурный центр", "city": "Москва", "dates": ["2026-10-25"], "status": "draft"},
    ]
    new = [Item(ev("«Щелкунчик»"), "kudago"), Item(ev("Лекция о дзене", "Культурный центр", dates=[date(2026, 10, 25)]), "timepad"),
           Item(ev("Совсем другое", "Другая площадка"), "timepad")]
    report = PipelineReport("Москва", FROM, TO, "боевой")
    out = dedupe(new, existing, report)
    assert [i.event.title for i in out] == ["Совсем другое"]
    assert report.sources["kudago"].duplicates == 1 and report.sources["timepad"].duplicates == 1


def test_same_event_on_another_day_is_not_a_duplicate_of_db():
    existing = [{"slug": "x1", "title": "Щелкунчик", "venue": "Большой театр", "city": "Москва", "dates": ["2026-10-31"]}]
    out = dedupe([Item(ev("Щелкунчик"), "kudago")], existing, PipelineReport("Москва", FROM, TO, "боевой"))
    assert len(out) == 1


def test_unique_slugs():
    a, b = Item(ev("Один и тот же"), "kudago"), Item(ev("Один и тот же", "Другая"), "timepad")
    out = unique_slugs([a, b], taken={"zzz"})
    assert out[0].event.slug != out[1].event.slug and out[1].event.slug.endswith("-2")
    taken_out = unique_slugs([a], taken={a.event.slug})
    assert taken_out[0].event.slug == f"{a.event.slug}-2"


def test_known_urls_collects_url_and_sources():
    assert known_urls([{"url": "u1", "sources": ["s1", "s2"]}, {"url": "", "sources": None}]) == {"u1", "s1", "s2"}


# ─── CLI ───

def test_cli_dry_run_prints_summary_and_exits_zero(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(pipeline, "collect_all", fixture_collect)
    rc = pipeline.main(["--city", "Москва", "--days", "3", "--start", "2026-10-23", "--sources", "kudago,timepad",
                        "--dry-run", "--raw-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0 and "2026-10-23 — 2026-10-25" in out and "kudago" in out and "timepad" in out and "ИТОГО" in out
    assert len(list(tmp_path.glob("raw_*.json"))) == 1


def test_cli_exit_code_one_when_every_source_is_silent(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(pipeline, "collect_all", lambda *a, **kw: CollectResult([], [SourceReport("kudago", False, error="403")]))
    assert pipeline.main(["--dry-run", "--raw-dir", str(tmp_path), "--sources", "kudago"]) == 1
    assert "молчит: 403" in capsys.readouterr().out


def test_cli_rejects_unknown_source_and_bad_days(tmp_path):
    with pytest.raises(SystemExit) as e1:
        pipeline.main(["--sources", "nonexistent", "--dry-run"])
    with pytest.raises(SystemExit) as e2:
        pipeline.main(["--days", "0", "--dry-run"])
    assert e1.value.code == 2 and e2.value.code == 2


def test_pipeline_module_is_not_registered_as_a_source():
    from leisure.collectors import load_collectors
    assert "pipeline" not in load_collectors() and "_common" not in load_collectors()
