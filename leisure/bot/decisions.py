"""Кнопки карточек: иду / может быть / мимо (+ причина) и оценка после выходных."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import select

from leisure.api import services
from leisure.db.models import Decision

from . import keyboards as kb
from .callbacks import parse_cb
from .db import run_db
from .onboarding import markup

log = logging.getLogger("leisure.bot.decisions")
router = Router(name="decisions")
STATUS_TITLE = {"иду": "Иду", "может": "Может быть", "мимо": "Мимо", "интересно": "Интересно"}
TOASTS = {"иду": "В плане ✓ Напомню в субботу утром.", "может": "Отметил как «может быть».",
          "мимо": "Понял. Почему мимо? Это поможет подбирать точнее.", "интересно": "Запомнил: буду искать похожее."}


def rows_of(markup_obj) -> list[list[dict]]:
    """Кнопки существующего сообщения как список словарей (для перерисовки с отметкой)."""
    rows = []
    for row in (markup_obj.inline_keyboard if markup_obj else []):
        rows.append([{"text": b.text, **({"url": b.url} if b.url else {"callback_data": b.callback_data})} for b in row])
    return rows


def _set(session, user_id: int, event_key: str, status: str, reason: str | None = None, rating: int | None = None):
    ev = services.get_event(session, event_key)
    if ev is None:
        return None
    return services.set_decision(session, user_id, ev, status, reason=reason, rating=rating)


def _rate(session, user_id: int, event_key: str, rating: int):
    ev = services.get_event(session, event_key)
    if ev is None:
        return None
    d = session.scalar(select(Decision).where(Decision.user_id == user_id, Decision.event_id == ev.id))
    if d is None:
        return services.set_decision(session, user_id, ev, "иду", rating=rating)
    d.rating = rating
    session.commit()
    services.recompute_affinity(session, services.get_profile(session, user_id))
    return d


@router.callback_query(F.data.regexp(r"^[drs]:"))
async def on_card_button(cb: CallbackQuery) -> None:
    data = cb.data or ""
    parsed = parse_cb(data)
    if parsed is None and data.startswith("r:0:"):
        parsed = ("reason", "", data.split(":", 2)[2])  # «Без причины»
    if parsed is None:
        await cb.answer()
        return
    kind, value, event_id = parsed
    uid = cb.from_user.id
    try:
        if kind == "decision":
            d = await run_db(_set, uid, event_id, value)
            if d is None:
                await cb.answer("Событие уже убрали из базы.")
                return
            base = kb.mark_keyboard(rows_of(cb.message.reply_markup), STATUS_TITLE[value])
            if value == "мимо":
                await cb.message.edit_reply_markup(reply_markup=markup(base[:1] + kb.reasons_keyboard(event_id)))
            else:
                await cb.message.edit_reply_markup(reply_markup=markup(base))
            await cb.answer(TOASTS[value])
        elif kind == "reason":
            await run_db(_set, uid, event_id, "мимо", value or None)
            rows = rows_of(cb.message.reply_markup)
            await cb.message.edit_reply_markup(reply_markup=markup(kb.mark_keyboard(rows[:1], "Мимо")))
            await cb.answer("Спасибо, учту." if value else "Ок.")
        elif kind == "rating":
            await run_db(_rate, uid, event_id, int(value))
            stars = "★" * int(value) + "☆" * (5 - int(value))
            await cb.message.edit_reply_markup(reply_markup=markup([[{"text": stars, "callback_data": "ob:noop"}]]))
            await cb.answer("Спасибо! Это лучше всего учит подборку.")
    except Exception:  # noqa: BLE001
        log.exception("кнопка %s у %s", data, uid)
        await cb.answer("Что-то пошло не так, попробуй ещё раз.")
