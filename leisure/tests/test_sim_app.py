"""Каркас симулятора для приложения (docs/PIVOT-PWA.md): клиент API, онбординг по нажатиям FLOW-ONBOARDING, фейковый push. Без БД и без бэкенда ТЗ-12:
сервер заменён заглушкой по предположенному контракту (sim/app/contract.py)."""
import asyncio
import dataclasses
import random
import sys
import types
from datetime import datetime, timezone

from leisure.core.catalog import propose_interests, proposed_categories
from leisure.sim import personas as P
from leisure.sim.actors import Findings
from leisure.sim.app import push as pushmod
from leisure.sim.app.api import AppApi
from leisure.sim.app.driver import AppDriver
from leisure.sim.app.user import AppUser

SEED = 20261024
NOW = datetime(2026, 10, 21, 10, 0, tzinfo=timezone.utc)


class Stub:
    """Сервер по предположенному контракту: гостевая сессия, профиль, решения, подборка, push-подписки, входящие."""

    def __init__(self, events: list[dict]) -> None:
        self.events = events
        self.next_uid = 7_000_000
        self.profiles: dict[int, dict] = {}
        self.decisions: list[dict] = []
        self.subs: list[dict] = []
        self.notes: list[dict] = []
        self.log: list[str] = []

    def __call__(self, method: str, path: str, kw: dict):
        self.log.append(f"{method.upper()} {path}")
        body = kw.get("json") or {}
        if method == "post" and path == "/api/session":
            self.next_uid += 1
            self.profiles[self.next_uid] = {"consent": False, "onboarded": False, "values": {}, "interests": {}, "params": {}}
            return 200, {"user_id": self.next_uid, "token": "tok"}
        if path.startswith("/api/profile/"):
            uid = int(path.rsplit("/", 1)[1])
            p = self.profiles[uid]
            if method == "put":
                for k, v in body.items():
                    if k in ("values", "interests", "params"):
                        p[k].update(v)
                    else:
                        p[k] = v
                if body.get("values"):
                    p["interests"] = propose_interests(p["values"])
            return 200, {"user_id": uid, **p}
        if method == "post" and path == "/api/decisions":
            self.decisions.append(body)
            return 200, {"event_slug": body["event"], "status": body["status"], "reason": body.get("reason"), "day": body.get("day"), "rating": body.get("rating")}
        if method == "get" and path.endswith("/preview"):
            return 200, {"items": [{"event": {"id": e["id"]}, "day": "2026-10-24", "days": ["2026-10-24", "2026-10-25"], "slot": "день"} for e in self.events[:5]],
                         "horizon": []}
        if method == "post" and path == "/api/push/subscriptions":
            self.subs.append(body)
            return 201, {}
        if method == "get" and path.startswith("/api/notifications/"):
            return 200, self.notes
        if method == "post" and "/read" in path:
            return 200, {}
        return 404, {"detail": path}


def _events(n: int = 8) -> list[dict]:
    return [{"id": f"e{i}", "slug": f"ev-{i}", "category": "Театр", "tags": ["театр"], "kind": "событие", "price_from": 1000, "aesthetics": 4} for i in range(n)]


def _user(**over) -> tuple[AppUser, Stub, AppDriver]:
    p = dataclasses.replace(P.generate(50, SEED)[0], abandon_step=None, misclick_step=None, **over)
    stub = Stub(_events())
    f = Findings()
    drv = AppDriver(AppApi(stub), pushmod.FakePush(lambda: NOW), lambda: NOW, {e["id"]: e for e in stub.events}, lambda t: 0, f)
    return AppUser(p=p, rng=random.Random(1), E=0.8), stub, drv


def _targets_equal_prefill(p) -> dict:
    return {c: v for c, v in propose_interests(p.value_w).items()}


def test_push_permission_share_is_in_expected_range():
    ps = P.generate(50, SEED)
    mean = sum(pushmod.p_grant_push(p) for p in ps) / len(ps)
    assert 0.4 <= mean <= 0.6, mean                               # ориентир поворотного ТЗ: 40–60 % дают разрешение
    assert all(0 < pushmod.p_open_push(p, k) < 1 for p in ps for k in pushmod.OPEN_BASE)


def test_onboarding_tap_counts_follow_flow_onboarding():
    # «ничего не меняю»: согласие 1 + «Начать» 1 + пять ценностей + «Показать подборку» = 8, с бюджетом строкой — 9
    u, stub, drv = _user(budget_on_step=False)
    u.p.interest_targets.update(_targets_equal_prefill(u.p))
    assert asyncio.run(drv.onboard(u)) == "completed"
    assert u.onb["taps_total"] == 8 and u.onb["interest_edits"] == 0
    assert stub.profiles[u.uid]["onboarded"] and stub.profiles[u.uid]["consent"]
    u2, _, drv2 = _user(budget_on_step=True, budget=2500)
    u2.p.interest_targets.update(_targets_equal_prefill(u2.p))
    assert asyncio.run(drv2.onboard(u2)) == "completed" and u2.onb["taps_total"] == 9
    # типичный: три убранных лишних направления → 12
    u3, _, drv3 = _user(budget_on_step=True, budget=1000)
    pre = _targets_equal_prefill(u3.p)
    shown = proposed_categories(dict(u3.p.value_w))
    u3.p.interest_targets.update(pre)
    for c in shown[:3]:
        u3.p.interest_targets[c] = 0
    u3 = dataclasses.replace(u3, p=dataclasses.replace(u3.p, max_interest_taps=9))
    assert asyncio.run(drv3.onboard(u3)) == "completed" and u3.onb["taps_total"] == 12, u3.onb


def test_abandon_leaves_profile_not_onboarded():
    u, stub, drv = _user()
    u.p = dataclasses.replace(u.p, abandon_step="values", abandon_sub=2)
    assert asyncio.run(drv.onboard(u)) == "abandoned"
    assert u.status == "abandoned" and not stub.profiles[u.uid]["onboarded"] and u.onb["abandoned_at"] == "values"


def test_digest_visit_posts_decisions_and_push_prompt_subscribes():
    u, stub, drv = _user(budget_on_step=False)
    u.p.interest_targets.update(_targets_equal_prefill(u.p))
    asyncio.run(drv.onboard(u))
    u.p = dataclasses.replace(u.p, decisive=1.0, view_range=(5, 5))
    rec = asyncio.run(drv.visit_digest(u, origin="first"))
    assert rec["opened"] and rec["cards"] == 5 and len(stub.decisions) == rec["decisions"] and rec["decisions"] > 0
    assert all(d["user_id"] == u.uid and d["event"].startswith("e") for d in stub.decisions)
    # разрешение на push: подписка уходит на сервер и регистрируется в фейковом канале
    u.p = dataclasses.replace(u.p, engagement=1.0, max_interest_taps=13)
    random.seed(0)
    for seed in range(40):
        u.rng = random.Random(seed)
        u.push = {"asks": 0, "granted": None, "sub": None, "moments": []}
        if asyncio.run(drv.push_prompt(u, "after_digest")):
            break
    assert u.push["granted"] is True and stub.subs and stub.subs[-1]["endpoint"] in drv.push.owner


def test_inbox_feedback_rating_goes_through_decisions_api():
    u, stub, drv = _user(budget_on_step=False)
    u.p.interest_targets.update(_targets_equal_prefill(u.p))
    asyncio.run(drv.onboard(u))
    u.p = dataclasses.replace(u.p, p_rate=1.0, p_attend=1.0)
    stub.notes = [{"id": 1, "kind": "feedback", "title": "Как прошло?", "body": "Событие", "url": "/e/ev-1", "read": False},
                  {"id": 2, "kind": "digest", "title": "Подборка готова", "body": "", "url": "/", "read": True}]
    out = asyncio.run(drv.visit_inbox(u, via_push=True))
    assert out["seen"] == 1 and out["read"] == 1 and out["rated"] == 1
    assert stub.decisions[-1]["status"] == "иду" and 1 <= stub.decisions[-1]["rating"] <= 5 and stub.decisions[-1]["event"] == "ev-1"


def test_fake_push_contract_and_install():
    now = lambda: NOW  # noqa: E731
    fp = pushmod.FakePush(now)
    fp.subscribe(5, "https://push.sim.invalid/a")
    ok = fp.webpush({"endpoint": "https://push.sim.invalid/a", "keys": {}}, data='{"title": "Подборка готова", "body": "5 событий", "url": "/", "kind": "digest"}',
                    vapid_private_key="k", vapid_claims={"sub": "mailto:x"})
    assert ok.status_code == 201 and fp.delivered_to(5)[0].kind == "digest"
    fp.webpush({"endpoint": "https://push.sim.invalid/a"}, data='{"title": "' + "я" * 41 + '", "body": "x"}', vapid_private_key="k")
    assert any("длина push" in e for e in fp.contract_errors)
    fp.revoke("https://push.sim.invalid/a")
    try:
        fp.webpush({"endpoint": "https://push.sim.invalid/a"}, data="{}", vapid_private_key="k")
        raise AssertionError("ожидали 410")
    except pushmod.WebPushException as e:
        assert e.response.status_code == 410
    mod = types.ModuleType("leisure._fake_push_user")
    mod.webpush = lambda *a, **k: "real"
    sys.modules[mod.__name__] = mod
    try:
        saved = pushmod.install(fp)
        assert mod.webpush == fp.webpush
        pushmod.uninstall(saved)
        assert mod.webpush() == "real"
    finally:
        del sys.modules[mod.__name__]
