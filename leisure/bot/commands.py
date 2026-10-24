"""Команды: /digest — подборка сейчас, /plan — план на выходные, /profile — что я узнал, /help."""
from __future__ import annotations

from html import escape

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from leisure import settings
from leisure.api import services
from leisure.core.catalog import VALUES
from leisure.worker.messages import plan_item_keyboard
from leisure.worker.schedules import digest_messages
from leisure.worker.send import send_with_bot

from .db import run_db
from .onboarding import markup

router = Router(name="commands")
NOT_READY = "Сначала короткая настройка: /start"


def _digest(session, user_id: int):
    p = services.get_profile(session, user_id)
    if p is None or p.onboarded_at is None:
        return None, None
    dg, _, _ = services.core_digest(session, p, services.local_today(p), now=services.utcnow())
    return p, services.digest_view(p, dg)


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


@router.message(Command("plan"))
async def plan(message: Message) -> None:
    plan = await run_db(_plan, message.from_user.id)
    if plan is None:
        await message.answer(NOT_READY)
        return
    going = [it for items in plan["days"].values() for it in items if it["status"] == "иду"]
    if not going and not plan["horizon"]:
        await message.answer(f"План на {plan['title']} пока пуст. Отметь «Иду» в подборке: /digest")
        return
    await message.answer(f"<pre>{escape(plan['text'])}</pre>", parse_mode=ParseMode.HTML)
    for items in plan["days"].values():
        for it in items:
            if it["status"] == "иду":
                warn = " ⚠️ пересекается по времени" if it.get("conflict") else ""
                await message.answer(f"<b>{escape(it['event']['title'])}</b>{warn}", parse_mode=ParseMode.HTML,
                                     reply_markup=markup(plan_item_keyboard(it)))


def _profile(session, user_id: int):
    p = services.get_profile(session, user_id)
    if p is None or p.onboarded_at is None:
        return None
    return services.profile_view(p, services.user_decisions(session, user_id))


def profile_text(v: dict) -> str:
    top = sorted(VALUES, key=lambda x: -int(v["values"].get(x, 0)))[:5]
    first = [c for c, w in v["interests"].items() if int(w) == 3]
    off = [c for c, w in v["interests"].items() if int(w) == 0]
    prm = v["params"]
    lines = [f"<b>Главные ценности:</b> {escape(', '.join(top))}"]
    if first:
        lines.append(f"<b>В первую очередь:</b> {escape(', '.join(first))}")
    if off:
        lines.append(f"<b>Не показываю:</b> {escape(', '.join(off))}")
    lines.append(f"<b>Параметры:</b> {escape(str(prm.get('company', 'любая')))}, {escape(', '.join(prm.get('times', [])))}, "
                 f"бюджет {prm.get('budget') or 'без ограничения'}, эстетика {'обязательна' if prm.get('aesthetics') else 'не принципиальна'}")
    lines.append(f"<b>Что я узнал о тебе:</b> {escape(v['learned_text'])}")
    lines.append(f"Поправить всё можно в вебе: {settings.WEB_BASE_URL.rstrip('/')}/profile или заново через /reset")
    return "\n".join(lines)


@router.message(Command("profile"))
async def profile(message: Message) -> None:
    v = await run_db(_profile, message.from_user.id)
    if v is None:
        await message.answer(NOT_READY)
        return
    await message.answer(profile_text(v), parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@router.message(Command("help"))
async def help_cmd(message: Message) -> None:
    await message.answer("/digest — подборка на ближайшие выходные\n/plan — мой план\n/profile — что я о тебе знаю\n"
                         "/reset — пройти настройку заново\n/delete — удалить мои данные\n\nКаждый четверг в 19:00 пришлю подборку сам; "
                         "утром в день события — план, на следующий день спрошу, как прошло.")


DELETE_KEYBOARD = [[{"text": "Да, удалить всё", "callback_data": "del:yes"}, {"text": "Отмена", "callback_data": "del:no"}]]


@router.message(Command("delete"))
async def delete_cmd(message: Message) -> None:
    await message.answer("Удалить профиль, все решения и подборки? Это отзыв согласия на обработку данных: "
                         "восстановить будет нельзя, подборки перестанут приходить.", reply_markup=markup(DELETE_KEYBOARD))


@router.callback_query(F.data == "del:yes")
async def delete_yes(cb: CallbackQuery, state: FSMContext) -> None:
    removed = await run_db(services.delete_profile, cb.from_user.id)
    await state.clear()
    await cb.message.edit_text("Готово: данные удалены. Если захочешь вернуться — /start." if removed else "Профиля уже нет.")
    await cb.answer()


@router.callback_query(F.data == "del:no")
async def delete_no(cb: CallbackQuery) -> None:
    await cb.message.edit_text("Оставляю всё как есть.")
    await cb.answer()
