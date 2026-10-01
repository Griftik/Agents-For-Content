"""Клавиатуры. Все подписи — из texts.yaml / questions.yaml."""
from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton as IB,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from bot.config import get_settings
from bot.content import Content


def _ikb(rows: list[list[IB]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def open_app(text: str) -> InlineKeyboardMarkup | None:
    """Кнопка, открывающая мини-приложение (заявка, меню, подписка)."""
    url = get_settings().webapp_url
    if not url:
        return None
    return _ikb([[IB(text=text, web_app=WebAppInfo(url=url))]])


def contact(c: Content, with_later: bool = True) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=c.t("contact_button"), request_contact=True)]]
    if with_later:
        rows.append([KeyboardButton(text=c.t("contact_later_button"))])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, one_time_keyboard=True)


def book(text: str) -> InlineKeyboardMarkup:
    """Кнопка-колбэк: сначала фиксируем событие, потом отдаём ссылку."""
    return _ikb([[IB(text=text, callback_data="book")]])


def booking_url(text: str) -> InlineKeyboardMarkup | None:
    url = get_settings().booking_url
    return _ikb([[IB(text=text, url=url)]]) if url else None


def report_next(c: Content) -> InlineKeyboardMarkup:
    return _ikb([[IB(text=c.t("report_next_button"), callback_data="next")]])


def yes_no(c: Content, prefix: str) -> InlineKeyboardMarkup:
    return _ikb([[
        IB(text=c.t("yes_button"), callback_data=f"{prefix}:yes"),
        IB(text=c.t("no_button"), callback_data=f"{prefix}:no"),
    ]])


def admin_card(c: Content, user_id: int, username: str | None) -> InlineKeyboardMarkup:
    b = c.texts["admin_buttons"]
    rows = []
    # tg://user?id= в кнопке Telegram отклоняет, если у человека закрыт профиль,
    # поэтому «Написать» — только по username; иначе ссылка есть в тексте карточки.
    if username:
        rows.append([IB(text=b["write"], url=f"https://t.me/{username}")])
    rows += [
        [IB(text=b["contacted"], callback_data=f"adm:contacted:{user_id}")],
        [IB(text=b["send_report"], callback_data=f"adm:send:{user_id}")],
    ]
    return _ikb(rows)
