"""Клавиатуры. Все подписи — из texts.yaml / questions.yaml."""
from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton as IB,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from bot.config import get_settings
from bot.content import Content, Question


def _ikb(rows: list[list[IB]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def start(c: Content) -> InlineKeyboardMarkup:
    return _ikb([[IB(text=c.t("start_button"), callback_data="app:start")]])


def resume(c: Content) -> InlineKeyboardMarkup:
    return _ikb([
        [IB(text=c.t("resume_button"), callback_data="app:resume")],
        [IB(text=c.t("restart_button"), callback_data="app:restart")],
    ])


def question(c: Content, q: Question, with_back: bool) -> InlineKeyboardMarkup:
    rows = [[IB(text=text, callback_data=f"a:{q.code}:{code}")] for code, text in q.options]
    if q.skippable and q.label("skip") is None:
        rows.append([IB(text=c.t("skip_button"), callback_data=f"a:{q.code}:skip")])
    if with_back:
        rows.append([IB(text=c.t("back_button"), callback_data=f"back:{q.code}")])
    return _ikb(rows)


def contact(c: Content, with_later: bool = True) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=c.t("contact_button"), request_contact=True)]]
    if with_later:
        rows.append([KeyboardButton(text=c.t("contact_later_button"))])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, one_time_keyboard=True)


def company_skip(c: Content) -> InlineKeyboardMarkup:
    return _ikb([[IB(text=c.company_skip or c.t("company_skip_button"), callback_data="company:skip")]])


def book(text: str) -> InlineKeyboardMarkup:
    """Кнопка-колбэк: сначала фиксируем событие, потом отдаём ссылку."""
    return _ikb([[IB(text=text, callback_data="book")]])


def booking_url(text: str) -> InlineKeyboardMarkup | None:
    url = get_settings().booking_url
    return _ikb([[IB(text=text, url=url)]]) if url else None


def report_next(c: Content) -> InlineKeyboardMarkup:
    return _ikb([[IB(text=c.t("report_next_button"), callback_data="next")]])


def menu(c: Content, nurture_enabled: bool, has_report: bool) -> InlineKeyboardMarkup:
    b = c.texts["menu_buttons"]
    state = c.t("notify_on") if nurture_enabled else c.t("notify_off")
    rows = [[IB(text=c.t("restart_button"), callback_data="menu:restart")]]
    if has_report:
        rows.append([IB(text=b["report"], callback_data="menu:report")])
    rows += [
        [IB(text=b["booking"], callback_data="menu:booking")],
        [IB(text=b["notify_toggle"].format(state=state), callback_data="menu:notify")],
        [IB(text=b["delete"], callback_data="menu:delete")],
    ]
    return _ikb(rows)


def yes_no(c: Content, prefix: str) -> InlineKeyboardMarkup:
    return _ikb([[
        IB(text=c.t("yes_button"), callback_data=f"{prefix}:yes"),
        IB(text=c.t("no_button"), callback_data=f"{prefix}:no"),
    ]])


def channel(c: Content) -> InlineKeyboardMarkup:
    return _ikb([[IB(text=c.t("specialist_channel_button"), url=get_settings().channel_url)]])


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
