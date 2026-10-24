"""Отправка сообщений в Telegram через aiogram. Без токена — только логирование (режим разработки)."""
from __future__ import annotations

import asyncio
import logging

from leisure import settings

log = logging.getLogger("leisure.worker.send")
SEND_INTERVAL = 1 / 25  # лимит Telegram ~30 сообщений/с на бота; держим 25


def _markup(rows):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(**b) for b in row] for row in rows])


async def send_with_bot(bot, messages: list[tuple[int, str, list | None]]) -> int:
    """Отправить через готовый экземпляр aiogram.Bot (из бота или воркера). Возвращает число отправленных.

    Ошибка у одного пользователя не валит рассылку; блокировка бота пользователем — просто пропуск.
    """
    from aiogram.enums import ParseMode
    from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

    sent = 0
    for uid, text, rows in messages:
        for _attempt in range(3):
            try:
                await bot.send_message(uid, text, parse_mode=ParseMode.HTML, reply_markup=_markup(rows) if rows else None,
                                       disable_web_page_preview=True)
                sent += 1
                break
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 0.5)
            except TelegramForbiddenError:
                log.info("пользователь %s заблокировал бота", uid)
                break
            except Exception:  # noqa: BLE001
                log.exception("не отправилось пользователю %s", uid)
                break
        await asyncio.sleep(SEND_INTERVAL)
    return sent


async def send_messages(messages: list[tuple[int, str, list | None]]) -> int:
    """[(user_id, html_text, keyboard_rows|None)] → число отправленных. Без токена — только лог."""
    try:
        token = settings.bot_token()
    except RuntimeError:
        log.warning("LEISURE_BOT_TOKEN не задан — %d сообщений не отправлены (режим разработки)", len(messages))
        for uid, text, _ in messages[:3]:
            log.info("[dry-run → %s] %s", uid, text.replace("\n", " | ")[:200])
        return 0
    from aiogram import Bot

    bot = Bot(token)
    try:
        return await send_with_bot(bot, messages)
    finally:
        await bot.session.close()


def send_sync(messages: list[tuple[int, str, list | None]]) -> int:
    return asyncio.run(send_messages(messages))
