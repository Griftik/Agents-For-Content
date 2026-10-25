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
        key = re.sub(r"/[A-Z0-9]{8}(?=/|$)", "/{code}", re.sub(r"/\d{5,}", "/{id}", path.split("?")[0]))
        self.calls[f"{method.upper()} {key} {st}"] += 1
        if st >= 500:
            self.errors.append({"path": f"{method.upper()} {path}", "status": st, "body": str(body)[:200]})
        return st, body

    # ── сессия, аккаунт, профили ──
    async def session(self) -> tuple[int, dict]:
        return await self.call("post", C.POST_SESSION, json={})

    async def create_profile(self, uid: int, name: str, kind: str) -> tuple[int, dict]:
        return await self.call("post", C.POST_PROFILE, json={"user_id": uid, "name": name, "kind": kind})

    async def put_profile(self, pid: int, **fields: Any) -> tuple[int, dict]:
        return await self.call("put", C.PUT_PROFILE.format(pid=pid), json=fields)

    async def get_profile(self, pid: int) -> tuple[int, dict]:
        return await self.call("get", C.GET_PROFILE.format(pid=pid))

    async def delete_account(self, uid: int) -> tuple[int, dict]:
        return await self.call("delete", C.DELETE_ACCOUNT.format(uid=uid))

    # ── лента, план, решения ──
    async def feed(self, pid: int, date: str = "today", segment: str = "leisure", limit: int = 20) -> tuple[int, dict]:
        return await self.call("get", C.GET_FEED, params={"profile_id": pid, "date": date, "segment": segment, "limit": limit})

    async def plan(self, pid: int) -> tuple[int, dict]:
        return await self.call("get", C.GET_PLAN.format(pid=pid))

    async def decide(self, uid: int, pid: int, event: str, status: str, reason: str | None = None, day: str | None = None,
                     rating: int | None = None) -> tuple[int, dict]:
        body: dict = {"user_id": uid, "profile_id": pid, "event": event, "status": status}
        if reason:
            body["reason"] = reason
        if day:
            body["day"] = day
        if rating:
            body["rating"] = rating
        return await self.call("post", C.POST_DECISION, json=body)

    # ── приглашения (без изменений, user_id из сессии) ──
    async def invite_create(self, uid: int, slug: str, day: str | None) -> tuple[int, dict]:
        return await self.call("post", C.POST_INVITE, json={"user_id": uid, "event_slug": slug, "day": day, "kind": "event"})

    async def invite_view(self, code: str, uid: int) -> tuple[int, dict]:
        return await self.call("get", C.GET_INVITE.format(code=code), params={"user_id": uid})

    async def invite_open(self, code: str, uid: int, name: str = "") -> tuple[int, dict]:
        return await self.call("post", C.OPEN_INVITE.format(code=code), json={"user_id": uid, "name": name})

    async def invite_accept(self, code: str, uid: int, status: str, consent: bool = False, name: str = "") -> tuple[int, dict]:
        return await self.call("post", C.ACCEPT_INVITE.format(code=code), json={"user_id": uid, "status": status, "consent": consent, "name": name})

    async def growth(self) -> tuple[int, dict]:
        return await self.call("get", C.GET_GROWTH)
