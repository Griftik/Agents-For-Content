"""/delete_me, запись по ссылке, «Что дальше» под разбором, всё вне сценария (п. 3.10)."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.config import get_settings
from bot.content import get_content
from bot.db import repo
from bot.keyboards import kb
from bot.services import crm, leadflow, notify

router = Router(name="common")
fallback_router = Router(name="fallback")  # подключается последним


def _msg(cb: CallbackQuery) -> Message | None:
    return cb.message if isinstance(cb.message, Message) else None


@router.message(Command("delete_me"))
async def cmd_delete(message: Message) -> None:
    c = get_content()
    await message.answer(c.t("delete_confirm"), reply_markup=kb.yes_no(c, "del"))


@router.callback_query(F.data.startswith("del:"))
async def cb_delete(cb: CallbackQuery, bot: Bot) -> None:
    c = get_content()
    await cb.answer()
    if (m := _msg(cb)) is not None:
        try:
            await m.edit_reply_markup(reply_markup=None)
        except Exception:  # noqa: BLE001
            pass
    if cb.data != "del:yes":
        return
    uid = cb.from_user.id
    await repo.forget_user(uid)
    await repo.log_event(uid, "deleted")
    crm.push(uid)  # строка в таблице тоже очищается
    await leadflow.remove_reply_keyboard(bot, uid)
    await bot.send_message(uid, c.t("delete_done"))
    await notify.to_admins(bot, f"Пользователь {uid} удалил свои данные (/delete_me).")


@router.callback_query(F.data == "book")
async def cb_book(cb: CallbackQuery, bot: Bot) -> None:
    await cb.answer()
    await leadflow.send_booking_link(bot, cb.from_user.id)


@router.callback_query(F.data == "next")
async def cb_next(cb: CallbackQuery, bot: Bot) -> None:
    """«Что дальше» под разбором — ветка сегмента."""
    c = get_content()
    await cb.answer()
    uid = cb.from_user.id
    await repo.log_event(uid, "report_next_clicked")
    lead = await repo.get_lead(uid)
    seg = lead.segment if lead else None
    if seg == "hot":
        # hot_offer уже был до разбора — теперь сразу ссылка на запись
        await leadflow.send_booking_link(bot, uid)
    elif seg == "warm":
        await bot.send_message(uid, c.t("warm_intro"), reply_markup=kb.book(c.t("warm_button")))
    elif seg == "warm_initiator":
        await bot.send_message(uid, c.t("initiator_intro"), reply_markup=kb.book(c.t("warm_button")))
    else:
        await bot.send_message(uid, c.t("already_done"), reply_markup=kb.open_app(c.t("menu_open_button")))


@fallback_router.message()
async def on_anything(message: Message, bot: Bot) -> None:
    """Любое сообщение вне сценария — Евгению с карточкой, пользователю — text_forwarded."""
    tg = message.from_user
    if tg is None or message.chat.type != "private":
        return
    c = get_content()
    await repo.upsert_user(tg.id, tg.username, tg.first_name)
    await repo.cancel_jobs(tg.id, leadflow.HOT_REMINDERS)  # написал сам — дальше лично
    await repo.log_event(tg.id, "text_received")
    lead = await repo.get_lead(tg.id)
    if lead and lead.segment:
        await leadflow.send_admin_card(bot, tg.id, header="Сообщение от лида ↓")
    else:
        who = f"@{tg.username}" if tg.username else f"tg://user?id={tg.id}"
        await notify.to_admins(bot, f"Сообщение от {tg.first_name or ''} ({who}, id {tg.id}), заявка не заполнена ↓")
    for admin_id in get_settings().admin_ids:
        try:
            await message.forward(admin_id)
        except Exception:  # noqa: BLE001
            pass
    await message.answer(c.t("text_forwarded"))
