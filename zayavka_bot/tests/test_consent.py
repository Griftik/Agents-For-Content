"""Согласие галочкой на первом экране: не стоит заранее, без неё заявка не начинается."""
from bot.content import get_content
from bot.db import repo
from tests.conftest import ADMIN  # noqa: F401
from tests.test_scenarios import HOT, fill, tg  # noqa: F401


def _welcome(tg, uid):
    c = get_content()
    return [m for m in tg.sent(uid) if m.text == c.t("welcome")][-1]


async def test_welcome_has_unchecked_box_and_policy_link(tg):  # noqa: F811
    await tg.text(801, "/start")
    rows = _welcome(tg, 801).reply_markup.inline_keyboard
    c = get_content()
    assert rows[0][0].text == c.t("consent_off") and rows[0][0].callback_data == "consent:toggle"
    assert rows[0][1].url == "https://example.com/consent"
    assert rows[1][0].callback_data == "app:start"


async def test_start_without_box_shows_toast_only(tg):  # noqa: F811
    await tg.text(802, "/start")
    tg.clear()
    await tg.press(802, "app:start")
    toast = tg.sent(None, "AnswerCallbackQuery")[-1]
    assert toast.text == get_content().t("consent_needed")
    assert tg.sent(802) == []  # ни одного нового сообщения в чат
    assert (await repo.get_user(802)).stage == "welcome"


async def test_toggle_and_start(tg):  # noqa: F811
    c = get_content()
    await tg.text(803, "/start")
    await tg.press(803, "consent:toggle")
    assert (await repo.get_user(803)).consent_at is not None
    edit = tg.sent(None, "EditMessageReplyMarkup")[-1]
    assert edit.reply_markup.inline_keyboard[0][0].text == c.t("consent_on")
    await tg.press(803, "consent:toggle")  # сняли
    assert (await repo.get_user(803)).consent_at is None
    await tg.press(803, "consent:toggle")
    await tg.press(803, "app:start")
    assert (await repo.get_user(803)).stage == "q:role"


async def test_consent_carried_to_lead_and_cleared_on_delete(tg):  # noqa: F811
    await tg.text(804, "/start")
    await fill(tg, 804, HOT)
    u = await repo.get_user(804)
    await tg.contact(804, "+79161234567")
    assert (await repo.get_lead(804)).consent_at == u.consent_at
    await tg.press(804, "company:skip")
    await tg.press(804, "del:yes")
    assert (await repo.get_user(804)).consent_at is None
    # вернулся — снова галочка
    tg.clear()
    await tg.text(804, "/start")
    assert _welcome(tg, 804).reply_markup.inline_keyboard[0][0].callback_data == "consent:toggle"
