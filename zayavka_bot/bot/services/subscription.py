"""Платная подписка на бизнес-аналитику: счёт, оплата, продление, напоминания об окончании.

Рубли — через платёжного провайдера Telegram (ЮKassa, токен от @BotFather), с чеком по 54-ФЗ.
Звёзды (XTR) — без провайдера. Автосписания нет: за {remind_before_days} дня до конца бот
присылает кнопку продления, продление сдвигает срок от конца оплаченного.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from aiogram import Bot
from aiogram.types import InlineKeyboardButton as IB, InlineKeyboardMarkup, LabeledPrice

from bot.config import get_settings
from bot.content import get_content
from bot.db import repo
from bot.db.models import utcnow
from bot.services import notify

log = logging.getLogger(__name__)
JOB_EXPIRING = "sub_expiring"
JOB_EXPIRED = "sub_expired"


@dataclass
class Offer:
    currency: str        # RUB | XTR
    amount: int          # копейки или звёзды
    days: int

    @property
    def price_text(self) -> str:
        return f"{self.amount // 100} ₽" if self.currency == "RUB" else f"{self.amount} ⭐"

    @property
    def payload(self) -> str:
        return f"sub:{self.days}:{self.currency}:{self.amount}"


def cfg() -> dict[str, Any]:
    return get_content().subscription


def current_offer() -> Offer | None:
    """Что сейчас продаём. None — подписка выключена (нет цены)."""
    sc, s = cfg(), get_settings()
    days = int(sc.get("days") or 30)
    if s.payment_provider_token and int(sc.get("price_rub") or 0) > 0:
        return Offer("RUB", int(sc["price_rub"]) * 100, days)
    if int(sc.get("price_stars") or 0) > 0:
        return Offer("XTR", int(sc["price_stars"]), days)
    return None


def t(key: str, **kw: Any) -> str:
    return str(cfg()["texts"][key]).rstrip("\n").format(**kw)


def fmt_date(dt: datetime) -> str:
    return (dt + timedelta(hours=3)).strftime("%d.%m.%Y")  # МСК


async def active_until(user_id: int) -> datetime | None:
    sub = await repo.get_subscription(user_id)
    return sub.paid_until if sub and sub.paid_until > utcnow() else None


async def show(bot: Bot, user_id: int) -> None:
    """Экран подписки: описание и кнопка оплаты, или срок и кнопка продления."""
    offer = current_offer()
    if offer is None:
        await bot.send_message(user_id, t("unavailable"))
        return
    until = await active_until(user_id)
    if until:
        text = t("active", date=fmt_date(until))
        btn = t("renew_button", days=offer.days, price=offer.price_text)
    else:
        text = t("pitch", price=offer.price_text, days=offer.days)
        btn = t("buy_button", price=offer.price_text)
    offer_url = get_settings().offer_url
    if offer_url:
        text += "\n\n" + t("offer_line", offer_url=offer_url)
    markup = InlineKeyboardMarkup(inline_keyboard=[[IB(text=btn, callback_data="sub:buy")]])
    await bot.send_message(user_id, text, reply_markup=markup, disable_web_page_preview=True)
    await repo.log_event(user_id, "subscription_offer_shown")


async def send_invoice(bot: Bot, user_id: int) -> None:
    offer = current_offer()
    if offer is None:
        await bot.send_message(user_id, t("unavailable"))
        return
    sc, s = cfg(), get_settings()
    title = str(sc.get("title") or "Подписка")[:32]
    description = str(sc.get("invoice_description") or title).format(days=offer.days)[:255]
    kw: dict[str, Any] = {}
    if offer.currency == "RUB":
        kw["provider_token"] = s.payment_provider_token
        if s.payment_receipts:
            # чек по 54-ФЗ формирует ЮKassa; ей нужен email покупателя
            kw.update(need_email=True, send_email_to_provider=True, provider_data=json.dumps({
                "receipt": {"items": [{
                    "description": title, "quantity": "1.00",
                    "amount": {"value": f"{offer.amount / 100:.2f}", "currency": "RUB"},
                    "vat_code": s.payment_vat_code, "payment_mode": "full_payment",
                    "payment_subject": "service",
                }]}
            }, ensure_ascii=False))
    await bot.send_invoice(
        user_id, title=title, description=description, payload=offer.payload,
        currency=offer.currency, prices=[LabeledPrice(label=title, amount=offer.amount)], **kw,
    )
    await repo.log_event(user_id, "subscription_invoice", currency=offer.currency, amount=offer.amount)


def check_payload(payload: str) -> bool:
    """Перед списанием: счёт соответствует текущей цене (цену могли поменять через /reload)."""
    offer = current_offer()
    return offer is not None and payload == offer.payload


async def on_paid(bot: Bot, user_id: int, payload: str, total_amount: int, currency: str,
                  telegram_charge_id: str, provider_charge_id: str | None) -> None:
    try:
        days = int(payload.split(":")[1])
    except (IndexError, ValueError):
        days = int(cfg().get("days") or 30)
    until = await repo.record_payment(user_id, total_amount, currency, days, telegram_charge_id, provider_charge_id)
    if until is None:
        return  # этот платёж уже учтён
    await repo.log_event(user_id, "subscription_paid", currency=currency, amount=total_amount, days=days)
    await schedule_reminders(user_id, until)
    await bot.send_message(user_id, t("paid", date=fmt_date(until)))
    u = await repo.get_user(user_id)
    who = f"@{u.username}" if u and u.username else f"id {user_id}"
    price = f"{total_amount // 100} ₽" if currency == "RUB" else f"{total_amount} ⭐"
    await notify.to_admins(bot, f"💳 Подписка на бизнес-аналитику: {u.first_name if u else ''} ({who}), "
                                f"{price}, до {fmt_date(until)}")


async def schedule_reminders(user_id: int, until: datetime) -> None:
    await repo.cancel_jobs(user_id, [JOB_EXPIRING, JOB_EXPIRED])
    before = timedelta(days=int(cfg().get("remind_before_days") or 3))
    now = utcnow()
    if until - before > now:
        await repo.schedule_at(user_id, JOB_EXPIRING, until - before)
    await repo.schedule_at(user_id, JOB_EXPIRED, until)


async def handle_job(bot: Bot, user_id: int, kind: str) -> None:
    sub = await repo.get_subscription(user_id)
    if sub is None:
        return
    offer = current_offer()
    markup = None
    if offer is not None:
        markup = InlineKeyboardMarkup(inline_keyboard=[[IB(
            text=t("renew_button", days=offer.days, price=offer.price_text), callback_data="sub:buy")]])
    if kind == JOB_EXPIRING and sub.paid_until > utcnow():
        await bot.send_message(user_id, t("expiring", date=fmt_date(sub.paid_until)), reply_markup=markup)
    elif kind == JOB_EXPIRED and sub.paid_until <= utcnow() + timedelta(minutes=1):
        await bot.send_message(user_id, t("expired"), reply_markup=markup)
        await repo.log_event(user_id, "subscription_expired")
