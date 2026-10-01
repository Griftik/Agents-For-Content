"""Телефон. В мини-приложении кнопка «Поделиться телефоном» (WebApp.requestContact) присылает
контакт в чат обычным сообщением — здесь он сохраняется, а приложение подхватывает его.
После разбора без телефона бот один раз просит его кнопкой в чате — тоже сюда."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.types import Message

from bot.content import get_content
from bot.db import repo
from bot.services import flow, leadflow
from bot.services.cards import normalize_phone

router = Router(name="contact")


@router.message(F.contact)
async def on_contact(message: Message, bot: Bot) -> None:
    c = get_content()
    tg, contact = message.from_user, message.contact
    assert tg is not None and contact is not None
    if contact.user_id != tg.id:
        # чужой контакт из записной книжки — просим свой кнопкой
        await leadflow.ask_contact(bot, tg.id, with_later=False)
        return
    u = await repo.get_user(tg.id)
    if u is None:
        return
    await leadflow.save_contact(bot, tg.id, normalize_phone(contact.phone_number))
    if u.stage == flow.STAGE_CONTACT:
        await repo.set_stage(tg.id, flow.STAGE_COMPANY)  # дальше — экран компании в приложении
    elif u.stage == flow.STAGE_DONE:
        # телефон после разбора (повторная просьба в чате) — сообщаем Евгению
        await leadflow.remove_reply_keyboard(bot, tg.id)
        await message.answer(c.t("text_forwarded"))
        await leadflow.send_admin_card(bot, tg.id, header="Лид оставил телефон после разбора")
