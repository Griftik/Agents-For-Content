"""Команды: /digest — подборка сейчас, /plan — план на выходные, /profile — что я узнал, /help, /delete."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from leisure import settings
from leisure.api import services
from leisure.core.links import plan_share_url
from leisure.worker import messages as msg
from leisure.worker.schedules import digest_messages
from leisure.worker.send import send_with_bot

from . import texts
from .db import run_db
from .onboarding import markup

router = Router(name="commands")
NOT_READY = texts.NOT_READY
PLAN_CARDS_MAX = msg.PLAN_CARDS_MAX


def profile_text(v: dict) -> str:
    return texts.profile_text(v)


def _digest(session, user_id: int):
    p = services.get_profile(session, user_id)
    if p is None or p.onboarded_at is None:
        return None, None
    dg, _, _ = services.core_digest(session, p, services.local_today(p), now=services.utcnow())
    return p, services.digest_view(p, dg, services.decision_map(session, user_id))


@router.message(Command("digest"))
async def digest(message: Message) -> None:
    p, view = await run_db(_digest, message.from_user.id)
    if p is None:
        await message.answer(NOT_READY)
        return
    await send_with_bot(message.bot, digest_messages(p, view))


def _plan(session, user_id: int):
    p = services.get_profile(session, user_id)
    if p is None or p.onboarded_at is None:
        return None
    return services.plan(session, p, services.local_today(p))


def going_items(plan: dict) -> list[dict]:
    return [it for items in plan["days"].values() for it in items if it["status"] == "иду"] + \
           [h for h in plan.get("horizon", []) if h["status"] == "иду"]


async def send_plan(message: Message, user_id: int, offset: int = 0) -> None:
    """Обзор плана обычным текстом и карточки «Иду» (не больше шести за раз; остальные — по кнопке)."""
    plan = await run_db(_plan, user_id)
    if plan is None:
        await message.answer(NOT_READY)
        return
    items = going_items(plan)
    listed = [it for its in plan["days"].values() for it in its] + list(plan.get("horizon", []))
    if offset == 0:
        if not listed:
            await message.answer(msg.plan_empty_text(plan["title"]))
            return
        rows = []
        if services.web_links_enabled():
            rows = [[{"text": "Отправить план", "url": plan_share_url(plan["text"], settings.WEB_BASE_URL.rstrip("/"))}]]
        await message.answer(msg.plan_overview_text(plan), reply_markup=markup(rows) if rows else None)
    shown = items[offset: offset + PLAN_CARDS_MAX]
    for it in shown:
        await message.answer(msg.plan_card_text(it), reply_markup=markup(msg.plan_card_keyboard(it)))
    rest = len(items) - offset - len(shown)
    if rest > 0:
        await message.answer(f"Ещё {rest} в плане.", reply_markup=markup(
            [[{"text": f"Показать остальные ({rest})", "callback_data": f"pl:o:{offset + len(shown)}"}]]))


@router.message(Command("plan"))
async def plan(message: Message) -> None:
    await send_plan(message, message.from_user.id)


@router.callback_query(F.data == "pl:s")
async def plan_button(cb: CallbackQuery) -> None:
    """«Мой план» под заголовком подборки."""
    await cb.answer()
    await send_plan(cb.message, cb.from_user.id)


@router.callback_query(F.data.regexp(r"^pl:o:\d+$"))
async def plan_more(cb: CallbackQuery) -> None:
    await cb.answer()
    await send_plan(cb.message, cb.from_user.id, offset=int(cb.data.split(":")[2]))


def _profile(session, user_id: int):
    p = services.get_profile(session, user_id)
    if p is None or p.onboarded_at is None:
        return None
    return services.profile_view(p, services.user_decisions(session, user_id))


@router.message(Command("profile"))
async def profile(message: Message) -> None:
    v = await run_db(_profile, message.from_user.id)
    if v is None:
        await message.answer(NOT_READY)
        return
    from . import keyboards as kb
    await message.answer(texts.profile_text(v), parse_mode=ParseMode.HTML, disable_web_page_preview=True,
                         reply_markup=markup(kb.profile_keyboard()))


@router.message(Command("help"))
async def help_cmd(message: Message) -> None:
    await message.answer(texts.HELP, parse_mode=ParseMode.HTML)


DELETE_KEYBOARD = [[{"text": "Удалить всё", "callback_data": "del:yes"}, {"text": "Оставить", "callback_data": "del:no"}]]


@router.message(Command("delete"))
async def delete_cmd(message: Message) -> None:
    await message.answer(texts.DELETE_ASK, reply_markup=markup(DELETE_KEYBOARD))


@router.callback_query(F.data == "del:yes")
async def delete_yes(cb: CallbackQuery, state: FSMContext) -> None:
    removed = await run_db(services.delete_profile, cb.from_user.id)
    await state.clear()
    await cb.message.edit_text(texts.DELETE_DONE if removed else texts.DELETE_NONE)
    await cb.answer()


@router.callback_query(F.data == "del:no")
async def delete_no(cb: CallbackQuery) -> None:
    await cb.message.edit_text(texts.DELETE_KEEP)
    await cb.answer()
