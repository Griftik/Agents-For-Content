"""Клиент мини-приложения для тестов: настоящий aiohttp-сервер, initData с подписью Telegram."""
from __future__ import annotations

import json
import time

from aiohttp.test_utils import TestClient, TestServer

from bot.webapp.auth import sign
from bot.webapp.server import create_app

TOKEN = "123456:TEST"


def init_data(uid: int, start_param: str | None = None, username: str | None = None,
              token: str = TOKEN, auth_date: int | None = None) -> str:
    fields = {"auth_date": str(auth_date or int(time.time())), "query_id": "AAE",
              "user": json.dumps({"id": uid, "first_name": f"U{uid}", "username": username}, separators=(",", ":"))}
    if start_param:
        fields["start_param"] = start_param
    return sign(fields, token)


class MiniApp:
    def __init__(self, bot) -> None:
        self.client = TestClient(TestServer(create_app(bot)))

    async def __aenter__(self) -> "MiniApp":
        await self.client.start_server()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.client.close()

    async def raw(self, path: str, uid: int, body: dict | None = None, **kw):
        return await self.client.post(path, json=body or {}, headers={"X-Init-Data": init_data(uid, **kw)})

    async def state(self, uid: int, **kw) -> dict:
        r = await self.raw("/api/state", uid, **kw)
        assert r.status == 200, await r.text()
        return await r.json()

    async def act(self, uid: int, type: str, **data) -> dict:  # noqa: A002
        r = await self.raw("/api/action", uid, {"type": type, **data})
        assert r.status == 200, await r.text()
        return await r.json()
