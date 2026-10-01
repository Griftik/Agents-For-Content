"""Платная подписка на бизнес-аналитику: /subscribe, счёт, подтверждение и приём оплаты."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, PreCheckoutQuery

from bot.db import repo
from bot.services import subscription as sub

router = Router(name="subscription")


@router.message(Command("subscribe"))
async def cmd_subscribe(message: Message, bot: Bot) -> None:
    tg = message.from_user
    assert tg is not None
    await repo.upsert_user(tg.id, tg.username, tg.first_name)
    await sub.show(bot, tg.id)


@router.callback_query(F.data == "sub:buy")
async def cb_buy(cb: CallbackQuery, bot: Bot) -> None:
    await cb.answer()
    await sub.send_invoice(bot, cb.from_user.id)


@router.pre_checkout_query()
async def on_pre_checkout(q: PreCheckoutQuery) -> None:
    """Последняя проверка перед списанием (Telegram ждёт ответ до 10 секунд)."""
    if sub.check_payload(q.invoice_payload) and q.total_amount == sub.current_offer().amount:  # type: ignore[union-attr]
        await q.answer(ok=True)
    else:
        await q.answer(ok=False, error_message=sub.t("price_changed"))


@router.message(F.successful_payment)
async def on_paid(message: Message, bot: Bot) -> None:
    p = message.successful_payment
    assert p is not None and message.from_user is not None
    tg = message.from_user
    await repo.upsert_user(tg.id, tg.username, tg.first_name)  # счёт могли переслать — человека может не быть в базе
    await sub.on_paid(bot, message.from_user.id, p.invoice_payload, p.total_amount, p.currency,
                      p.telegram_payment_charge_id, p.provider_payment_charge_id)
