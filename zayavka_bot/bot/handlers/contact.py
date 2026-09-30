"""Контакт с согласием и название компании (п. 3.4)."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from bot.content import get_content
from bot.db import repo
from bot.services import flow, leadflow
from bot.services.cards import normalize_phone

router = Router(name="contact")


class StageIs(BaseFilter):
    """Фильтр: текущий этап пользователя. Именно BaseFilter — иначе aiogram не дождётся корутины."""

    def __init__(self, *stages: str) -> None:
        self.stages = stages

    async def __call__(self, message: Message) -> bool:
        if not message.from_user:
            return False
        u = await repo.get_user(message.from_user.id)
        return bool(u and u.stage in self.stages)


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
        await leadflow.ask_company(bot, tg.id)
    elif u.stage in (flow.STAGE_DONE, flow.STAGE_COMPANY):
        # телефон пришёл после разбора (повторная просьба) — сообщаем Евгению
        await leadflow.remove_reply_keyboard(bot, tg.id)
        if u.stage == flow.STAGE_DONE:
            await message.answer(c.t("text_forwarded"))
            await leadflow.send_admin_card(bot, tg.id, header="Лид оставил телефон после разбора")


@router.message(F.text, StageIs(flow.STAGE_CONTACT))
async def on_contact_stage_text(message: Message, bot: Bot) -> None:
    c = get_content()
    uid = message.from_user.id  # type: ignore[union-attr]
    if (message.text or "").strip() == c.t("contact_later_button"):
        await repo.log_event(uid, "contact_skipped", reason="button")
        await leadflow.ask_company(bot, uid)
    else:
        # текст вместо кнопки: телефон текстом не берём (нет согласия), напоминаем про кнопку
        await leadflow.ask_contact(bot, uid, with_later=True)


@router.message(F.text, StageIs(flow.STAGE_COMPANY))
async def on_company(message: Message, bot: Bot) -> None:
    uid = message.from_user.id  # type: ignore[union-attr]
    text = (message.text or "").strip()
    if text.startswith("/"):
        return
    await repo.update_lead(uid, company=text[:256])
    await leadflow.finalize(bot, uid)


@router.callback_query(F.data == "company:skip")
async def cb_company_skip(cb: CallbackQuery, bot: Bot) -> None:
    await cb.answer()
    u = await repo.get_user(cb.from_user.id)
    if u is None or u.stage != flow.STAGE_COMPANY:
        return
    if isinstance(cb.message, Message):
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:  # noqa: BLE001
            pass
    await leadflow.finalize(bot, u.id)
