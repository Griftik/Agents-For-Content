"""Онбординг v2 (web/FLOW-ONBOARDING.md): согласие → «Шаг 1 из 2» ценности → «Шаг 2 из 2» интересы → подборка; параметры и заметка —
в необязательном меню «Уточнить под себя». Тексты — texts.py (web/COPY.md).

Состояние — в профиле (черновик): каждое нажатие сразу пишет values / interests / params, поэтому перезапуск бота не ломает экран, а
любой callback `ob:*` обрабатывается без FSM. В памяти (FSM) остаются только подсказки: режим (start / reset / profile), флаг «менялось
влияющее на подборку» и ожидание текста заметки; если они потеряны, бот работает по данным профиля.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from leisure import settings
from leisure.api import services
from leisure.core.catalog import (ALL_CATS, COMPANY_OPTIONS, SLOTS, VALUES, default_aesthetics, default_profile,
                                  propose_interests, proposed_categories, weights_from_top)
from leisure.worker.schedules import digest_messages
from leisure.worker.send import send_with_bot

from . import keyboards as kb
from . import texts
from .db import run_db

log = logging.getLogger("leisure.bot.onboarding")
router = Router(name="onboarding")


class Onb(StatesGroup):
    """Единственное состояние в памяти — «жду текст заметки»."""
    notes = State()


def markup(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(**b) for b in row] for row in rows])


POLICY_URL = f"{settings.WEB_BASE_URL.rstrip('/')}/policy"
HELLO = texts.HELLO
STALE_SCREEN = texts.STALE
PRESS_BUTTON = texts.TEXT_ONB
PROFILE_GONE = texts.STALE_NO_PROFILE


def hello_message() -> tuple[str, list]:
    """Приветствие и клавиатура согласия. При WEB_BASE_URL=localhost URL-кнопки нет: политика уходит ссылкой в тексте."""
    if services.web_links_enabled():
        return HELLO, kb.consent_keyboard(POLICY_URL)
    return f"{HELLO}\n\nПолитика обработки данных: {POLICY_URL}", kb.consent_keyboard(None)


# ─── черновик профиля ───
def top_values(p) -> list[str]:
    return [v for v in VALUES if int((p.values or {}).get(v, 0) or 0) == 5]


def _set_values(session, p, top: list[str]):
    return services.update_profile(session, p, {"values": weights_from_top(top)}, auto_onboarded=False)


def _levels(p) -> dict[str, int]:
    return {c: int((p.interests or {}).get(c, 2)) for c in ALL_CATS}


def shown_categories(p) -> list[str]:
    """Предложенные по ценностям шесть направлений + добавленные вручную (уровень 2–3), в этом порядке."""
    proposed = proposed_categories(p.values or {})
    lv = _levels(p)
    return proposed + [c for c in ALL_CATS if c not in proposed and lv[c] >= 2]


def _back_target(p) -> str:
    return "ob:go:p" if p.onboarded_at is not None else "ob:go:hi"


@dataclass
class Out:
    """Что сделать с нажатием: правка экрана (или новое сообщение), тост, обновление подсказок в памяти, подборка."""
    text: str | None = None
    rows: list | None = None
    toast: str | None = None
    new_message: bool = False
    mode: str | None = None
    dirty: bool | None = None
    wait_note: bool | None = None
    digest: str | None = None            # 'first' | 'regular'
    extra: dict = field(default_factory=dict)


def screen_values(p) -> Out:
    return Out(texts.values_text(top_values(p)), kb.values_pick_keyboard(top_values(p), _back_target(p)))


def screen_interests(p, mode: str, changed: bool = False) -> Out:
    shown = shown_categories(p)
    save = "Сохранить" if mode == "profile" else "Показать подборку →"
    back = "ob:go:p" if mode == "profile" else "ob:go:v"
    return Out(texts.interests_text(len(ALL_CATS) - len(shown), changed),
               kb.interests_main_keyboard(shown, _levels(p), len(ALL_CATS) - len(shown), save, back,
                                          int((p.params or {}).get("budget") or 0)))


def screen_all(p, mode: str, brush: int = 2) -> Out:
    save = "Сохранить" if mode == "profile" else "Показать подборку →"
    return Out(texts.all_text(_levels(p)), kb.interests_all_keyboard(_levels(p), brush, save))


def screen_menu(p, dirty: bool) -> Out:
    return Out(texts.SETUP_TEXT, kb.setup_menu_keyboard(p.params or {}, bool(p.notes), dirty))


def screen_profile(session, p) -> Out:
    v = services.profile_view(p, services.user_decisions(session, p.user_id))
    return Out(texts.profile_text(v), kb.profile_keyboard())


def _mode(p, hint: str | None) -> str:
    if p.onboarded_at is None:
        return "start"
    return hint if hint in ("reset", "profile") else "profile"


def _write_params(session, p, **params):
    return services.update_profile(session, p, {"params": params}, auto_onboarded=False)


# ─── действия: синхронная часть, работает с БД ───
def act(session, uid: int, parts: list[str], mode_hint: str | None, dirty: bool, src_text: str = "") -> Out | None:
    """Результат нажатия `ob:<parts>`; None — профиля нет (STALE_NO_PROFILE)."""
    p = services.get_profile(session, uid)
    if p is None:
        return None
    cmd = parts[0]
    mode = _mode(p, mode_hint)
    arg = parts[1:]

    if cmd == "consent":
        if p.onboarded_at is not None:
            return Out(texts.START_AGAIN, [])
        d = default_profile()
        services.update_profile(session, p, {"consent": True, "values": weights_from_top([]),
                                             "params": d["params"]}, auto_onboarded=False)
        p = services.get_profile(session, uid)
        out = screen_values(p)
        out.mode = "start"
        return out

    if cmd == "go":
        return _go(session, p, arg[0], mode, dirty, src_text)

    if cmd == "v":
        v = VALUES[int(arg[0])]
        top = top_values(p)
        if v in top:
            top.remove(v)
        elif len(top) >= kb.TOP_N:
            return Out(toast=texts.VALUES_FULL)
        else:
            top.append(v)
        p = _set_values(session, p, top)
        return screen_values(p)

    if cmd == "ct":
        c = ALL_CATS[int(arg[0])]
        lv = _levels(p)
        lv[c] = 0 if lv[c] > 0 else 2
        p = services.update_profile(session, p, {"interests": lv}, auto_onboarded=False)
        return screen_interests(p, mode)

    if cmd == "sb":                                  # бюджет одной строкой на «Шаге 2»: пишем и остаёмся на экране
        p = _write_params(session, p, budget=int(arg[0]))
        return screen_interests(p, mode)

    if cmd == "br":
        return screen_all(p, mode, int(arg[0]))

    if cmd == "cs":
        c, lvl = ALL_CATS[int(arg[0])], int(arg[1])
        p = services.update_profile(session, p, {"interests": {c: lvl}}, auto_onboarded=False)
        return screen_all(p, mode, lvl)

    if cmd == "show":
        return _show(session, p, mode)

    if cmd in ("b", "a", "t", "c"):
        return _setting(session, p, cmd, arg[0])

    if cmd == "redo":
        return Out(toast=texts.TOAST_BUILD, dirty=False, digest="regular")

    if cmd == "done":
        return Out(texts.SETUP_DONE, [], dirty=False)

    if cmd == "noop":
        return Out()
    return Out(toast=texts.STALE)


def _go(session, p, where: str, mode: str, dirty: bool, src_text: str) -> Out:
    if where == "hi" and p.onboarded_at is None:
        text, rows = hello_message()
        return Out(text, rows)
    if where == "v":
        return screen_values(p)
    if where == "p":
        return screen_profile(session, p)
    if where == "i":
        top = top_values(p)
        if len(top) != kb.TOP_N:
            out = screen_values(p)
            out.toast = "Нужно выбрать ровно пять."
            return out
        params = p.params or {}
        changed = False
        if params.get("interests_basis") != sorted(top):
            changed = params.get("interests_basis") is not None
            upd = {"interests_basis": sorted(top)}
            if p.onboarded_at is None:
                upd["aesthetics"] = default_aesthetics(top)       # умолчание от пятёрки ценностей; дальше правится в меню
            services.update_profile(session, p, {"interests": propose_interests(p.values or {}), "params": upd},
                                    auto_onboarded=False)
            p = services.get_profile(session, p.user_id)
        return screen_interests(p, mode, changed)
    if where == "ia":
        return screen_all(p, mode)
    if where == "s":
        times = (p.params or {}).get("times")
        if not times:
            p = _write_params(session, p, times=["день", "вечер"])
        out = screen_menu(p, dirty)
        out.new_message = not _is_setup_screen(src_text)  # из заголовка подборки или /profile — новым сообщением
        return out
    if where == "sb":
        return Out(texts.SETUP_BUDGET, kb.budget_keyboard(int((p.params or {}).get("budget") or 0)))
    if where == "sa":
        return Out(texts.SETUP_AEST, kb.aesthetics_keyboard(bool((p.params or {}).get("aesthetics"))))
    if where == "st":
        return Out(texts.SETUP_TIMES, kb.times_keyboard((p.params or {}).get("times") or []))
    if where == "sc":
        return Out(texts.SETUP_KIDS, kb.kids_keyboard((p.params or {}).get("company") == "с детьми"))
    if where == "n":
        return Out(texts.SETUP_NOTE, kb.note_keyboard(), wait_note=True)
    return Out(toast=texts.STALE)


def _is_setup_screen(src_text: str) -> bool:
    return src_text.split("\n")[0] in texts.SETUP_TITLES


def _setting(session, p, cmd: str, val: str) -> Out:
    params = p.params or {}
    if cmd == "b":
        p = _write_params(session, p, budget=int(val))
        return Out(*_menu_args(p), dirty=True)
    if cmd == "a":
        p = _write_params(session, p, aesthetics=val == "1")
        return Out(*_menu_args(p), dirty=True)
    if cmd == "t":
        times = list(params.get("times") or [])
        t = SLOTS[int(val)]
        times = [x for x in times if x != t] if t in times else [x for x in SLOTS if x in times + [t]]
        p = _write_params(session, p, times=times)
        return Out(texts.SETUP_TIMES, kb.times_keyboard(times), dirty=True)
    company = COMPANY_OPTIONS[int(val)]
    p = _write_params(session, p, company=company, kids=company == "с детьми")
    return Out(*_menu_args(p), dirty=True)


def _menu_args(p) -> tuple[str, list]:
    return texts.SETUP_TEXT, kb.setup_menu_keyboard(p.params or {}, bool(p.notes), True)


def _show(session, p, mode: str) -> Out:
    top = top_values(p)
    if len(top) != kb.TOP_N:
        out = screen_values(p)
        out.toast = "Нужно выбрать ровно пять."
        return out
    if mode == "profile":
        services.update_profile(session, p, {"onboarded": True}, auto_onboarded=False)
        return Out(texts.PROFILE_SAVED, [])
    first = p.onboarded_at is None
    p = services.update_profile(session, p, {"onboarded": True}, auto_onboarded=False)
    return Out(texts.saved_text(top, _levels(p), int((p.params or {}).get("budget") or 0)), [], toast=texts.TOAST_BUILD, digest="first" if first else "regular",
               mode="profile")


# ─── подборка (первая и по «Пересобрать») ───
def _digest_for(session, user_id: int, first: bool):
    p = services.get_profile(session, user_id)
    if p is None:
        return None
    now = services.utcnow()
    dg, _, _ = services.core_digest(session, p, services.local_today(p), now=now)
    view = services.digest_view(p, dg, services.decision_map(session, user_id))
    if dg.items():
        # Первая подборка и «Пересобрать» пишутся в Digest.items этого уикенда (перезапись той же строки, не новый дайджест):
        # показанное попадает в журнал «что показывали», в четверг этот уикенд повторно не шлём.
        services.save_digest(session, p, dg, sent=True)
    return p, view


async def send_digest(message: Message, user_id: int, first: bool) -> None:
    got = await run_db(_digest_for, user_id, first)
    if got is None:
        await message.answer(texts.STALE_NO_PROFILE)
        return
    p, view = got
    await send_with_bot(message.bot, digest_messages(p, view, first=first))


# ─── обработчики ───
def _deeplink_card(session, uid: int, slug: str):
    """Карточка события по диплинку /start e_<slug>: (текст, ряды) или None, если события нет. Оценка — только у настроенного профиля."""
    from leisure.core.timeutil import weekend_iso
    from leisure.worker import messages as msg

    ev = services.get_event(session, slug)
    p = services.get_profile(session, uid)
    if ev is None or ev.status != "published" or p is None:
        return None
    day = services.first_day(ev, services.local_today(p))
    iso = day.isoformat() if day else None
    weekend = weekend_iso(day or services.local_today(p))
    item = services.card_item(session, p, ev, iso, weekend, scored=p.onboarded_at is not None)
    return msg.card_text(item, weekend), msg.card_keyboard(item)


async def _send_deeplink(message: Message, slug: str, p) -> bool:
    """Показать карточку события и, если профиль не настроен, предложить настройку. False — события нет."""
    card = await run_db(_deeplink_card, message.from_user.id, slug)
    if card is None:
        await message.answer(texts.DEEPLINK_GONE)
        return False
    await message.answer(card[0], reply_markup=markup(card[1]))
    if p.onboarded_at is None:
        if p.consent_at is None:
            text, rows = hello_message()
            await message.answer(texts.DEEPLINK_OFFER + text, reply_markup=markup(rows))
        else:
            await message.answer(texts.DEEPLINK_CONTINUE)
    return True


@router.message(CommandStart())
async def start(message: Message, state: FSMContext, command: CommandObject | None = None) -> None:
    u = message.from_user
    p = await run_db(services.get_or_create_profile, u.id, u.full_name or "", u.username or "")
    if not p.active:
        await run_db(services.set_active, u.id, True)  # вернулся после блокировки бота — рассылки снова включены
    await state.clear()
    arg = (command.args or "").strip() if command else ""
    if arg.startswith("e_") and len(arg) > 2:         # диплинк «Отправить другу»: t.me/<бот>?start=e_<slug>
        if await _send_deeplink(message, arg[2:], p) or p.onboarded_at is not None:
            return
    if p.onboarded_at is not None:
        await message.answer(texts.START_AGAIN)
        return
    if p.consent_at is not None:  # согласие уже дано: показываем экран, на котором остановился
        await state.update_data(mode="start")
        top = top_values(p)
        out = screen_values(p) if len(top) != kb.TOP_N else await run_db(lambda s, uid: screen_interests(services.get_profile(s, uid), "start"), u.id)
        await message.answer(out.text, reply_markup=markup(out.rows))
        return
    text, rows = hello_message()
    await message.answer(text, reply_markup=markup(rows))


@router.message(Command("reset"))
async def reset(message: Message, state: FSMContext) -> None:
    await state.clear()
    p = await run_db(services.get_profile, message.from_user.id)
    if p is None or p.consent_at is None:
        text, rows = hello_message()
        await message.answer(text, reply_markup=markup(rows))
        return
    await state.update_data(mode="reset")
    out = screen_values(p)
    await message.answer(texts.RESET_PREFIX + out.text, reply_markup=markup(out.rows))


async def _edit(cb: CallbackQuery, out: Out) -> None:
    from aiogram.exceptions import TelegramBadRequest

    if out.text is None:
        return
    rows = out.rows or []
    try:
        if out.new_message:
            await cb.message.answer(out.text, reply_markup=markup(rows) if rows else None)
        else:
            await cb.message.edit_text(out.text, reply_markup=markup(rows) if rows else None)
    except TelegramBadRequest as e:
        if "message is not modified" not in (e.message or str(e)):
            raise


@router.callback_query(F.data.startswith("ob:"))
async def on_ob(cb: CallbackQuery, state: FSMContext) -> None:
    """Любая кнопка онбординга. Не зависит от FSM: устаревший экран получает ответ, а не вечную загрузку."""
    data = await state.get_data()
    parts = (cb.data or "").split(":")[1:]
    try:
        src = (cb.message.text or "") if cb.message else ""
        out = await run_db(act, cb.from_user.id, parts, data.get("mode"), bool(data.get("dirty")), src)
    except (ValueError, IndexError):
        await cb.answer(texts.STALE)
        return
    except Exception:  # noqa: BLE001
        log.exception("кнопка %s у %s", cb.data, cb.from_user.id)
        await cb.answer("Что-то пошло не так, попробуй ещё раз.")
        return
    if out is None:
        await cb.answer(texts.STALE_NO_PROFILE)
        return
    upd = {k: v for k, v in (("mode", out.mode), ("dirty", out.dirty)) if v is not None}
    if upd:
        await state.update_data(**upd)
    if out.wait_note:
        await state.set_state(Onb.notes)
    elif await state.get_state() == Onb.notes.state and parts[0] != "noop":
        await state.set_state(None)
    try:
        await _edit(cb, out)
    except Exception:  # noqa: BLE001
        log.exception("не обновился экран %s у %s", cb.data, cb.from_user.id)
    await cb.answer(out.toast or None)
    if out.digest:
        await send_digest(cb.message, cb.from_user.id, out.digest == "first")


@router.message(Onb.notes, F.text, ~F.text.startswith("/"))
async def notes_text(message: Message, state: FSMContext) -> None:
    """Текст заметки; команды сюда не попадают (идут в commands)."""
    def save(session, uid, note):
        p = services.get_profile(session, uid)
        if p is None:
            return None
        p = services.update_profile(session, p, {"notes": note}, auto_onboarded=False)
        return screen_menu(p, False)

    data = await state.get_data()
    out = await run_db(save, message.from_user.id, (message.text or "")[:2000])
    await state.set_state(None)
    if out is None:
        await message.answer(texts.STALE_NO_PROFILE)
        return
    await message.answer(texts.NOTE_SAVED)
    await message.answer(out.text, reply_markup=markup(_with_dirty(out, bool(data.get("dirty")))))


def _with_dirty(out: Out, dirty: bool) -> list:
    return out.rows if not dirty else out.rows[:-1] + [[{"text": "Пересобрать подборку", "callback_data": "ob:redo"}], out.rows[-1]]


@router.message(StateFilter(None), F.text, ~F.text.startswith("/"))
async def text_when_idle(message: Message) -> None:
    """Текст вне заметки: незавершённый профиль — подсказка про кнопки, готовый — список возможностей (T-TEXT-ONB, T-TEXT-ANY)."""
    p = await run_db(services.get_profile, message.from_user.id)
    await message.answer(texts.TEXT_ANY if p is not None and p.onboarded_at is not None else texts.TEXT_ONB)
