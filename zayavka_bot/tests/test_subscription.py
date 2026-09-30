"""Платная подписка на бизнес-новости: выключена без цены, Stars и рубли, продление, окончание."""
from __future__ import annotations

import asyncio
import json
from datetime import timedelta

import pytest
from sqlalchemy import update

from bot.config import get_settings
from bot.content import get_content
from bot.db import repo
from bot.db.models import ScheduledJob, utcnow
from bot.db.session import session
from bot.services import broadcast, scheduler
from bot.services import subscription as sub
from tests.conftest import ADMIN
from tests.fakebot import paid, pre_checkout
from tests.test_scenarios import tg  # noqa: F401


def _price(stars: int = 0, rub: int = 0) -> None:
    get_content().subscription.update(price_stars=stars, price_rub=rub)


async def test_hidden_without_price(tg):  # noqa: F811
    await tg.text(1001, "/subscribe")
    assert tg.texts(1001)[-1] == sub.t("unavailable")
    await tg.text(1001, "/menu")
    rows = tg.sent(1001)[-1].reply_markup.inline_keyboard
    assert all(b.callback_data != "menu:subs" for r in rows for b in r)


async def test_stars_purchase_flow(tg):  # noqa: F811
    _price(stars=150)
    uid = 1002
    await tg.text(uid, "/menu")
    rows = tg.sent(uid)[-1].reply_markup.inline_keyboard
    assert any(b.callback_data == "menu:subs" for r in rows for b in r)

    await tg.press(uid, "menu:subs")
    assert "150 ⭐ за 30 дней" in tg.texts(uid)[-1]
    await tg.press(uid, "sub:buy")
    inv = tg.sent(uid, "SendInvoice")[-1]
    assert (inv.currency, inv.prices[0].amount, inv.payload) == ("XTR", 150, "sub:30:XTR:150")
    assert not inv.provider_token

    await pre_checkout(tg, uid, inv.payload, 150)
    assert tg.sent(None, "AnswerPreCheckoutQuery")[-1].ok is True

    await paid(tg, uid, inv.payload, 150, "ch-1")
    s = await repo.get_subscription(uid)
    assert timedelta(days=29, hours=23) < s.paid_until - utcnow() <= timedelta(days=30)
    assert any("Оплата прошла" in t for t in tg.texts(uid))
    assert any("💳 Подписка" in t and "150 ⭐" in t for t in tg.texts(ADMIN))
    kinds = {j.kind for j in await repo.pending_jobs(uid, sub.JOB_EXPIRING)} | \
            {j.kind for j in await repo.pending_jobs(uid, sub.JOB_EXPIRED)}
    assert kinds == {sub.JOB_EXPIRING, sub.JOB_EXPIRED}

    # тот же платёж второй раз не продлевает; новый — продлевает от конца срока
    await paid(tg, uid, inv.payload, 150, "ch-1")
    assert (await repo.get_subscription(uid)).paid_until == s.paid_until
    await paid(tg, uid, inv.payload, 150, "ch-2")
    assert (await repo.get_subscription(uid)).paid_until - s.paid_until == timedelta(days=30)
    assert len(await repo.pending_jobs(uid, sub.JOB_EXPIRED)) == 1  # старые напоминания сняты

    await tg.press(uid, "menu:subs")
    assert tg.texts(uid)[-1].startswith("Подписка на бизнес-аналитику действует до")


async def test_price_changed_before_payment(tg):  # noqa: F811
    _price(stars=150)
    await pre_checkout(tg, 1003, "sub:30:XTR:100", 100)
    ans = tg.sent(None, "AnswerPreCheckoutQuery")[-1]
    assert ans.ok is False and ans.error_message == sub.t("price_changed")


async def test_rub_invoice_with_receipt(tg, monkeypatch):  # noqa: F811
    monkeypatch.setattr(get_settings(), "payment_provider_token", "381764678:TEST:1")
    _price(rub=990, stars=150)  # при токене ЮKassa продаём в рублях
    await tg.press(1004, "sub:buy")
    inv = tg.sent(1004, "SendInvoice")[-1]
    assert (inv.currency, inv.prices[0].amount, inv.provider_token) == ("RUB", 99000, "381764678:TEST:1")
    assert inv.need_email and inv.send_email_to_provider
    item = json.loads(inv.provider_data)["receipt"]["items"][0]
    assert item["amount"] == {"value": "990.00", "currency": "RUB"} and item["vat_code"] == 1


async def test_expiry_reminders_and_news_only_for_active(tg, monkeypatch):  # noqa: F811
    monkeypatch.setattr(broadcast, "PAUSE_SEC", 0)
    _price(stars=150)
    await paid(tg, 1005, "sub:30:XTR:150", 150, "ch-5")
    await paid(tg, 1006, "sub:30:XTR:150", 150, "ch-6")
    # у 1006 подписка кончилась
    from bot.db.models import Subscription

    async with session() as s:
        await s.execute(update(Subscription).where(Subscription.user_id == 1006)
                        .values(paid_until=utcnow() - timedelta(minutes=5)))
        await s.execute(update(ScheduledJob).values(run_at=utcnow() - timedelta(seconds=1)))
        await s.commit()
    tg.clear()
    for job in await repo.take_due_jobs():
        await scheduler.handle(tg.bot, job)
    assert any(t.startswith("Подписка на бизнес-аналитику заканчивается") for t in tg.texts(1005))
    assert any(t.startswith("Подписка на бизнес-аналитику закончилась") for t in tg.texts(1006))
    renew = tg.sent(1006)[-1].reply_markup.inline_keyboard[0][0]
    assert renew.callback_data == "sub:buy"

    # /news → превью → «Подписчикам (1)» → уходит только действующему
    tg.clear()
    await tg.text(ADMIN, "/news")
    await tg.text(ADMIN, "Новость недели")
    btn = [b for m in tg.sent(ADMIN) if m.reply_markup for r in m.reply_markup.inline_keyboard for b in r
           if (b.callback_data or "").startswith("bc:")]
    assert btn[0].text == "Подписчикам (1)"
    await tg.press(ADMIN, btn[0].callback_data)
    await asyncio.gather(*[t for t in asyncio.all_tasks() if t.get_name().startswith("broadcast-")])
    assert {m.chat_id for m in tg.sent(None, "CopyMessage")} - {ADMIN} == {1005}

    await tg.text(ADMIN, "/stats 7")
    assert "Подписка: активных 1 | оплат за период 2 на 0 ₽ + 300 ⭐" in tg.texts(ADMIN)[-1]


def test_yaml_validation(tmp_path):
    import shutil

    from bot.content import ContentError, load_content
    from tests.conftest import ROOT

    d = tmp_path / "content"
    shutil.copytree(ROOT / "content", d)
    p = d / "subscription.yaml"
    p.write_text(p.read_text(encoding="utf-8").replace("days: 30 ", "days: 0 "), encoding="utf-8")
    with pytest.raises(ContentError, match="days"):
        load_content(d)
