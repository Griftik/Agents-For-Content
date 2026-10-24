"""Запасной роутер: подключается последним, ловит то, что не взял никто."""
from __future__ import annotations

import logging

from aiogram import Router
from aiogram.types import CallbackQuery

log = logging.getLogger("leisure.bot.fallback")
router = Router(name="fallback")


@router.callback_query()
async def unknown_callback(cb: CallbackQuery) -> None:
    """Неизвестная кнопка (старая версия бота, чужой формат): молча снимаем индикатор загрузки."""
    log.info("неизвестный callback %r у %s", cb.data, cb.from_user.id)
    await cb.answer()
