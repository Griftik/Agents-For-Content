"""Важное из канала и новости подписчикам."""
from __future__ import annotations

import asyncio

import pytest

from bot.db import repo
from bot.services import broadcast
from tests.conftest import ADMIN
from tests.fakebot import channel_post, forward_from_channel
from tests.test_scenarios import HOT, WARM, lead, tg  # noqa: F401


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(broadcast, "PAUSE_SEC", 0)


async def _finish_broadcasts() -> None:
    tasks = [t for t in asyncio.all_tasks() if t.get_name().startswith("broadcast-")]
    await asyncio.gather(*tasks)


async def _people(tg):
    await lead(tg, 901, WARM, phone="+79160000901")
    await lead(tg, 902, HOT, phone="+79160000902")
    await tg.text(903, "/start")               # дал согласие, заявку не закончил
    await tg.app.act(903, "consent", value=True)
    await tg.text(904, "/start")               # без согласия — не получает ничего
    await lead(tg, 905, WARM, phone="+79160000905")
    await tg.app.act(905, "notify", value=False)  # выключил сообщения


def _bc_buttons(tg):
    m = [m for m in tg.sent(ADMIN) if m.reply_markup and any(
        (b.callback_data or "").startswith("bc:") for r in m.reply_markup.inline_keyboard for b in r)][-1]
    return [b for r in m.reply_markup.inline_keyboard for b in r]


async def test_channel_post_with_tag_goes_to_everyone_after_one_tap(tg):  # noqa: F811
    await _people(tg)
    tg.clear()
    await channel_post(tg, "neurostrategy", "Большой разбор рынка #важное", message_id=77)
    buttons = _bc_buttons(tg)
    assert [b.text for b in buttons] == ["Всем в боте (3)", "Только лидам (2)", "Не рассылать"]
    assert tg.sent(ADMIN, "CopyMessage")  # превью поста

    await tg.press(ADMIN, buttons[0].callback_data)
    await _finish_broadcasts()
    got = {m.chat_id for m in tg.sent(None, "CopyMessage")} - {ADMIN}
    assert got == {901, 902, 903}
    copy = [m for m in tg.sent(901, "CopyMessage")][-1]
    assert copy.reply_markup.inline_keyboard[0][0].url == "https://t.me/neurostrategy/77"
    assert copy.reply_markup.inline_keyboard[1][0].callback_data == "book"
    assert any("доставлено 3, не доставлено 0" in t for t in tg.texts(ADMIN))

    # повторное нажатие не запускает вторую рассылку
    tg.clear()
    await tg.press(ADMIN, buttons[0].callback_data)
    assert tg.sent(901, "CopyMessage") == []


async def test_post_without_tag_or_foreign_channel_ignored(tg):  # noqa: F811
    await channel_post(tg, "neurostrategy", "Обычный пост")
    await channel_post(tg, "other_channel", "Чужой #важное")
    assert tg.sent(ADMIN) == []


async def test_forwarded_post_to_leads_only_and_blocked_user(tg):  # noqa: F811
    await _people(tg)
    tg.session.blocked.add(902)
    tg.clear()
    await forward_from_channel(tg, ADMIN, "neurostrategy", 55)
    buttons = _bc_buttons(tg)
    await tg.press(ADMIN, buttons[1].callback_data)  # только лидам
    tg.session.blocked.add(902)
    await _finish_broadcasts()
    got = {m.chat_id for m in tg.sent(None, "CopyMessage")} - {ADMIN}
    assert got == {901, 902}  # 903 не лид; 902 попытались, но он заблокировал бота
    assert (await repo.get_user(902)).nurture_enabled is False
    assert any("доставлено 1, не доставлено 1" in t for t in tg.texts(ADMIN))


async def test_cancel(tg):  # noqa: F811
    await _people(tg)
    await channel_post(tg, "neurostrategy", "#важное")
    buttons = _bc_buttons(tg)
    tg.clear()
    await tg.press(ADMIN, buttons[-1].callback_data)
    await tg.press(ADMIN, buttons[0].callback_data)
    await _finish_broadcasts()
    assert {m.chat_id for m in tg.sent(None, "CopyMessage")} == set()
