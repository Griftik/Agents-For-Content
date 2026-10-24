"""Конвейер сбора (п. 7 спеки): коллекторы → LLM-нормализация → дедупликация → черновики в базе.

    python -m leisure.collectors.pipeline --city Москва --days 14 [--sources kudago,timepad] [--dry-run]

Шаги:
  1. `collect_all` по зарегистрированным источникам; молчащий источник не мешает остальным и виден в сводке.
  2. Сырые карточки всегда сохраняются в leisure/data/raw/*.json (можно нормализовать позже, не ходя в сеть).
  3. Нормализация каждой карточки через `normalize.llm.normalize_raw` (статус всегда draft). Карточки, чей адрес уже
     есть у событий в базе, в LLM не отправляем (экономим деньги). Сбой одной карточки не останавливает остальные.
  4. Дедупликация (`normalize.dedup`): новые между собой (остаётся лучшая, ссылки склеиваются в `sources`) и против
     событий из базы за тот же диапазон, и draft, и published. Событие из базы всегда побеждает: куратор мог его править.
  5. Новые события пишутся в базу черновиками через `seed.load.upsert_events`.
  6. Сводка в лог и в stdout: по источникам собрано, уже в базе, ошибок нормализации, дубликатов, черновиков.

`--dry-run` (и автоматически, если нет OPENROUTER_KEY): только шаги 1–2, без LLM и без базы; конвейер не падает.
Код выхода: 0 — отработал (источники могли молчать, это видно в сводке); 1 — не записалось в базу или молчат все источники.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from leisure import settings
from leisure.normalize.dedup import find_duplicates, pick_best
from leisure.normalize.llm import normalize_raw
from leisure.normalize.schema import EventIn, RawEvent

from . import load_collectors
from ._common import MSK
from .base import REGISTRY, CollectResult, collect_all

log = logging.getLogger("leisure.collectors.pipeline")

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"


# ─── структуры ───

@dataclass
class Item:
    """Нормализованное событие с именем источника: у EventIn источника как поля нет, а в сводке он нужен."""

    event: EventIn
    source: str


@dataclass
class SourceStats:
    collected: int = 0
    known_in_db: int = 0       # адрес карточки уже есть у события в базе
    norm_errors: int = 0
    duplicates: int = 0        # отброшено как дубликат (среди новых или против базы)
    drafts: int = 0            # создано черновиков
    error: str = ""            # источник молчит: причина
    first_norm_error: str = ""


@dataclass
class PipelineReport:
    city: str
    date_from: date
    date_to: date
    mode: str                  # «боевой» или «сухой прогон (...)»
    sources: dict[str, SourceStats] = field(default_factory=dict)
    raw_file: str = ""
    db_error: str = ""

    def stats(self, source: str) -> SourceStats:
        return self.sources.setdefault(source, SourceStats())

    @property
    def total_drafts(self) -> int:
        return sum(s.drafts for s in self.sources.values())

    def render(self) -> str:
        head = f"Сбор: {self.city}, {self.date_from} — {self.date_to}; режим: {self.mode}"
        cols = ("источник", "собрано", "уже в базе", "ошибок LLM", "дубликатов", "черновиков")
        rows = [(name, s.collected, s.known_in_db, s.norm_errors, s.duplicates, s.drafts) for name, s in self.sources.items()]
        total = ("ИТОГО", *(sum(r[i] for r in rows) for i in range(1, 6)))
        width = [max(len(str(x)) for x in col) for col in zip(cols, *rows, total)]
        line = lambda r: "  ".join(str(x).ljust(w) if i == 0 else str(x).rjust(w) for i, (x, w) in enumerate(zip(r, width)))  # noqa: E731
        out = [head, line(cols), *(line(r) for r in rows), line(total)]
        for name, s in self.sources.items():
            if s.error:
                out.append(f"источник «{name}» молчит: {s.error}")
            if s.first_norm_error:
                out.append(f"источник «{name}», пример ошибки нормализации: {s.first_norm_error}")
        if self.raw_file:
            out.append(f"сырые карточки: {self.raw_file}")
        if self.db_error:
            out.append(f"ОШИБКА записи в базу: {self.db_error}")
        return "\n".join(out)


# ─── чистые шаги ───

def save_raw(cards: Sequence[RawEvent], result: CollectResult, report: PipelineReport, raw_dir: Path, now: datetime) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"raw_{report.date_from}_{report.date_to}_{now:%Y%m%dT%H%M%S}.json"
    payload = {
        "city": report.city, "date_from": report.date_from.isoformat(), "date_to": report.date_to.isoformat(),
        "saved_at": now.isoformat(timespec="seconds"),
        "sources": [{"source": r.source, "ok": r.ok, "count": r.count, "error": r.error, "stats": r.stats}
                    for r in result.sources],
        "cards": [c.model_dump() for c in cards],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path


def known_urls(existing: Sequence[dict]) -> set[str]:
    out: set[str] = set()
    for e in existing:
        if e.get("url"):
            out.add(str(e["url"]))
        out.update(str(u) for u in e.get("sources") or [])
    return out


def normalize_cards(
    cards: Sequence[RawEvent], normalize: Callable[..., EventIn], date_from: date, date_to: date,
    report: PipelineReport, skip_urls: set[str] | None = None, max_cards: int | None = None,
) -> list[Item]:
    """Каждая карточка отдельно: сбой LLM или невалидный ответ считается в сводке, остальные идут дальше."""
    items: list[Item] = []
    sent = 0
    for raw in cards:
        st = report.stats(raw.source)
        if skip_urls and raw.url in skip_urls:
            st.known_in_db += 1
            continue
        if max_cards is not None and sent >= max_cards:
            continue
        sent += 1
        try:
            items.append(Item(normalize(raw, date_from.isoformat(), date_to.isoformat()), raw.source))
        except Exception as exc:  # noqa: BLE001 — HTTP, не JSON, ValidationError: карточка пропускается, конвейер живёт
            st.norm_errors += 1
            st.first_norm_error = st.first_norm_error or f"{type(exc).__name__}: {str(exc)[:200]}"
            log.warning("нормализация «%s» (%s) не удалась: %s", raw.title[:60], raw.source, type(exc).__name__)
    return items


def dedupe(items: list[Item], existing: Sequence[dict], report: PipelineReport) -> list[Item]:
    """1) среди новых оставляем лучшего, ссылки отброшенных переходят в его `sources`;
    2) всё, что совпало с событием из базы, отбрасываем (база побеждает)."""
    items = list(items)
    events = [it.event for it in items]
    dropped: set[int] = set()
    for group in find_duplicates(events):
        best = pick_best(events, group)
        others = [i for i in group if i != best]
        sources = list(dict.fromkeys([*events[best].sources, *(u for i in others for u in events[i].sources)]))
        items[best] = Item(events[best].model_copy(update={"sources": sources}), items[best].source)
        for i in others:
            dropped.add(i)
            report.stats(items[i].source).duplicates += 1
    survivors = [it for i, it in enumerate(items) if i not in dropped]
    if existing and survivors:
        combined = [*existing, *(it.event for it in survivors)]
        n_old = len(existing)
        clash = {i - n_old for g in find_duplicates(combined) if any(j < n_old for j in g) for i in g if i >= n_old}
        for i in clash:
            report.stats(survivors[i].source).duplicates += 1
        survivors = [it for i, it in enumerate(survivors) if i not in clash]
    return survivors


def unique_slugs(items: list[Item], taken: set[str]) -> list[Item]:
    """Два разных события не должны делить slug: upsert по slug перезаписал бы первое вторым."""
    taken = set(taken)
    out = []
    for it in items:
        slug, n = it.event.slug, 1
        while slug in taken:
            n += 1
            slug = f"{it.event.slug}-{n}"
        taken.add(slug)
        out.append(it if slug == it.event.slug else Item(it.event.model_copy(update={"slug": slug}), it.source))
    return out


def overlaps(event: dict, date_from: date, date_to: date) -> bool:
    for d in event.get("dates") or []:
        try:
            if date_from <= date.fromisoformat(str(d)[:10]) <= date_to:
                return True
        except ValueError:
            continue
    return False


# ─── база (ленивые импорты: сухой прогон и тесты чистых шагов базу не трогают) ───

def load_existing(city: str, date_from: date, date_to: date) -> list[dict]:
    """События города за диапазон: published через сервисный слой, draft добавлены здесь отдельным чтением, потому что
    `upcoming_events` отдаёт только published, а черновики нужны, чтобы повторный запуск не плодил дубли."""
    from sqlalchemy import select

    from leisure.api.services import upcoming_events
    from leisure.db.models import Event
    from leisure.db.session import session_factory

    with session_factory()() as s:
        published = upcoming_events(s, city, date_from)
        drafts = [r.as_core() for r in s.scalars(select(Event).where(Event.status == "draft", Event.city == city))]
    return [e for e in [*published, *drafts] if overlaps(e, date_from, date_to)]


def write_drafts(events: Sequence[EventIn]) -> tuple[int, int]:
    from leisure.db.session import session_factory
    from leisure.seed.load import upsert_events

    with session_factory()() as s:
        # status не передаём: у новых событий уже draft, а чужой slug не должен сбросить статус, выставленный куратором
        return upsert_events(s, [e.model_dump() for e in events])


# ─── конвейер ───

def has_openrouter_key() -> bool:
    try:
        settings.openrouter_key()
    except RuntimeError:
        return False
    return True


def run_pipeline(
    city: str, date_from: date, date_to: date, *, names: list[str] | None = None, dry_run: bool = False,
    max_cards: int | None = None, raw_dir: Path = RAW_DIR, now: Callable[[], datetime] | None = None,
    collect: Callable[..., CollectResult] | None = None, normalize: Callable[..., EventIn] = normalize_raw,
    load_existing_events: Callable[..., list[dict]] | None = None, write: Callable[[Sequence[EventIn]], tuple[int, int]] | None = None,
    key_present: Callable[[], bool] = has_openrouter_key,
) -> PipelineReport:
    """Зависимости передаются аргументами только для тестов и подмены сети; CLI использует настоящие."""
    clock = now or (lambda: datetime.now(timezone.utc))
    collect = collect or collect_all
    load_existing_events = load_existing_events or load_existing
    write = write or write_drafts

    mode = "боевой"
    if dry_run:
        mode = "сухой прогон (--dry-run): без LLM и без базы"
    elif not key_present():
        dry_run, mode = True, "сухой прогон (нет OPENROUTER_KEY): без LLM и без базы"
        log.warning("OPENROUTER_KEY не задан, нормализация пропущена, карточки только сохраняются")
    report = PipelineReport(city, date_from, date_to, mode)

    result = collect(city, date_from, date_to, names)
    for r in result.sources:
        st = report.stats(r.source)
        st.collected, st.error = r.count, ("" if r.ok else r.error)
    report.raw_file = str(save_raw(result.events, result, report, raw_dir, clock()))

    if not dry_run:
        try:
            existing = load_existing_events(city, date_from, date_to)
        except Exception as exc:  # noqa: BLE001 — без базы дедуплицировать нечем: лучше не писать ничего
            report.db_error = f"не удалось прочитать события из базы: {type(exc).__name__}: {exc}"
            log.error(report.db_error)
            return report
        items = normalize_cards(result.events, normalize, date_from, date_to, report, known_urls(existing), max_cards)
        items = unique_slugs(dedupe(items, existing, report), {e.get("slug", "") for e in existing})
        if items:
            try:
                write([it.event for it in items])
            except Exception as exc:  # noqa: BLE001
                report.db_error = f"{type(exc).__name__}: {exc}"
                log.error("запись в базу не удалась: %s", report.db_error)
                return report
            for it in items:
                report.stats(it.source).drafts += 1
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Сбор событий: коллекторы → LLM → дедупликация → черновики в базе")
    ap.add_argument("--city", default=settings.DEFAULT_CITY)
    ap.add_argument("--days", type=int, default=14, help="сколько дней вперёд, считая сегодня (по умолчанию 14)")
    ap.add_argument("--start", type=date.fromisoformat, default=None, help="первый день диапазона, YYYY-MM-DD (по умолчанию сегодня, МСК)")
    ap.add_argument("--sources", default="", help="имена через запятую, например kudago,timepad (по умолчанию все)")
    ap.add_argument("--dry-run", action="store_true", help="только собрать и сохранить сырые карточки: без LLM и без базы")
    ap.add_argument("--max-cards", type=int, default=None, help="потолок карточек для LLM за запуск (защита от расходов)")
    ap.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    args = ap.parse_args(argv)
    if args.days < 1:
        ap.error("--days должно быть не меньше 1")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_collectors()
    names = [n.strip() for n in args.sources.split(",") if n.strip()] or None
    unknown = [n for n in names or [] if n not in REGISTRY]
    if unknown:
        ap.error(f"неизвестные источники: {', '.join(unknown)}; есть: {', '.join(sorted(REGISTRY))}")
    date_from = args.start or datetime.now(MSK).date()
    date_to = date_from + timedelta(days=args.days - 1)

    report = run_pipeline(args.city, date_from, date_to, names=names, dry_run=args.dry_run,
                          max_cards=args.max_cards, raw_dir=args.raw_dir)
    text = report.render()
    log.info("сводка:\n%s", text)
    print(text)
    all_silent = bool(report.sources) and all(s.error for s in report.sources.values())
    return 1 if report.db_error or all_silent else 0


if __name__ == "__main__":
    sys.exit(main())
