"""Согласие галочкой на первом экране приложения: не стоит заранее, без неё заявка не начинается."""
from bot.content import get_content
from bot.db import repo
from tests.test_scenarios import HOT, lead, tg  # noqa: F401


async def test_welcome_screen(tg):  # noqa: F811
    s = await tg.app.state(801)
    c = get_content()
    assert s["screen"] == "welcome" and s["consent"] is False
    assert s["consent_label"] == "Согласен на обработку данных"
    assert s["more"] == c.t("consent_policy_button")
    assert s["links"]["consent"] == "https://example.com/consent"
    assert s["links"]["privacy"] == "https://example.com/privacy"


async def test_start_without_box_only_toast(tg):  # noqa: F811
    s = await tg.app.act(802, "start")
    assert s["screen"] == "welcome" and s["toast"] == get_content().t("consent_needed")
    assert tg.sent(802) == []  # в чат ничего
    assert (await repo.get_user(802)).stage == "welcome"


async def test_toggle_and_start(tg):  # noqa: F811
    s = await tg.app.act(803, "consent", value=True)
    assert s["consent"] is True and (await repo.get_user(803)).consent_at is not None
    s = await tg.app.act(803, "consent", value=False)
    assert s["consent"] is False and (await repo.get_user(803)).consent_at is None
    await tg.app.act(803, "consent", value=True)
    s = await tg.app.act(803, "start")
    assert s["screen"] == "question" and s["question"]["code"] == "role"


async def test_consent_carried_to_lead_and_cleared_on_delete(tg):  # noqa: F811
    await lead(tg, 804, HOT)
    u = await repo.get_user(804)
    assert (await repo.get_lead(804)).consent_at == u.consent_at
    s = await tg.app.act(804, "delete")
    assert s["screen"] == "welcome" and s["consent"] is False
    assert (await repo.get_user(804)).consent_at is None
