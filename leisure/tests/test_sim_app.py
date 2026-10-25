"""Каркас симулятора приложения (версия 2) без БД: клиент API на заглушке по контракту README «Продукт без Telegram», онбординг по нажатиям
FLOW-ONBOARDING (8–9 при «ничего не меняю», 12 у типичного), лента и решения, «сходил» с оценкой из плана, модель открытий, пробы обучения."""
import asyncio
import dataclasses
import random
from datetime import datetime, timezone

from leisure.core.catalog import propose_interests, proposed_categories
from leisure.sim import personas as P
from leisure.sim.app import contract as C
from leisure.sim.app.api import AppApi
from leisure.sim.app.driver import AppDriver, is_evening_window, open_times, opens_per_week
from leisure.sim.app.user import AppUser
from leisure.sim.common import START, Findings

SEED = 20261024
NOW = datetime(2026, 10, 21, 10, 0, tzinfo=timezone.utc)


class Stub:
    """Сервер по контракту v2: гостевая сессия, профиль первым PUT с согласием, дополнительные профили, лента, план с past, решения."""

    def __init__(self, events: list[dict]) -> None:
        self.events = events
        self.next_uid = 10**12
        self.profiles: dict[int, dict] = {}
        self.decisions: list[dict] = []
        self.log: list[str] = []
        self.past: list[dict] = []

    def _profile(self, uid: int) -> dict:
        return self.profiles.setdefault(uid, {"user_id": uid, "account_id": uid, "kind": "self", "name": "", "has_consent": False, "onboarded": False,
                                              "values": {}, "interests": {}, "params": {}})

    def __call__(self, method: str, path: str, kw: dict):
        self.log.append(f"{method.upper()} {path}")
        body = kw.get("json") or {}
        params = kw.get("params") or {}
        if method == "post" and path == C.POST_SESSION:
            self.next_uid += 1
            return 200, {"user_id": self.next_uid}
        if path.startswith("/api/profile/"):
            uid = int(path.rsplit("/", 1)[1])
            if method == "get":
                return (200, self.profiles[uid]) if uid in self.profiles else (404, {"detail": "профиль не найден"})
            if method == "delete":
                return 200, {"removed": self.profiles.pop(uid, None) is not None}
            p = self._profile(uid)
            for k, v in body.items():
                if k in ("values", "interests", "params"):
                    p[k].update(v)
                elif k == "consent":
                    p["has_consent"] = p["has_consent"] or bool(v)
                else:
                    p[k] = v
            if body.get("values"):
                p["interests"] = propose_interests(p["values"])
            return 200, p
        if path == C.PROFILES and method == "post":
            owner = self._profile(int(body["user_id"]))
            if not owner["has_consent"]:
                return 409, {"detail": "consent_required"}
            self.next_uid += 1
            p = self._profile(self.next_uid)
            p.update(kind=body["kind"], name=body["name"], account_id=owner["account_id"], has_consent=True)
            acc = [x for x in self.profiles.values() if x["account_id"] == owner["account_id"]]
            return 200, {"account_id": owner["account_id"], "email": None,
                         "profiles": [{"user_id": x["user_id"], "name": x["name"], "kind": x["kind"], "onboarded": x["onboarded"], "is_main": x["user_id"] == owner["account_id"]} for x in acc]}
        if method == "post" and path == C.POST_DECISION:
            if body["status"] in (C.WENT, C.SKIPPED) and body.get("day") and body["day"] > "2026-10-21":   # «сходил» только после дня события
                return 400, {"detail": "рано"}
            self.decisions.append(body)
            out = {"event_id": body["event"], "event_slug": body["event"], "status": body["status"], "reason": body.get("reason"), "day": body.get("day"), "rating": body.get("rating")}
            if body.get("rating") and body["rating"] >= 4:
                out["ref_ask"] = {"url": "https://web.example/?ref=ABCDEFGH", "share_text": "Попробуй: https://web.example/?ref=ABCDEFGH"}
            return 200, out
        if method == "get" and path == C.GET_FEED:
            uid = int(params["user_id"])
            if not self.profiles.get(uid, {}).get("onboarded"):
                return 409, {"detail": "not_onboarded"}
            return 200, {"user_id": uid, "date": params.get("date"), "days": ["2026-10-24"], "today": "2026-10-21", "segment": params.get("segment"), "travel_minutes": 40,
                         "items": [{"event": e, "day": "2026-10-24", "days": ["2026-10-24", "2026-10-25"], "score": 80 - i, "why": [], "can_make_it": True, "links": {}}
                                   for i, e in enumerate(self.events[:5])]}
        if method == "get" and path.startswith("/api/plan/"):
            return 200, {"weekend": [], "today": "2026-10-21", "title": "План", "days": {}, "horizon": [], "past": self.past, "text": ""}
        return 404, {"detail": path}


def _events(n: int = 8) -> list[dict]:
    return [{"id": f"e{i}", "slug": f"ev-{i}", "title": f"Событие {i}", "category": "Театр", "tags": ["театр"], "kind": "событие", "price_from": 1000,
             "aesthetics": 4, "dates": ["2026-10-24"]} for i in range(n)]


def _user(**over) -> tuple[AppUser, Stub, AppDriver]:
    p = dataclasses.replace(P.generate(50, SEED)[0], abandon_step=None, misclick_step=None, **over)
    stub = Stub(_events())
    drv = AppDriver(AppApi(stub), lambda: NOW, {e["id"]: e for e in stub.events}, lambda t: 0, Findings(), SEED)
    return AppUser(p=p, rng=random.Random(1), E=0.8), stub, drv


def _prefill(p) -> dict:
    return dict(propose_interests(p.value_w))


def test_onboarding_tap_counts_follow_flow_onboarding():
    u, stub, drv = _user(budget_on_step=False)                       # «ничего не меняю»: галочка, «Начать», пять ценностей, «Показать подборку» = 8
    u.p.interest_targets.update(_prefill(u.p))
    assert asyncio.run(drv.onboard(u)) == "completed" and u.onb["taps_total"] == 8 and u.onb["interest_edits"] == 0
    prof = stub.profiles[u.uid]
    assert prof["onboarded"] and prof["has_consent"] and sorted(v for v, w in prof["values"].items() if w == 5) == sorted(u.p.top_values)
    assert stub.log[:3] == [f"POST {C.POST_SESSION}", f"PUT /api/profile/{u.uid}", f"PUT /api/profile/{u.uid}"]
    u2, _, drv2 = _user(budget_on_step=True, budget=2500)             # с бюджетом строкой — 9
    u2.p.interest_targets.update(_prefill(u2.p))
    assert asyncio.run(drv2.onboard(u2)) == "completed" and u2.onb["taps_total"] == 9
    u3, _, drv3 = _user(budget_on_step=True, budget=1000, max_interest_taps=9)     # типичный: убрал три лишних направления — 12
    u3.p.interest_targets.update(_prefill(u3.p))
    for c in proposed_categories(dict(u3.p.value_w))[:3]:
        u3.p.interest_targets[c] = 0
    assert asyncio.run(drv3.onboard(u3)) == "completed" and u3.onb["taps_total"] == 12, u3.onb


def test_abandon_and_second_profile():
    u, stub, drv = _user()
    u.p = dataclasses.replace(u.p, abandon_step="values", abandon_sub=2)
    assert asyncio.run(drv.onboard(u)) == "abandoned" and u.status == "abandoned" and not stub.profiles[u.uid]["onboarded"]
    u2, stub2, drv2 = _user(budget_on_step=False)
    u2.p.interest_targets.update(_prefill(u2.p))
    asyncio.run(drv2.onboard(u2))
    assert asyncio.run(drv2.add_second_profile(u2, "child"))
    second = u2.profiles[1]
    assert second.pid != u2.uid and stub2.profiles[second.pid]["kind"] == "child" and stub2.profiles[second.pid]["onboarded"]
    assert second.p.archetype != u2.p.archetype and second.name == "Ребёнок"


def test_open_app_decides_through_api_and_marks_past_with_rating():
    u, stub, drv = _user(budget_on_step=False)
    u.p.interest_targets.update(_prefill(u.p))
    asyncio.run(drv.onboard(u))
    u.p = u.profiles[0].p = dataclasses.replace(u.p, decisive=1.0, view_range=(5, 5), p_rate=1.0, p_attend=1.0)   # вкус читается из профиля
    stub.past = [{"event": stub.events[7], "status": C.GO, "day": "2026-10-18", "rating": None, "links": {}}]
    rec = asyncio.run(drv.open_app(u))
    assert rec["cards"] == 5 and rec["decisions"] >= 1 and rec["day"] in C.DAYS and rec["segment"] in C.SEGMENTS
    statuses = {d["status"] for d in stub.decisions}
    assert statuses <= {C.GO, C.NOT_MINE, C.WENT, C.SKIPPED} and all(d["user_id"] == u.uid for d in stub.decisions)
    rec2 = {"went": 0, "rated": 0, "cycle": 0}
    asyncio.run(drv.mark_past(u, u.prof, rec2))                                    # вкладка «План»: прошедшее «иду» → «сходил» с оценкой (один раз)
    assert rec["went"] + rec2["went"] == 1 and any(d["status"] == C.WENT and 1 <= d["rating"] <= 5 and d["event"] == "e7" for d in stub.decisions)


def test_open_times_model_and_evening_window():
    ps = P.generate(50, SEED)
    per_week = [opens_per_week(p) for p in ps]
    assert all(1 <= n <= 5 for n in per_week) and 2 <= sum(per_week) / len(per_week) <= 4
    t1, t2 = open_times(ps[0], SEED, 1, START), open_times(ps[0], SEED, 1, START)
    assert t1 == t2 and len(t1) == opens_per_week(ps[0]) and all(START <= t for t in t1)
    from zoneinfo import ZoneInfo

    hours = [t.astimezone(ZoneInfo(p.tz)).hour for p in ps for t in open_times(p, SEED, 0, START)]
    evening, day = sum(1 for h in hours if h >= 17), sum(1 for h in hours if h < 17)
    assert evening / 7 > day / 9                                                  # в вечерний час открывают чаще, чем в дневной
    assert is_evening_window(datetime(2026, 10, 22, 18, 0)) and not is_evening_window(datetime(2026, 10, 24, 18, 0))
