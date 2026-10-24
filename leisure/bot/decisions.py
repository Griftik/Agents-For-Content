"""Кнопки карточек: иду / может быть / мимо (+ причина) и оценка после выходных."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery
from sqlalchemy import select

from leisure.api import services
from leisure.db.models import Decision

from . import keyboards as kb
from .callbacks import Parsed, parse_cb
from .db import run_db
from .onboarding import markup

log = logging.getLogger("leisure.bot.decisions")
router = Router(name="decisions")
STATUS_TITLE = {"иду": "Иду", "может": "Может быть", "мимо": "Мимо", "интересно": "Интересно", "пропуск": "Пропуск"}
TOASTS = {"иду": "В плане ✓ Напомню утром в день события.", "может": "Отметил как «может быть».",
          "мимо": "Записал «Мимо». Причину можно не указывать.", "интересно": "Запомнил: буду искать похожее.", "пропуск": "Понял, пропускаю."}
PROFILE_GONE = "Профиль удалён. Чтобы начать заново — /start"
NOT_MODIFIED = "message is not modified"


def rows_of(markup_obj) -> list[list[dict]]:
    """Кнопки существующего сообщения как список словарей (для перерисовки с отметкой)."""
    rows = []
    for row in (markup_obj.inline_keyboard if markup_obj else []):
        rows.append([{"text": b.text, **({"url": b.url} if b.url else {"callback_data": b.callback_data})} for b in row])
    return rows


def _is_reason_row(row: list[dict]) -> bool:
    return all(b.get("callback_data", "").startswith("r:") or b["text"] == kb.REASON_CAPTION for b in row)


def card_rows(rows: list[list[dict]], mark: str, event_id: str | None = None) -> list[list[dict]]:
    """Клавиатура карточки после решения: первый ряд с отметкой, затем (если event_id — ряды причин «Мимо»),
    затем остальные исходные ряды (ссылки, «Весь дайджест»). Ряды причин прежнего вида отбрасываются."""
    rows = kb.mark_keyboard(rows, mark)
    first, rest = rows[:1], [r for r in rows[1:] if not _is_reason_row(r)]
    return first + (kb.reasons_keyboard(event_id) if event_id else []) + rest


def _set(session, user_id: int, event_key: str, status: str, reason: str | None = None, rating: int | None = None,
         day=None):
    ev = services.get_event(session, event_key)
    if ev is None:
        return None
    return services.set_decision(session, user_id, ev, status, reason=reason, rating=rating, day=day)


def _rate(session, user_id: int, event_key: str, rating: int):
    ev = services.get_event(session, event_key)
    if ev is None:
        return None
    p = services.get_profile(session, user_id)
    if p is None:
        raise services.ProfileMissing(user_id)
    d = session.scalar(select(Decision).where(Decision.user_id == user_id, Decision.event_id == ev.id))
    if d is None:
        return services.set_decision(session, user_id, ev, "иду", rating=rating)
    d.rating = rating
    session.commit()
    services.recompute_affinity(session, p)
    return d


async def _edit_markup(cb: CallbackQuery, rows) -> None:
    """Перерисовать клавиатуру; повторное нажатие той же кнопки («message is not modified») — не ошибка."""
    try:
        await cb.message.edit_reply_markup(reply_markup=markup(rows))
    except TelegramBadRequest as e:
        if NOT_MODIFIED not in (e.message or str(e)):
            raise


@router.callback_query(F.data.regexp(r"^[drs]:"))
async def on_card_button(cb: CallbackQuery) -> None:
    data = cb.data or ""
    parsed = parse_cb(data)
    if parsed is None and data.startswith("r:0:"):
        parsed = Parsed("reason", "", data.split(":", 2)[2])  # «Без причины»
    if parsed is None:
        await cb.answer()
        return
    kind, value, event_id, day = parsed
    uid = cb.from_user.id
    try:
        if kind == "decision":
            d = await run_db(_set, uid, event_id, value, day=day)
            if d is None:
                await cb.answer("Событие уже убрали из базы.")
                return
            rows = rows_of(cb.message.reply_markup)
            await _edit_markup(cb, card_rows(rows, STATUS_TITLE[value], event_id if value == "мимо" else None))
            await cb.answer(TOASTS[value])
        elif kind == "reason":
            await run_db(_set, uid, event_id, "мимо", value or None)
            await _edit_markup(cb, card_rows(rows_of(cb.message.reply_markup), "Мимо"))
            await cb.answer("Спасибо, учту." if value else "Ок.")
        elif kind == "rating":
            await run_db(_rate, uid, event_id, int(value))
            stars = "★" * int(value) + "☆" * (5 - int(value))
            await _edit_markup(cb, [[{"text": stars, "callback_data": "ob:noop"}]])
            await cb.answer("Спасибо! Это лучше всего учит подборку.")
    except services.ProfileMissing:
        await cb.answer(PROFILE_GONE, show_alert=True)
    except Exception:  # noqa: BLE001
        log.exception("кнопка %s у %s", data, uid)
        await cb.answer("Что-то пошло не так, попробуй ещё раз.")
