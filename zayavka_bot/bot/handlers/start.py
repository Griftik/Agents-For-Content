"""/start с deep link: источник, кружок, приветствие с кнопкой мини-приложения (п. 3.1–3.2).

Сама заявка, согласие, меню и подписка — в мини-приложении (bot/webapp).
"""
from __future__ import annotations

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message

from bot.content import get_content
from bot.db import repo
from bot.keyboards import kb
from bot.services import deeplink, flow, leadflow

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, bot: Bot) -> None:
    c = get_content()
    tg = message.from_user
    assert tg is not None
    source, ref = deeplink.parse(command.args)
    u, _ = await repo.upsert_user(tg.id, tg.username, tg.first_name, source, ref)
    await repo.log_event(tg.id, "start", arg=command.args or "")

    stage = u.stage
    q = flow.stage_question(stage)
    if q:
        await message.answer(c.t("resume", n=flow.question_number(c, q)), reply_markup=kb.open_app(c.t("resume_button")))
    elif stage in (flow.STAGE_CONTACT, flow.STAGE_COMPANY):
        await message.answer(c.t("resume", n=len(c.order)), reply_markup=kb.open_app(c.t("resume_button")))
    elif stage in (flow.STAGE_DONE, flow.STAGE_TRAINING):
        await message.answer(c.t("already_done"), reply_markup=kb.open_app(c.t("menu_open_button")))
    else:
        await repo.set_stage(tg.id, flow.STAGE_WELCOME)
        await leadflow.send_welcome(bot, tg.id)


@router.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    c = get_content()
    tg = message.from_user
    assert tg is not None
    await repo.upsert_user(tg.id, tg.username, tg.first_name)
    await message.answer(c.t("already_done"), reply_markup=kb.open_app(c.t("menu_open_button")))
