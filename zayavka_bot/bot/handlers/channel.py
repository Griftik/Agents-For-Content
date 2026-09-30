"""Посты канала: бот — админ канала, пост с тегом (#важное) предлагается Евгению к рассылке."""
from __future__ import annotations

from aiogram import Bot, Router
from aiogram.types import Message

from bot.config import get_settings
from bot.db import repo
from bot.services import broadcast

router = Router(name="channel")


@router.channel_post()
async def on_channel_post(message: Message, bot: Bot) -> None:
    s = get_settings()
    if (message.chat.username or "").lower() != s.channel_username.lower():
        return
    if not broadcast.has_tag(message.text or message.caption):
        return
    b = await repo.create_broadcast(
        "digest", message.chat.id, message.message_id,
        broadcast.post_url(message.chat.username, message.message_id), created_by=None,
    )
    await broadcast.offer_to_admins(bot, b, f"В канале вышел пост с {s.digest_tag}. Разослать его в бот?")
