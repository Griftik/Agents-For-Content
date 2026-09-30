"""Рассылки вместо серии по расписанию.

digest — важный пост канала: бот видит пост с тегом (или Евгений пересылает пост боту),
         присылает Евгению превью, рассылка уходит после одного нажатия.
news   — материал аналитики для платных подписчиков: /news и следующее сообщение.

Каждому получателю уходит копия сообщения; под постом канала — «Читать в канале» и запись
на разбор. Темп — ~20 сообщений в секунду (лимит Telegram 30), паузы по RetryAfter.
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardButton as IB, InlineKeyboardMarkup

from bot.config import get_settings
from bot.content import get_content
from bot.db import repo
from bot.db.models import Broadcast
from bot.services import notify

log = logging.getLogger(__name__)
PAUSE_SEC = 0.05

AUDIENCE_LABELS = {"all": "Всем в боте", "leads": "Только лидам", "subs": "Подписчикам"}


def has_tag(text: str | None) -> bool:
    tag = get_settings().digest_tag.strip().lower()
    return bool(tag) and tag in (text or "").lower()


def post_url(chat_username: str | None, message_id: int | None) -> str | None:
    return f"https://t.me/{chat_username}/{message_id}" if chat_username and message_id else None


def recipient_markup(b: Broadcast) -> InlineKeyboardMarkup | None:
    if b.kind != "digest":
        return None
    c = get_content()
    rows = []
    if b.post_url:
        rows.append([IB(text=c.t("digest_channel_button"), url=b.post_url)])
    rows.append([IB(text=c.t("warm_button"), callback_data="book")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def offer_to_admins(bot: Bot, b: Broadcast, header: str) -> None:
    """Превью рассылки каждому админу с кнопками выбора аудитории."""
    kinds = ["subs"] if b.kind == "news" else ["all", "leads"]
    rows = []
    for k in kinds:
        n = len(await repo.audience(k))
        rows.append([IB(text=f"{AUDIENCE_LABELS[k]} ({n})", callback_data=f"bc:{b.id}:{k}")])
    rows.append([IB(text="Не рассылать", callback_data=f"bc:{b.id}:no")])
    markup = InlineKeyboardMarkup(inline_keyboard=rows)
    for admin_id in get_settings().admin_ids:
        try:
            await bot.copy_message(admin_id, b.from_chat_id, b.message_id, reply_markup=recipient_markup(b))
            await bot.send_message(admin_id, header, reply_markup=markup)
        except Exception as e:  # noqa: BLE001
            log.warning("превью рассылки админу %s не ушло: %s", admin_id, e)


async def run(bot: Bot, bid: int, audience_kind: str, report_to: int) -> tuple[int, int]:
    """Разослать. Вызывается после claim_broadcast; итог — админу в report_to."""
    b = await repo.get_broadcast(bid)
    assert b is not None
    users = await repo.audience(audience_kind)
    markup = recipient_markup(b)
    sent = failed = 0
    for uid in users:
        ok = await _send_one(bot, b, uid, markup)
        sent, failed = sent + ok, failed + (not ok)
        await asyncio.sleep(PAUSE_SEC)
    await repo.finish_broadcast(bid, "sent", sent, failed)
    await repo.log_event(None, f"{b.kind}_broadcast", id=bid, audience=audience_kind, sent=sent, failed=failed)
    try:
        await bot.send_message(report_to, f"Рассылка №{bid} готова: доставлено {sent}, не доставлено {failed}.")
    except Exception:  # noqa: BLE001
        pass
    return sent, failed


async def _send_one(bot: Bot, b: Broadcast, uid: int, markup) -> bool:
    for attempt in range(2):
        try:
            await bot.copy_message(uid, b.from_chat_id, b.message_id, reply_markup=markup)
            await repo.log_event(uid, f"{b.kind}_sent", id=b.id)
            return True
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
        except TelegramForbiddenError:
            # человек заблокировал бота — больше не пишем
            await repo.set_nurture(uid, False)
            await repo.log_event(uid, "blocked")
            return False
        except Exception as e:  # noqa: BLE001
            log.warning("рассылка %s → %s: %s", b.id, uid, e)
            return False
    return False


def start_in_background(bot: Bot, bid: int, audience_kind: str, report_to: int) -> asyncio.Task:
    async def _job() -> None:
        try:
            await run(bot, bid, audience_kind, report_to)
        except Exception as e:  # noqa: BLE001
            log.exception("рассылка %s упала", bid)
            await repo.finish_broadcast(bid, "failed")
            await notify.to_admins(bot, f"Рассылка №{bid} прервалась: {e}")

    return asyncio.create_task(_job(), name=f"broadcast-{bid}")
