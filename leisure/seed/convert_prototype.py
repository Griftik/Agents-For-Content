"""Конвертер массива EVENTS из прототипа «Уикенд в Москве» в формат seed (модель Event, п. 6.1 спеки).

Использован один раз для events_2026-10-23.json; оставлен для воспроизводимости:
    python -I leisure/seed/convert_prototype.py <events_from_prototype.json> leisure/seed/events_2026-10-23.json
Переименования: id → slug, time → time_text, why_fit → why_fit_hint; review_snippet → rating.review;
служебное поле fit прототипа отбрасывается. Все события публикуются (status = published), город — Москва.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from leisure.normalize.schema import EventIn  # noqa: E402


def convert(raw: dict) -> dict:
    rating = raw.get("rating") or None
    review = (raw.get("review_snippet") or "").strip()
    if review:
        rating = {**(rating or {}), "review": review}
    return {
        "slug": raw["id"],
        "title": raw["title"],
        "category": raw["category"],
        "subcategory": raw.get("subcategory") or "",
        "kind": raw.get("kind") or "событие",
        "city": "Москва",
        "dates": raw.get("dates") or [],
        "time_text": raw.get("time") or "",
        "duration_min": raw.get("duration_min"),
        "venue": raw.get("venue") or "",
        "address": raw.get("address") or "",
        "metro": raw.get("metro") or "",
        "price_from": raw.get("price_from"),
        "price_text": raw.get("price_text") or "",
        "description": raw.get("description") or "",
        "why_fit_hint": raw.get("why_fit") or "",
        "note": raw.get("note") or "",
        "tags": raw.get("tags") or [],
        "aesthetics": raw.get("aesthetics") or 3,
        "novelty": raw.get("novelty") or 3,
        "crowd": raw.get("crowd") or "камерно",
        "audience_30plus": bool(raw.get("audience_30plus")),
        "audience_kids": bool(raw.get("audience_kids", False)),
        "url": raw.get("url") or "",
        "sources": raw.get("sources") or [],
        "rating": rating,
        "confidence": raw.get("confidence") or "вероятно",
        "status": "published",
    }


def main(src: str, dst: str) -> None:
    raw = json.load(open(src, encoding="utf-8"))
    out = []
    for r in raw:
        ev = EventIn.model_validate(convert(r))
        d = ev.model_dump(mode="json")
        out.append(d)
    Path(dst).write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(out)} событий → {dst}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
