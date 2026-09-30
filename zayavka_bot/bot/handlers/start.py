"""/start с deep link, приветствие, продолжение и перезапуск заявки (п. 3.1–3.2)."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message

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
        n = flow.question_number(c, q)
        await message.answer(c.t("resume", n=n), reply_markup=kb.resume(c))
    elif stage == flow.STAGE_CONTACT:
        await leadflow.ask_contact(bot, tg.id, with_later=True)
    elif stage == flow.STAGE_COMPANY:
        await leadflow.ask_company(bot, tg.id)
    elif stage in (flow.STAGE_DONE, flow.STAGE_TRAINING):
        lead = await repo.get_lead(tg.id)
        await message.answer(
            c.t("already_done"),
            reply_markup=kb.menu(c, u.nurture_enabled, bool(lead and lead.report_path)),
        )
    else:
        await repo.set_stage(tg.id, flow.STAGE_WELCOME)
        await leadflow.send_welcome(bot, tg.id)


async def begin(bot: Bot, user_id: int, edit: Message | None = None) -> None:
    """Начать заявку с первого вопроса. Старые ответы стираются (заявка заново)."""
    c = get_content()
    await repo.delete_answers(user_id)
    await repo.cancel_jobs(user_id, ["contact_timeout", *leadflow.HOT_REMINDERS])
    await repo.log_event(user_id, "app_started")
    await leadflow.show_question(bot, user_id, c.order[0], edit=edit)


@router.callback_query(F.data == "app:start")
async def cb_start(cb: CallbackQuery, bot: Bot) -> None:
    await cb.answer()
    u = await repo.get_user(cb.from_user.id)
    if u is None:
        u, _ = await repo.upsert_user(cb.from_user.id, cb.from_user.username, cb.from_user.first_name)
    q = flow.stage_question(u.stage)
    if q:  # уже в процессе — старая кнопка приветствия не сбрасывает ответы
        await leadflow.show_question(bot, u.id, q)
        return
    # кнопку приветствия не редактируем: под ней может быть кружок, а текст приветствия полезно оставить
    await begin(bot, u.id)


@router.callback_query(F.data == "app:resume")
async def cb_resume(cb: CallbackQuery, bot: Bot) -> None:
    await cb.answer()
    u = await repo.get_user(cb.from_user.id)
    q = flow.stage_question(u.stage if u else None)
    if q:
        await leadflow.show_question(bot, cb.from_user.id, q, edit=cb.message if isinstance(cb.message, Message) else None)
    else:
        await begin(bot, cb.from_user.id)


@router.callback_query(F.data == "app:restart")
async def cb_restart(cb: CallbackQuery, bot: Bot) -> None:
    await cb.answer()
    await begin(bot, cb.from_user.id, edit=cb.message if isinstance(cb.message, Message) else None)
