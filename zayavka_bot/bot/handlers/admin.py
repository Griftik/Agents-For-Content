"""Админ-команды MVP (п. 11, раздел 16): /send, /stats, /reload, /cancel, кнопки карточки."""
from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import BaseFilter, Command, CommandObject
from aiogram.types import CallbackQuery, Message

from bot.config import get_settings
from bot.content import ContentError, get_content, reload_content
from bot.db import repo
from bot.db.models import utcnow
from bot.services import analytics, broadcast, crm, leadflow

log = logging.getLogger(__name__)
router = Router(name="admin")

# admin_id → user_id, кому уйдёт следующее сообщение админа как разбор.
# В памяти: после рестарта достаточно повторить /send.
pending_send: dict[int, int] = {}
# админы, от которых ждём текст бизнес-аналитику после /news
pending_news: set[int] = set()


class IsAdmin(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        return bool(event.from_user and event.from_user.id in get_settings().admin_ids)


router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

def help_text() -> str:
    return (
        "Команды админа:\n"
        "/send <user_id> — следующее сообщение (файл или текст) уйдёт пользователю как разбор\n"
        "/send <user_id> <текст> — отправить текст как разбор сразу\n"
        "/cancel — отменить /send или /news\n"
        "Перешлите сюда пост канала — предложу разослать его в бот (или отметьте пост тегом "
        f"{get_settings().digest_tag} в канале, когда бот — админ канала)\n"
        "/news — следующее сообщение уйдёт платным подписчикам бизнес-аналитики\n"
        "/stats [7|30] — воронка и точка отвала по вопросам\n"
        "/reload — перечитать YAML из content/ без рестарта\n"
        "Промт для разбора — prompts/report_system.md (вставьте карточку лида в блок «ОТВЕТЫ»)."
    )


@router.message(Command("admin", "help"))
async def cmd_help(message: Message) -> None:
    await message.answer(help_text())


async def _check_target(message: Message, uid: int) -> bool:
    u = await repo.get_user(uid)
    if u is None or u.deleted_at is not None:
        await message.answer(f"Пользователь {uid} не найден или удалил данные.")
        return False
    return True


@router.message(Command("send"))
async def cmd_send(message: Message, command: CommandObject, bot: Bot) -> None:
    args = (command.args or "").strip()
    head, _, rest = args.partition(" ")
    if not head.isdigit():
        await message.answer("Формат: /send <user_id> [текст]. user_id — в карточке лида.")
        return
    uid = int(head)
    if not await _check_target(message, uid):
        return
    if rest.strip():
        await _deliver(message, bot, uid, text=rest.strip())
        return
    pending_send[message.from_user.id] = uid  # type: ignore[union-attr]
    await message.answer(f"Жду разбор для {uid}: пришлите файл или текст следующим сообщением. /cancel — отмена.")


@router.message(Command("cancel"))
async def cmd_cancel(message: Message) -> None:
    aid = message.from_user.id  # type: ignore[union-attr]
    had = pending_send.pop(aid, None) is not None or aid in pending_news
    pending_news.discard(aid)
    await message.answer("Отменено." if had else "Нечего отменять.")


@router.message(Command("news"))
async def cmd_news(message: Message) -> None:
    pending_news.add(message.from_user.id)  # type: ignore[union-attr]
    pending_send.pop(message.from_user.id, None)  # type: ignore[union-attr]
    n = len(await repo.audience("subs"))
    await message.answer(f"Пришлите материал следующим сообщением (текст, фото, файл). "
                         f"Покажу превью перед отправкой. Подписчиков сейчас: {n}. /cancel — отмена.")


class HasPendingSend(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        return bool(message.from_user and message.from_user.id in pending_send
                    and not (message.text or "").startswith("/"))


@router.message(HasPendingSend())
async def on_pending_report(message: Message, bot: Bot) -> None:
    uid = pending_send.pop(message.from_user.id)  # type: ignore[union-attr]
    await _deliver(message, bot, uid, from_chat_id=message.chat.id, message_id=message.message_id)


class HasPendingNews(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        return bool(message.from_user and message.from_user.id in pending_news
                    and not (message.text or "").startswith("/"))


@router.message(HasPendingNews())
async def on_pending_news(message: Message, bot: Bot) -> None:
    pending_news.discard(message.from_user.id)  # type: ignore[union-attr]
    b = await repo.create_broadcast("news", message.chat.id, message.message_id, None, message.from_user.id)  # type: ignore[union-attr]
    await broadcast.offer_to_admins(bot, b, "Материал аналитики для подписчиков. Отправить?")


@router.message(F.forward_origin.type == "channel")
async def on_forwarded_post(message: Message, bot: Bot) -> None:
    """Евгений переслал пост канала — предложить разослать как важное."""
    origin = message.forward_origin
    url = broadcast.post_url(getattr(origin.chat, "username", None), getattr(origin, "message_id", None))  # type: ignore[union-attr]
    b = await repo.create_broadcast("digest", message.chat.id, message.message_id, url, message.from_user.id)  # type: ignore[union-attr]
    await broadcast.offer_to_admins(bot, b, "Разослать этот пост в бот?")


@router.callback_query(F.data.startswith("bc:"))
async def cb_broadcast(cb: CallbackQuery, bot: Bot) -> None:
    _, bid_s, aud = (cb.data or "").split(":", 2)
    bid = int(bid_s)
    msg = cb.message if isinstance(cb.message, Message) else None
    if aud == "no":
        b = await repo.get_broadcast(bid)
        if b and b.status == "draft":
            await repo.finish_broadcast(bid, "cancelled")
        await cb.answer("Не рассылаем")
        if msg:
            await msg.edit_text("Рассылка отменена.", reply_markup=None)
        return
    if not await repo.claim_broadcast(bid, aud):
        await cb.answer("Эта рассылка уже запущена или отменена", show_alert=True)
        return
    n = len(await repo.audience(aud))
    await cb.answer("Запускаю")
    if msg:
        await msg.edit_text(f"Рассылаю: {broadcast.AUDIENCE_LABELS.get(aud, aud)}, {n} чел. Итог пришлю.",
                            reply_markup=None)
    broadcast.start_in_background(bot, bid, aud, report_to=cb.from_user.id)


async def _deliver(message: Message, bot: Bot, uid: int, **kw) -> None:
    try:
        await leadflow.deliver_report(bot, uid, **kw)
    except Exception as e:  # noqa: BLE001
        log.exception("разбор для %s не доставлен", uid)
        await message.answer(f"Не доставлено пользователю {uid}: {e}")
        return
    await message.answer(f"Разбор доставлен пользователю {uid}.")


@router.callback_query(F.data.startswith("adm:"))
async def cb_admin(cb: CallbackQuery) -> None:
    _, action, uid_s = (cb.data or "").split(":", 2)
    uid = int(uid_s)
    if action == "contacted":
        await repo.update_lead(uid, contacted_at=utcnow(), status="contacted")
        await repo.cancel_jobs(uid, leadflow.HOT_REMINDERS)
        await repo.log_event(uid, "contacted", by=cb.from_user.id)
        crm.push(uid)
        await cb.answer("Отмечено: связался")
    elif action == "send":
        pending_send[cb.from_user.id] = uid
        await cb.answer()
        if isinstance(cb.message, Message):
            await cb.message.answer(
                f"Жду разбор для {uid}: пришлите файл или текст следующим сообщением. /cancel — отмена."
            )
    else:
        await cb.answer()


@router.message(Command("stats"))
async def cmd_stats(message: Message, command: CommandObject) -> None:
    arg = (command.args or "").strip()
    days = int(arg) if arg.isdigit() and int(arg) > 0 else 7
    await message.answer(await analytics.stats_text(get_content(), days))


@router.message(Command("reload"))
async def cmd_reload(message: Message) -> None:
    try:
        c = reload_content(get_settings().content_dir)
    except ContentError as e:
        await message.answer(f"YAML не принят, работает прежняя версия:\n{e}")
        return
    except Exception as e:  # noqa: BLE001 — синтаксис YAML и т.п.
        await message.answer(f"YAML не прочитан, работает прежняя версия:\n{e}")
        return
    await message.answer(f"Перечитал content/: {len(c.questions)} вопросов, тексты, тизеры, скоринг, маппинг.")
