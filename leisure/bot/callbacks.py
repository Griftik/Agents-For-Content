"""Формат callback_data кнопок Telegram — общий для воркера (отправка) и бота (обработка). Лимит Telegram — 64 байта."""
from __future__ import annotations

from datetime import date
from typing import NamedTuple

STATUS_CODES = {"иду": "g", "может": "m", "интересно": "i", "мимо": "s", "пропуск": "p"}
CODES_STATUS = {v: k for k, v in STATUS_CODES.items()}
REASON_CODES = {"не моё": "1", "дорого": "2", "далеко": "3", "уже был": "4", "не в это время": "5", "не та компания": "6"}
CODES_REASON = {v: k for k, v in REASON_CODES.items()}


def decision_cb(status: str, event_id: str, day: str | None = None) -> str:
    """d:<код>:<uuid>[:<YYYY-MM-DD>] — день с карточки (51 байт при uuid), чтобы решение легло на показанный день."""
    base = f"d:{STATUS_CODES[status]}:{event_id}"
    return f"{base}:{day}" if day else base


def reason_cb(reason: str, event_id: str) -> str:
    return f"r:{REASON_CODES[reason]}:{event_id}"


def more_reasons_cb(event_id: str) -> str:
    return f"r:m:{event_id}"


def day_cb(n: int, event_id: str) -> str:
    """y:<n>:<uuid> — выбор дня уикенда у многодневного события: 0 — пятница, 1 — суббота, 2 — воскресенье."""
    return f"y:{int(n)}:{event_id}"


def rating_cb(stars: int, event_id: str) -> str:
    return f"s:{int(stars)}:{event_id}"


class Parsed(NamedTuple):
    kind: str            # 'decision' | 'reason' | 'more_reasons' | 'lowreason' | 'lowmore' | 'day' | 'rating'
    value: str
    event_id: str
    day: date | None = None


def parse_cb(data: str) -> Parsed | None:
    """Parsed(kind, значение, event_id, день) или None, если это не наша кнопка. День — только у решений, необязателен."""
    parts = data.split(":")
    if len(parts) not in (3, 4):
        return None
    kind, val, event_id = parts[:3]
    day = None
    if len(parts) == 4:
        if kind != "d":
            return None
        try:
            day = date.fromisoformat(parts[3])
        except ValueError:
            return None
    if kind == "d" and val in CODES_STATUS:
        return Parsed("decision", CODES_STATUS[val], event_id, day)
    if kind == "r" and val in CODES_REASON:
        return Parsed("reason", CODES_REASON[val], event_id)
    if kind == "r" and val == "0":
        return Parsed("reason", "", event_id)            # «Без причины» из старых сообщений
    if kind == "r" and val == "m":
        return Parsed("more_reasons", "", event_id)
    if kind == "rl" and val in CODES_REASON:                 # причина низкой оценки (1–2), статус решения не меняется
        return Parsed("lowreason", CODES_REASON[val], event_id)
    if kind == "rl" and val == "m":
        return Parsed("lowmore", "", event_id)
    if kind == "y" and val in ("0", "1", "2"):
        return Parsed("day", val, event_id)
    if kind == "s" and val.isdigit() and 1 <= int(val) <= 5:
        return Parsed("rating", val, event_id)
    return None
