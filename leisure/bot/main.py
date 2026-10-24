"""Telegram-бот планировщика (aiogram 3). Запуск: python -m leisure.bot.main

Хранилище FSM — память процесса (MVP на одном инстансе); для нескольких инстансов — RedisStorage на REDIS_URL.
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from leisure import settings

from leisure.api import services

from . import commands, decisions, fallback, onboarding


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(onboarding.router)
    dp.include_router(decisions.router)
    dp.include_router(commands.router)
    dp.include_router(fallback.router)  # последним: любой неопознанный callback получает ответ
    return dp


async def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    services.warn_local_web_url()
    bot = Bot(settings.bot_token(), default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await bot.set_my_commands([
        BotCommand(command="digest", description="Подборка на выходные"),
        BotCommand(command="plan", description="Мой план"),
        BotCommand(command="profile", description="Что я о тебе знаю"),
        BotCommand(command="reset", description="Настроить заново"),
        BotCommand(command="delete", description="Удалить мои данные"),
        BotCommand(command="help", description="Помощь"),
    ])
    await build_dispatcher().start_polling(bot, allowed_updates=["message", "callback_query"])


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
