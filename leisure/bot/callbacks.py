"""Формат callback_data кнопок Telegram — общий для воркера (отправка) и бота (обработка). Лимит Telegram — 64 байта."""
from __future__ import annotations

STATUS_CODES = {"иду": "g", "может": "m", "интересно": "i", "мимо": "s", "пропуск": "p"}
CODES_STATUS = {v: k for k, v in STATUS_CODES.items()}
REASON_CODES = {"не моё": "1", "дорого": "2", "далеко": "3", "уже был": "4", "не в это время": "5", "не та компания": "6"}
CODES_REASON = {v: k for k, v in REASON_CODES.items()}


def decision_cb(status: str, event_id: str) -> str:
    return f"d:{STATUS_CODES[status]}:{event_id}"


def reason_cb(reason: str, event_id: str) -> str:
    return f"r:{REASON_CODES[reason]}:{event_id}"


def rating_cb(stars: int, event_id: str) -> str:
    return f"s:{int(stars)}:{event_id}"


def parse_cb(data: str) -> tuple[str, str, str] | None:
    """('decision'|'reason'|'rating', значение, event_id) или None, если это не наша кнопка."""
    parts = data.split(":", 2)
    if len(parts) != 3:
        return None
    kind, val, event_id = parts
    if kind == "d" and val in CODES_STATUS:
        return "decision", CODES_STATUS[val], event_id
    if kind == "r" and val in CODES_REASON:
        return "reason", CODES_REASON[val], event_id
    if kind == "s" and val.isdigit() and 1 <= int(val) <= 5:
        return "rating", val, event_id
    return None
