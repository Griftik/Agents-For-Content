"""Онбординг (п. 3.1 спеки): согласие → 5 главных ценностей → важно/не очень → интересы → параметры → заметка → первая подборка."""
from __future__ import annotations

import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from leisure import settings
from leisure.api import services
from leisure.core.catalog import ALL_CATS, COMPANY_OPTIONS, SLOTS, VALUES, interests_from_values
from leisure.worker.schedules import digest_messages
from leisure.worker.send import send_with_bot

from . import keyboards as kb
from .db import run_db

log = logging.getLogger("leisure.bot.onboarding")
router = Router(name="onboarding")


class Onb(StatesGroup):
    values = State()
    weights = State()
    interests = State()
    company = State()
    times = State()
    budget = State()
    aesthetics = State()
    notes = State()


def markup(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(**b) for b in row] for row in rows])


POLICY_URL = f"{settings.WEB_BASE_URL.rstrip('/')}/policy"
STALE_SCREEN = "Этот экран устарел. Начни заново: /start"
PRESS_BUTTON = "Здесь нужно нажать кнопку выше"
PROFILE_GONE = "Профиль удалён. Чтобы начать заново — /start"


def hello_message() -> tuple[str, list]:
    """Приветствие и клавиатура согласия. При WEB_BASE_URL=localhost URL-кнопки нет: политика уходит ссылкой в тексте."""
    if services.web_links_enabled():
        return HELLO, kb.consent_keyboard(POLICY_URL)
    return f"{HELLO}\n\nПолитика обработки данных: {POLICY_URL}", kb.consent_keyboard(None)
HELLO = ("Привет! Я подбираю события на выходные под твои ценности, а не под рубрики афиши: 5–7 карточек "
         "в четверг вечером, с объяснением, почему именно тебе.\n\n"
         "Чтобы начать, мне нужны твой Telegram id, имя и ответы на несколько вопросов — три минуты. "
         "Данные хранятся в России и нужны только для подборки.")


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    u = message.from_user
    p = await run_db(services.get_or_create_profile, u.id, u.full_name or "", u.username or "")
    if not p.active:
        await run_db(services.set_active, u.id, True)  # вернулся после блокировки бота — рассылки снова включены
    if p.onboarded_at is not None:
        await message.answer("С возвращением. Команды: /digest — подборка на выходные, /plan — план, "
                             "/profile — что я о тебе знаю, /reset — пройти настройку заново.")
        return
    await state.clear()
    text, rows = hello_message()
    await message.answer(text, reply_markup=markup(rows))


@router.message(Command("reset"))
async def reset(message: Message, state: FSMContext) -> None:
    await state.clear()
    text, rows = hello_message()
    await message.answer("Настроим заново. " + text, reply_markup=markup(rows))


@router.callback_query(F.data == "ob:consent")
async def consent(cb: CallbackQuery, state: FSMContext) -> None:
    await run_db(lambda s, uid: services.update_profile(s, services.get_or_create_profile(s, uid), {"consent": True}), cb.from_user.id)
    await state.set_state(Onb.values)
    await state.update_data(top=[], important=[], asked=[])
    await cb.message.edit_text("Шаг 1 из 5. Что для тебя главное? Выбери пять ценностей.",
                               reply_markup=markup(kb.values_pick_keyboard([])))
    await cb.answer()


@router.callback_query(Onb.values, F.data.startswith("ob:v:"))
async def pick_value(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    top: list[str] = data.get("top", [])
    v = VALUES[int(cb.data.split(":")[2])]
    if v in top:
        top.remove(v)
    elif len(top) < kb.TOP_N:
        top.append(v)
    else:
        await cb.answer("Уже пять. Сними одну, чтобы выбрать другую.")
        return
    await state.update_data(top=top)
    await cb.message.edit_reply_markup(reply_markup=markup(kb.values_pick_keyboard(top)))
    await cb.answer()


@router.callback_query(F.data == "ob:noop")
async def noop(cb: CallbackQuery) -> None:
    await cb.answer()


async def _ask_weight(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    rest = [v for v in VALUES if v not in data["top"] and v not in data.get("asked", [])]
    if not rest:
        values = kb.weights_from_choice(data["top"], data.get("important", []))
        interests = interests_from_values(values)
        await state.update_data(values=values, interests=interests)
        await state.set_state(Onb.interests)
        await cb.message.edit_text("Шаг 2 из 5. Интересы. Я предзаполнил их по твоим ценностям — нажимай, чтобы поменять "
                                   "(— не показывать · иногда · интересно · в первую очередь).",
                                   reply_markup=markup(kb.interests_keyboard(interests)))
        return
    v = rest[0]
    await state.update_data(asked=data.get("asked", []) + [v])
    await cb.message.edit_text(f"Шаг 1 из 5. А «{v}» — насколько важно?", reply_markup=markup(kb.weight_keyboard(VALUES.index(v))))


@router.callback_query(Onb.values, F.data == "ob:vnext")
async def values_next(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if len(data.get("top", [])) != kb.TOP_N:
        await cb.answer("Нужно ровно пять.")
        return
    await state.set_state(Onb.weights)
    await _ask_weight(cb, state)
    await cb.answer()


@router.callback_query(Onb.weights, F.data.startswith("ob:w:"))
async def weight(cb: CallbackQuery, state: FSMContext) -> None:
    _, _, idx, flag = cb.data.split(":")
    data = await state.get_data()
    important = data.get("important", [])
    if flag == "1":
        important.append(VALUES[int(idx)])
    await state.update_data(important=important)
    await _ask_weight(cb, state)
    await cb.answer()


@router.callback_query(Onb.interests, F.data.startswith("ob:i:"))
async def interest_cycle(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    interests = data["interests"]
    c = ALL_CATS[int(cb.data.split(":")[2])]
    interests[c] = (int(interests.get(c, 2)) + 1) % 4
    await state.update_data(interests=interests)
    await cb.message.edit_reply_markup(reply_markup=markup(kb.interests_keyboard(interests)))
    await cb.answer()


@router.callback_query(Onb.interests, F.data == "ob:inext")
async def interests_next(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Onb.company)
    await cb.message.edit_text("Шаг 3 из 5. С кем ты обычно ходишь?", reply_markup=markup(kb.company_keyboard()))
    await cb.answer()


@router.callback_query(Onb.company, F.data.startswith("ob:c:"))
async def company(cb: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(company=COMPANY_OPTIONS[int(cb.data.split(":")[2])], times=[])
    await state.set_state(Onb.times)
    await cb.message.edit_text("Когда тебе удобнее? Можно несколько.", reply_markup=markup(kb.times_keyboard([])))
    await cb.answer()


@router.callback_query(Onb.times, F.data.startswith("ob:t:"))
async def times_toggle(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    times = data.get("times", [])
    t = SLOTS[int(cb.data.split(":")[2])]
    times = [x for x in times if x != t] if t in times else times + [t]
    await state.update_data(times=times)
    await cb.message.edit_reply_markup(reply_markup=markup(kb.times_keyboard(times)))
    await cb.answer()


@router.callback_query(Onb.times, F.data == "ob:tnext")
async def times_next(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("times"):
        await state.update_data(times=["день", "вечер"])
    await state.set_state(Onb.budget)
    await cb.message.edit_text("Бюджет на одно событие?", reply_markup=markup(kb.budget_keyboard()))
    await cb.answer()


@router.callback_query(Onb.budget, F.data.startswith("ob:b:"))
async def budget(cb: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(budget=int(cb.data.split(":")[2]))
    await state.set_state(Onb.aesthetics)
    await cb.message.edit_text("Красота места и формата для тебя обязательна?", reply_markup=markup(kb.aesthetics_keyboard()))
    await cb.answer()


@router.callback_query(Onb.aesthetics, F.data.startswith("ob:a:"))
async def aesthetics(cb: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(aesthetics=cb.data.endswith(":1"))
    await state.set_state(Onb.notes)
    await cb.message.edit_text("Шаг 4 из 5. Напиши пару слов: что надоело, что хочется попробовать. Или пропусти.",
                               reply_markup=markup(kb.notes_keyboard()))
    await cb.answer()


@router.message(Onb.notes, F.text, ~F.text.startswith("/"))
async def notes_text(message: Message, state: FSMContext) -> None:
    await _finish(message, state, (message.text or "")[:2000], user_id=message.from_user.id)


@router.callback_query(Onb.notes, F.data == "ob:skipnotes")
async def notes_skip(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await _finish(cb.message, state, "", user_id=cb.from_user.id)


def _save_profile(session, user_id: int, data: dict):
    p = services.get_profile(session, user_id)
    if p is None:
        return None  # профиль удалён по /delete посреди настройки — не воскрешаем без нового согласия
    params = {"company": data["company"], "times": data["times"], "budget": data["budget"],
              "aesthetics": data["aesthetics"], "adults30": True, "kids": data["company"] == "с детьми"}
    return services.update_profile(session, p, {"values": data["values"], "interests": data["interests"],
                                                 "params": params, "notes": data.get("notes", ""), "onboarded": True})


def _first_digest(session, user_id: int, now: datetime):
    p = services.get_profile(session, user_id)
    dg, _, _ = services.core_digest(session, p, services.local_today(p), now=now)
    view = services.digest_view(p, dg)
    if dg.items():
        services.save_digest(session, p, dg, sent=True)  # в четверг этот уикенд повторно не шлём
    return p, view


async def _finish(message: Message, state: FSMContext, notes: str, user_id: int) -> None:
    data = await state.get_data()
    data["notes"] = notes
    await state.clear()
    try:
        saved = await run_db(_save_profile, user_id, data)
    except Exception:  # noqa: BLE001
        log.exception("не сохранился профиль %s", user_id)
        await message.answer("Не получилось сохранить профиль. Попробуй /reset ещё раз.")
        return
    if saved is None:
        await message.answer(PROFILE_GONE)
        return
    await message.answer("Шаг 5 из 5. Профиль сохранён. Собираю первую подборку на ближайшие выходные…")
    p, view = await run_db(_first_digest, user_id, services.utcnow())
    await send_with_bot(message.bot, digest_messages(p, view))


# ─── запасные обработчики (регистрируются последними: срабатывают, только если ни один шаг не подошёл) ───
BUTTON_STEPS = (Onb.values, Onb.weights, Onb.interests, Onb.company, Onb.times, Onb.budget, Onb.aesthetics)


@router.message(StateFilter(*BUTTON_STEPS), F.text, ~F.text.startswith("/"))
async def text_on_button_step(message: Message) -> None:
    """Текст на шаге с кнопками: короткая подсказка, состояние не меняем. Команды сюда не попадают."""
    await message.answer(PRESS_BUTTON)


@router.callback_query(F.data.startswith("ob:"))
async def stale_onboarding_button(cb: CallbackQuery) -> None:
    """Кнопка онбординга без подходящего состояния (например, после перезапуска бота): объясняем и снимаем «часики»."""
    try:
        await cb.message.answer(STALE_SCREEN)
    except Exception:  # noqa: BLE001
        log.info("не удалось ответить на устаревшую кнопку %s", cb.data)
    await cb.answer()
