"""Логи в JSON (или текстом), телефоны маскируются в любом сообщении (п. 13)."""
from __future__ import annotations

import json
import logging
import sys

from bot.services.cards import mask_phones_in


class MaskPhonesFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        masked = mask_phones_in(msg)
        if masked != msg:
            record.msg, record.args = masked, None
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            data["exc"] = mask_phones_in(self.formatException(record.exc_info))
        return json.dumps(data, ensure_ascii=False)


def setup_logging(level: str = "INFO", as_json: bool = True) -> None:
    h = logging.StreamHandler(sys.stdout)
    h.addFilter(MaskPhonesFilter())
    h.setFormatter(JsonFormatter() if as_json else logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [h]
    root.setLevel(level)
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
