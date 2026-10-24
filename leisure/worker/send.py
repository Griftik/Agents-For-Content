"""Отправка сообщений в Telegram через aiogram. Без токена — только логирование (режим разработки)."""
from __future__ import annotations

import asyncio
import logging
from typing import NamedTuple

from leisure import settings

log = logging.getLogger("leisure.worker.send")
SEND_INTERVAL = 1 / 25  # лимит Telegram ~30 сообщений/с на бота; держим 25
RETRY_DELAYS = (1, 2, 4)  # секунды между повторами при 5xx и сетевых ошибках
RETRY_AFTER_MAX = 3       # сколько раз ждём 429 на одно сообщение


class SendResult(NamedTuple):
    sent: int                # сколько сообщений ушло
    undelivered: list[int]   # индексы недоставленных сообщений в исходном списке
    blocked: list[int]       # user_id, заблокировавших бота (отправку им прекратили)


def _markup(rows):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(**b) for b in row] for row in rows])


async def send_with_bot(bot, messages: list[tuple[int, str, list | None]]) -> SendResult:
    """Отправить через готовый экземпляр aiogram.Bot (из бота или воркера).

    429 ждём по retry_after; 5xx и сетевые ошибки повторяем до трёх раз с паузой 1, 2, 4 с. Заблокировавшему бота
    остальные сообщения не шлём — user_id попадает в blocked, вызывающий отключает рассылки. Ошибка у одного
    пользователя не валит рассылку остальным.
    """
    from aiogram.enums import ParseMode
    from aiogram.exceptions import TelegramForbiddenError, TelegramNetworkError, TelegramRetryAfter, TelegramServerError

    sent = 0
    undelivered: list[int] = []
    blocked: list[int] = []
    for i, (uid, text, rows) in enumerate(messages):
        if uid in blocked:
            undelivered.append(i)
            continue
        delivered, retries, waits = False, 0, 0
        while True:
            try:
                await bot.send_message(uid, text, parse_mode=ParseMode.HTML, reply_markup=_markup(rows) if rows else None,
                                       disable_web_page_preview=True)
                delivered = True
                break
            except TelegramRetryAfter as e:
                waits += 1
                if waits > RETRY_AFTER_MAX:
                    log.warning("пользователь %s: Telegram просит подождать, сдаюсь после %d ожиданий", uid, RETRY_AFTER_MAX)
                    break
                await asyncio.sleep(e.retry_after + 0.5)
            except TelegramForbiddenError:
                log.info("пользователь %s заблокировал бота", uid)
                blocked.append(uid)
                break
            except (TelegramServerError, TelegramNetworkError, asyncio.TimeoutError) as e:
                if retries >= len(RETRY_DELAYS):
                    log.warning("пользователь %s: сообщение %d не доставлено после %d повторов: %s", uid, i, retries, e)
                    break
                await asyncio.sleep(RETRY_DELAYS[retries])
                retries += 1
            except Exception:  # noqa: BLE001
                log.exception("не отправилось пользователю %s", uid)
                break
        if delivered:
            sent += 1
        else:
            undelivered.append(i)
        await asyncio.sleep(SEND_INTERVAL)
    return SendResult(sent, undelivered, blocked)


async def send_messages(messages: list[tuple[int, str, list | None]]) -> SendResult:
    """[(user_id, html_text, keyboard_rows|None)] → SendResult. Без токена — только лог, ничего не доставлено."""
    try:
        token = settings.bot_token()
    except RuntimeError:
        log.warning("LEISURE_BOT_TOKEN не задан — %d сообщений не отправлены (режим разработки)", len(messages))
        for uid, text, _ in messages[:3]:
            log.info("[dry-run → %s] %s", uid, text.replace("\n", " | ")[:200])
        return SendResult(0, list(range(len(messages))), [])
    from aiogram import Bot

    bot = Bot(token)
    try:
        return await send_with_bot(bot, messages)
    finally:
        await bot.session.close()


def send_sync(messages: list[tuple[int, str, list | None]]) -> SendResult:
    return asyncio.run(send_messages(messages))
