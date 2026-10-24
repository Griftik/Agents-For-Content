"""Кнопки карточек: решения, выбор дня, причины «Мимо», оценка после события (тосты — web/COPY.md, T-TOASTS)."""
from __future__ import annotations

import logging
from datetime import date

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery
from sqlalchemy import select

from leisure.api import services
from leisure.core.timeutil import weekend_days, weekend_iso
from leisure.db.models import Decision
from leisure.worker import messages as msg

from . import keyboards as kb
from . import texts
from .callbacks import parse_cb
from .db import run_db
from .onboarding import markup

log = logging.getLogger("leisure.bot.decisions")
router = Router(name="decisions")
STATUS_TITLE = {"иду": "Иду", "может": "Может быть", "мимо": "Мимо", "интересно": "Интересно", "пропуск": "Убрать из плана"}
TOASTS = {"иду": "В плане: {day}. Напомню утром.", "может": "Оставил в «может быть». Позже можно поменять.",
          "мимо": "Понял, больше не покажу. Причину можно выбрать ниже, это необязательно.",
          "интересно": "Запомнил. Буду показывать похожее.", "пропуск": "Убрал из плана."}
TOAST_REASON = "Учту."
TOAST_GONE = "Этого события уже нет в афише. Остальные: /digest."
TOAST_ERROR = "Не удалось сохранить ответ. Нажми ещё раз."
PROFILE_GONE = texts.STALE_NO_PROFILE
NOT_MODIFIED = "message is not modified"


def toast_for(status: str, day: date | None) -> str:
    return TOASTS[status].format(day=msg.day_phrase(day.isoformat()) if day else "на этой неделе")


def rows_of(markup_obj) -> list[list[dict]]:
    """Кнопки существующего сообщения как список словарей."""
    rows = []
    for row in (markup_obj.inline_keyboard if markup_obj else []):
        rows.append([{"text": b.text, **({"url": b.url} if b.url else {"callback_data": b.callback_data})} for b in row])
    return rows


def link_rows_of(rows: list[list[dict]]) -> list[list[dict]]:
    return [r for r in rows if any("url" in b for b in r)]


def card_day_of(rows: list[list[dict]]) -> date | None:
    """День карточки: из callback_data её кнопок решений (d:<код>:<id>:<день>)."""
    for r in rows:
        for b in r:
            p = parse_cb(b.get("callback_data", ""))
            if p and p.kind == "decision" and p.day:
                return p.day
    return None


def _event_days(ev, day: date | None) -> list[str]:
    anchor = day or (date.fromisoformat(sorted(ev.dates)[0].isoformat()) if ev.dates else None)
    if anchor is None:
        return []
    return weekend_days(ev.as_core(), weekend_iso(anchor))


def card_markup(ev, day: date | None, status: str | None, reasons: str | None, link_rows: list) -> list:
    return msg.card_rows(str(ev.id), _event_days(ev, day), day.isoformat() if day else None, status, reasons, link_rows)


def _set(session, user_id: int, event_key: str, status: str, reason: str | None = None, rating: int | None = None, day=None):
    ev = services.get_event(session, event_key)
    if ev is None:
        return None
    return services.set_decision(session, user_id, ev, status, reason=reason, rating=rating, day=day)


def _decide(session, user_id: int, event_key: str, status: str, day: date | None, rows: list, reason: str | None = None,
            picking_reason: bool = False):
    """Записать решение и собрать клавиатуру карточки. None — события нет. Возвращает (решение, ряды | None)."""
    ev = services.get_event(session, event_key)
    if ev is None:
        return None
    p = services.get_profile(session, user_id)
    if p is not None and p.consent_at is None:           # карточка по диплинку у человека без согласия: сначала настройка
        return "no_consent"
    d = services.set_decision(session, user_id, ev, status, reason=reason, day=day)
    if status == "пропуск":                              # «Убрать из плана» / «Не получилось пойти»: кнопку снимаем
        left = [r for r in rows if not any((b.get("callback_data") or "").startswith("d:p:") for b in r)]
        return d, left
    return d, card_markup(ev, d.day, status, "main" if status == "мимо" and not picking_reason else None, link_rows_of(rows))


def _rate(session, user_id: int, event_key: str, rating: int):
    ev = services.get_event(session, event_key)
    if ev is None:
        return None
    p = services.get_profile(session, user_id)
    if p is None:
        raise services.ProfileMissing(user_id)
    d = session.scalar(select(Decision).where(Decision.user_id == user_id, Decision.event_id == ev.id))
    if d is None:
        return services.set_decision(session, user_id, ev, "иду", rating=rating), None
    previous = d.rating
    d.rating = rating
    session.commit()
    services.recompute_affinity(session, p)
    return d, previous


def _pick_day(session, user_id: int, event_key: str, n: int, current: date | None):
    """Выбор дня уикенда: правит карточку на этот день; если решение «иду» / «может» есть — переносит его день."""
    ev = services.get_event(session, event_key)
    p = services.get_profile(session, user_id)
    if ev is None or p is None:
        return None if ev is None else "no_profile"
    anchor = current or services.local_today(p)
    weekend = weekend_iso(anchor)
    day = weekend[n]
    if day not in [x.isoformat() for x in (ev.dates or [])]:
        return {"toast": None}
    d = session.scalar(select(Decision).where(Decision.user_id == user_id, Decision.event_id == ev.id))
    if d is not None and d.status in ("иду", "может"):
        d = services.set_decision(session, user_id, ev, d.status, day=date.fromisoformat(day))
        toast = f"Перенёс в план на {msg.day_phrase(day)}." if d.status == "иду" else f"Показываю {msg.day_phrase(day)}."
    else:
        toast = f"Показываю {msg.day_phrase(day)}."
    item = services.card_item(session, p, ev, day, weekend)
    status = d.status if d is not None and d.status in msg.STATUS_TITLE else None
    return {"toast": toast, "text": msg.card_text(item, weekend), "rows": msg.card_rows(
        str(ev.id), item["days"], day, status, "main" if d is not None and d.status == "мимо" else None, msg.card_link_rows(item))}


async def _edit_markup(cb: CallbackQuery, rows) -> bool:
    """Перерисовать клавиатуру. False — «message is not modified» (двойной тап, не ошибка)."""
    try:
        await cb.message.edit_reply_markup(reply_markup=markup(rows) if rows else None)
    except TelegramBadRequest as e:
        if NOT_MODIFIED in (e.message or str(e)):
            return False
        raise
    return True


@router.callback_query(F.data.regexp(r"^[drsy]:"))
async def on_card_button(cb: CallbackQuery) -> None:
    data = cb.data or ""
    parsed = parse_cb(data)
    if parsed is None:
        await cb.answer()
        return
    kind, value, event_id, day = parsed
    uid = cb.from_user.id
    rows = rows_of(cb.message.reply_markup)
    try:
        if kind == "decision":
            res = await run_db(_decide, uid, event_id, value, day or card_day_of(rows), rows)
            if res is None:
                await cb.answer(TOAST_GONE)
                return
            if res == "no_consent":
                await cb.answer(texts.NEED_CONSENT)
                return
            d, new_rows = res
            changed = await _edit_markup(cb, new_rows)
            await cb.answer(toast_for(value, d.day) if changed else None)
        elif kind == "more_reasons":
            ev_rows = [r for r in rows if not _is_reason_row(r)]
            at = max((i for i, r in enumerate(ev_rows) if any(str(b.get("callback_data", "")).startswith("d:") for b in r)), default=-1) + 1
            new_rows = ev_rows[:at] + kb.reasons_keyboard(event_id, more=True) + ev_rows[at:]
            await _edit_markup(cb, new_rows)
            await cb.answer()
        elif kind == "reason":
            res = await run_db(_decide, uid, event_id, "мимо", card_day_of(rows), rows, value or None, True)
            if res is None:
                await cb.answer(TOAST_GONE)
                return
            if res == "no_consent":
                await cb.answer(texts.NEED_CONSENT)
                return
            await _edit_markup(cb, res[1])
            await cb.answer(TOAST_REASON)
        elif kind == "day":
            res = await run_db(_pick_day, uid, event_id, int(value), card_day_of(rows))
            if res is None:
                await cb.answer(TOAST_GONE)
            elif res == "no_profile":
                await cb.answer(PROFILE_GONE)
            elif res.get("toast") is None:
                await cb.answer()
            else:
                try:
                    await cb.message.edit_text(res["text"], reply_markup=markup(res["rows"]))
                except TelegramBadRequest as e:
                    if NOT_MODIFIED not in (e.message or str(e)):
                        raise
                    await cb.answer()
                    return
                await cb.answer(res["toast"])
        elif kind == "rating":
            res = await run_db(_rate, uid, event_id, int(value))
            if res is None:
                await cb.answer(TOAST_GONE)
                return
            _, previous = res
            n = int(value)
            if not await _edit_markup(cb, msg.rating_keyboard(event_id, n)):
                await cb.answer()
                return
            await cb.answer(f"Оценка изменена: {n} из 5." if previous and previous != n else f"Оценка {n} из 5.")
    except services.ProfileMissing:
        await cb.answer(PROFILE_GONE)
    except Exception:  # noqa: BLE001
        log.exception("кнопка %s у %s", data, uid)
        await cb.answer(TOAST_ERROR)


def _is_reason_row(row: list[dict]) -> bool:
    return all(str(b.get("callback_data", "")).startswith("r:") or b["text"] == kb.REASON_CAPTION for b in row)
