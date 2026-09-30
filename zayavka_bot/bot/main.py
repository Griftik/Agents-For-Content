"""Точка входа: миграции → бот → планировщик → CRM-синк → long polling (или webhook)."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

from bot.config import get_settings
from bot.content import get_content
from bot.db.migrate import upgrade_head
from bot.db.session import init_engine
from bot.handlers import admin, application, channel, common, contact, start, subscription
from bot.logging_setup import setup_logging
from bot.services import crm, scheduler

log = logging.getLogger("bot")


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    # порядок важен: админ → команды → заявка → контакт → всё остальное
    dp.include_routers(channel.router, admin.router, subscription.router, start.router, common.router,
                       application.router, contact.router, common.fallback_router)
    return dp


async def set_commands(bot: Bot) -> None:
    s = get_settings()
    await bot.set_my_commands(
        [BotCommand(command="start", description="Заявка на разбор"),
         BotCommand(command="menu", description="Меню"),
         BotCommand(command="subscribe", description="Бизнес-аналитика по подписке"),
         BotCommand(command="delete_me", description="Удалить мои данные")],
        scope=BotCommandScopeDefault(),
    )
    for admin_id in s.admin_ids:
        try:
            await bot.set_my_commands(
                [BotCommand(command="send", description="Отправить разбор: /send <user_id>"),
                 BotCommand(command="stats", description="Воронка: /stats 7"),
                 BotCommand(command="news", description="Новость подписчикам"),
                 BotCommand(command="reload", description="Перечитать content/"),
                 BotCommand(command="cancel", description="Отменить /send или /news"),
                 BotCommand(command="menu", description="Меню пользователя"),
                 BotCommand(command="help", description="Команды админа")],
                scope=BotCommandScopeChat(chat_id=admin_id),
            )
        except Exception as e:  # noqa: BLE001 — админ ещё не писал боту
            log.warning("команды для админа %s не установлены: %s", admin_id, e)


def check_settings() -> None:
    s = get_settings()
    for name, val in [("ADMIN_IDS", s.admin_ids), ("BOOKING_URL", s.booking_url), ("PRIVACY_URL", s.privacy_url), ("CONSENT_URL", s.consent_url),
                      ("OFFER_URL", s.offer_url)]:
        if not val:
            log.warning("TODO(Евгений): не задан %s в .env", name)


async def run() -> None:
    s = get_settings()
    init_engine(s.database_url)
    get_content()  # упасть сразу, если YAML невалиден
    bot = Bot(s.bot_token)
    dp = build_dispatcher()
    syncer = crm.init(bot)
    syncer.start()
    sched = asyncio.create_task(scheduler.run(bot), name="scheduler")
    try:
        me = await bot.get_me()
        await set_commands(bot)
        log.info("бот @%s запущен, CRM_SYNC=%s", me.username, s.crm_sync.value)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        sched.cancel()
        await syncer.stop()
        await bot.session.close()


def main() -> None:
    s = get_settings()
    setup_logging(s.log_level, s.log_json)
    (s.content_dir.parent / "storage").mkdir(exist_ok=True)
    check_settings()
    upgrade_head(s.database_url)  # до event loop: alembic env сам запускает asyncio.run
    asyncio.run(run())


if __name__ == "__main__":
    main()
