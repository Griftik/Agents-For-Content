"""Подпись Telegram: без неё API не отвечает; переход по ?startapp=… фиксирует источник."""
import time

import pytest

from bot.db import repo
from bot.webapp.auth import InitDataError, validate
from tests.appclient import TOKEN, init_data
from tests.test_scenarios import tg  # noqa: F401


def test_validate_ok_and_tampered():
    data = init_data(1, start_param="ig")
    u = validate(data, TOKEN, 3600)
    assert (u.id, u.start_param) == (1, "ig")
    with pytest.raises(InitDataError):
        validate(data.replace("U1", "U2"), TOKEN, 3600)          # подменили имя
    with pytest.raises(InitDataError):
        validate(init_data(1, token="999:OTHER"), TOKEN, 3600)    # подписано чужим ботом
    with pytest.raises(InitDataError):
        validate(init_data(1, auth_date=int(time.time()) - 7200), TOKEN, 3600)  # устарело
    with pytest.raises(InitDataError):
        validate("", TOKEN, 3600)


async def test_api_rejects_bad_signature(tg):  # noqa: F811
    r = await tg.app.client.post("/api/state", json={}, headers={"X-Init-Data": "user=%7B%22id%22%3A1%7D&hash=00"})
    assert r.status == 401
    r = await tg.app.client.post("/api/state", json={})
    assert r.status == 401


async def test_direct_app_link_records_source(tg):  # noqa: F811
    s = await tg.app.state(901, start_param="lecture_spb")
    assert s["screen"] == "welcome"
    u = await repo.get_user(901)
    assert (u.source, u.ref) == ("lecture", "spb")
    # источник первого входа не перезаписывается
    await tg.app.state(901, start_param="ig")
    assert (await repo.get_user(901)).source == "lecture"


async def test_static_served(tg):  # noqa: F811
    r = await tg.app.client.get("/")
    assert r.status == 200 and "telegram-web-app.js" in await r.text()
    assert r.headers["Cache-Control"] == "no-cache"
    r = await tg.app.client.get("/static/app.js")
    assert r.status == 200
