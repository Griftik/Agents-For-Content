"""Сообщения всем админам (ADMIN_IDS). Сбой доставки одному админу не мешает остальным."""
from __future__ import annotations

import logging
import time
from typing import Any

from aiogram import Bot

from bot.config import get_settings

log = logging.getLogger(__name__)
_last_alert: dict[str, float] = {}


async def to_admins(bot: Bot, text: str, **kw: Any) -> None:
    for admin_id in get_settings().admin_ids:
        try:
            await bot.send_message(admin_id, text, **kw)
        except Exception as e:  # noqa: BLE001
            log.warning("admin %s: не доставлено: %s", admin_id, e)


async def alert(bot: Bot, key: str, text: str, every_sec: int = 3600) -> None:
    """Техническое предупреждение админу, не чаще раза в every_sec по одному ключу."""
    now = time.monotonic()
    if now - _last_alert.get(key, -every_sec - 1) < every_sec:
        return
    _last_alert[key] = now
    await to_admins(bot, f"⚠️ {text}")
