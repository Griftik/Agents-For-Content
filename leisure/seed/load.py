"""Загрузка seed-событий в БД (upsert по slug).

    python -m leisure.seed.load                       # leisure/seed/events_2026-10-23.json
    python -m leisure.seed.load path/to/events.json --status draft

Повторный запуск обновляет поля существующих событий и не трогает решения пользователей (они ссылаются на id).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from leisure.db.models import Event
from leisure.db.session import session_factory
from leisure.normalize.schema import EventIn

DEFAULT_FILE = Path(__file__).with_name("events_2026-10-23.json")


def upsert_events(session: Session, items: list[dict], status: str | None = None) -> tuple[int, int]:
    created = updated = 0
    existing = {e.slug: e for e in session.scalars(select(Event).where(Event.slug.in_([i["slug"] for i in items])))}
    for raw in items:
        ev = EventIn.model_validate(raw)
        data = ev.model_dump()
        data.pop("organizer_id", None)
        rating = data.pop("rating")
        data["rating"] = rating if rating else None
        if status:
            data["status"] = status
        obj = existing.get(ev.slug)
        if obj is None:
            session.add(Event(**data))
            created += 1
        else:
            for k, v in data.items():
                setattr(obj, k, v)
            updated += 1
    session.commit()
    return created, updated


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Загрузить события из JSON в БД")
    ap.add_argument("file", nargs="?", default=str(DEFAULT_FILE))
    ap.add_argument("--status", choices=["draft", "published", "archived"], default=None,
                    help="принудительный статус для всех событий (по умолчанию — из файла)")
    args = ap.parse_args(argv)
    items = json.loads(Path(args.file).read_text(encoding="utf-8"))
    with session_factory()() as s:
        created, updated = upsert_events(s, items, args.status)
    print(f"создано {created}, обновлено {updated} (файл {args.file})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
