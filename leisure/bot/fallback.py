"""Запасной роутер: подключается последним, ловит то, что не взял никто."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from . import texts

log = logging.getLogger("leisure.bot.fallback")
router = Router(name="fallback")


@router.callback_query()
async def unknown_callback(cb: CallbackQuery) -> None:
    """Неизвестная кнопка (старая версия бота, чужой формат): снимаем индикатор загрузки и говорим, что экран устарел."""
    log.info("неизвестный callback %r у %s", cb.data, cb.from_user.id)
    await cb.answer(texts.STALE)


@router.message(F.text.startswith("/"))
async def unknown_command(message: Message) -> None:
    await message.answer(texts.UNKNOWN_COMMAND)
