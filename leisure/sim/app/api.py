"""Клиент API приложения. Транспорт — FastAPI TestClient (в потоке: обработчики синхронные) или любая функция (для тестов каркаса)."""
from __future__ import annotations

import asyncio
import re
from collections import Counter
from typing import Any, Callable

from . import contract as C

Transport = Callable[[str, str, dict], tuple[int, Any]]
API_KEY = "sim-api-key"


def testclient_transport() -> Transport:
    from fastapi.testclient import TestClient

    from leisure.api.main import app

    client = TestClient(app)

    def call(method: str, path: str, kw: dict) -> tuple[int, Any]:
        headers = {"X-API-Key": API_KEY, **kw.pop("headers", {})}
        if method == "delete" and "json" in kw:                  # httpx.delete не принимает тело
            r = client.request("DELETE", path, headers=headers, **kw)
        else:
            r = getattr(client, method)(path, headers=headers, **kw)
        try:
            return r.status_code, r.json()
        except Exception:  # noqa: BLE001
            return r.status_code, {}

    return call


class AppApi:
    def __init__(self, transport: Transport | None = None) -> None:
        self.transport = transport or testclient_transport()
        self.calls: Counter = Counter()
        self.errors: list[dict] = []                         # ответы 5xx

    async def call(self, method: str, path: str, **kw: Any) -> tuple[int, Any]:
        st, body = await asyncio.to_thread(self.transport, method, path, dict(kw))
        key = re.sub(r"/\d{5,}", "/{id}", re.sub(r"(/api/invites/)[A-Z0-9]{8}(?=/|$)", r"\1{code}", path.split("?")[0]))
        self.calls[f"{method.upper()} {key} {st}"] += 1
        if st >= 500:
            self.errors.append({"path": f"{method.upper()} {path}", "status": st, "body": str(body)[:200]})
        return st, body

    # ── сессия, аккаунт, профили ──
    async def session(self) -> tuple[int, dict]:
        return await self.call("post", C.POST_SESSION, json={})

    async def put_profile(self, uid: int, **fields: Any) -> tuple[int, dict]:
        return await self.call("put", C.PUT_PROFILE.format(uid=uid), json=fields)

    async def get_profile(self, uid: int) -> tuple[int, dict]:
        return await self.call("get", C.GET_PROFILE.format(uid=uid))

    async def delete_profile(self, uid: int) -> tuple[int, dict]:
        return await self.call("delete", C.DELETE_PROFILE.format(uid=uid))

    async def profiles(self, uid: int) -> tuple[int, dict]:
        return await self.call("get", C.PROFILES, params={"user_id": uid})

    async def create_profile(self, uid: int, name: str, kind: str) -> tuple[int, dict]:
        return await self.call("post", C.PROFILES, json={"user_id": uid, "name": name, "kind": kind})

    # ── лента, план, решения ──
    async def feed(self, uid: int, date: str = "today", segment: str = "all", limit: int | None = 20) -> tuple[int, dict]:
        params: dict = {"user_id": uid, "date": date, "segment": segment}
        if limit is not None:
            params["limit"] = limit
        return await self.call("get", C.GET_FEED, params=params)

    async def plan(self, uid: int) -> tuple[int, dict]:
        return await self.call("get", C.GET_PLAN.format(uid=uid))

    async def decisions(self, uid: int) -> tuple[int, list]:
        return await self.call("get", C.GET_DECISIONS.format(uid=uid))

    async def decide(self, uid: int, event: str, status: str, reason: str | None = None, day: str | None = None,
                     rating: int | None = None) -> tuple[int, dict]:
        body: dict = {"user_id": uid, "event": event, "status": status}
        if reason:
            body["reason"] = reason
        if day:
            body["day"] = day
        if rating:
            body["rating"] = rating
        return await self.call("post", C.POST_DECISION, json=body)

    # ── приглашения (user_id из сессии) ──
    async def invite_create(self, uid: int, slug: str, day: str | None, kind: str = "event") -> tuple[int, dict]:
        body: dict = {"user_id": uid, "kind": kind}
        if kind == "event":
            body.update(event_slug=slug, day=day)
        return await self.call("post", C.POST_INVITE, json=body)

    async def invite_view(self, code: str, uid: int) -> tuple[int, dict]:
        return await self.call("get", C.GET_INVITE.format(code=code), params={"user_id": uid})

    async def invite_open(self, code: str, uid: int, name: str = "", username: str = "") -> tuple[int, dict]:
        return await self.call("post", C.OPEN_INVITE.format(code=code), json={"user_id": uid, "name": name, "username": username})

    async def invite_accept(self, code: str, uid: int, status: str, consent: bool = False, name: str = "", username: str = "") -> tuple[int, dict]:
        return await self.call("post", C.ACCEPT_INVITE.format(code=code),
                               json={"user_id": uid, "status": status, "consent": consent, "name": name, "username": username})

    async def growth(self) -> tuple[int, dict]:
        return await self.call("get", C.GET_GROWTH)
