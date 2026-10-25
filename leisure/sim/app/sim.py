"""Прогон симуляции для приложения, версия 2: люди сами открывают приложение в случайные моменты (1–5 раз в неделю, чаще вечером четверга и пятницы),
выбирают день и направление, смотрят ленту и решают «Иду» / «Не моё»; после даты события отмечают «сходил / не сходил» с оценкой. Рассылок и
уведомлений нет. Часы, очередь событий и подмена «сейчас» — как у бота. КАРКАС: прогон и сборка результатов в формат report.py — после того
как бэкенд сдаст ленту и профили (см. TODO внизу)."""
from __future__ import annotations

import contextlib
import heapq
import random
import statistics
from datetime import datetime, timedelta

from ..actors import Findings
from ..personas import Persona
from ..runner import FRI0, PRIO_USER, START, Clock, at_local, cycle_of
from . import contract as C
from .api import API_KEY, AppApi, Transport
from .driver import AppDriver, open_times
from .user import AppUser

SECOND_PROFILE_SHARE = 0.2            # у 20 % персон второй профиль (ребёнок или родитель)
N_NEG_PROBES, N_POS_PROBES = 6, 6     # проб персонального обучения: «три не моё» по категории и «три сходил, 5»


@contextlib.contextmanager
def patched_app(clock: Clock):
    """Часы симуляции в продукте и ключ API на время прогона. Код продукта не меняется."""
    from leisure import settings
    from leisure.api import invites as inv_service
    from leisure.api import services

    class SimDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            t = clock.now
            return t.astimezone(tz) if tz else t.replace(tzinfo=None)

    saved = (services.utcnow, services.datetime, inv_service.datetime, settings.API_KEY)
    services.utcnow = lambda: clock.now
    services.datetime = inv_service.datetime = SimDatetime
    settings.API_KEY = API_KEY
    try:
        yield
    finally:
        services.utcnow, services.datetime, inv_service.datetime, settings.API_KEY = saved


class AppSim:
    def __init__(self, personas: list[Persona], weeks: int, seed: int, clock: Clock, events: dict[str, dict],
                 transport: Transport | None = None) -> None:
        self.weeks, self.seed, self.clock, self.events = weeks, seed, clock, events
        self.f = Findings()
        self.api = AppApi(transport)
        self.driver = AppDriver(self.api, lambda: clock.now, events, cycle_of, self.f, seed)
        self.users = [AppUser(p=p, rng=random.Random(f"{seed}:{p.idx}:behavior"), E=p.engagement) for p in personas]
        self.heap: list = []
        self.seq = 0
        self.by_uid: dict[int, AppUser] = {}
        self.probes: list[dict] = []
        self.probe_users: set[int] = set()
        self.pos_pending: list[dict] = []
        self.social = None

    # ── очередь ──
    def push(self, t: datetime, prio: int, kind: str, payload=None) -> None:
        heapq.heappush(self.heap, (t, prio, self.seq, kind, payload))
        self.seq += 1

    def has_second(self, u: AppUser) -> bool:
        return random.Random(f"{self.seed}:{u.p.idx}:second").random() < SECOND_PROFILE_SHARE

    def schedule(self) -> None:
        for u in self.users:
            self.push(START + timedelta(hours=u.p.onboard_offset_h), PRIO_USER, "onboard", u)
        for w in range(self.weeks + 1):
            F = FRI0 + timedelta(days=7 * w)
            self.push(at_local(F + timedelta(days=3), 22), PRIO_USER, "close", w)        # понедельник 22:00: конец недели
        self.push(at_local(START.date() + timedelta(days=1), 12), PRIO_USER, "probe_neg")
        self.push(at_local(START.date() + timedelta(days=1), 13), PRIO_USER, "probe_pos_a")
        self.push(at_local(FRI0 + timedelta(days=3), 12), PRIO_USER, "probe_pos_b")      # после дат событий первого уикенда

    def schedule_opens(self, u: AppUser) -> None:
        t0 = self.clock.now
        for c in range(0, self.weeks + 1):
            for t in open_times(u.p, self.seed, c, START):
                if t > t0:
                    self.push(t, PRIO_USER, "open", u)

    # ── обработчики ──
    async def on_onboard(self, u: AppUser) -> None:
        res = await self.driver.onboard(u)
        if u.uid is not None:
            self.by_uid[u.uid] = u
        if res != "completed":
            return
        self.schedule_opens(u)
        await self.driver.open_app(u)                       # «подборка на сегодня» сразу после онбординга
        if self.has_second(u):
            self.push(self.clock.now + timedelta(days=u.rng.uniform(1, 3)), PRIO_USER, "second_profile", u)

    async def on_second_profile(self, u: AppUser) -> None:
        if u.status == "active":
            await self.driver.add_second_profile(u, "child" if u.p.archetype == "родитель" or u.rng.random() < 0.5 else "parent")

    async def on_open(self, u: AppUser) -> None:
        if u.status == "active":
            await self.driver.open_app(u)

    async def on_close(self, w: int) -> None:
        for u in self.users:
            if u.status != "active":
                continue
            u.E *= 0.96
            if w not in u.active_cycles and w > 0:
                u.E *= 0.85
            if w >= 1 and u.E < u.p.churn_thr and u.rng.random() < 0.5:
                u.status, u.churn_cycle = "churned", w

    async def on_social(self, payload) -> None:
        if self.social is not None:
            await self.social.handle(payload)

    # ── пробы персонального обучения ──
    def _probe_users(self, n: int, need_second: bool) -> list[AppUser]:
        pool = [u for u in self.users if u.status == "active" and u.uid not in self.probe_users and u.profiles
                and (len(u.profiles) > 1) == need_second]
        return pool[:n]

    def _by_category(self, items: list[dict]) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        for it in items:
            ev = self.events.get(str((it.get("event") or {}).get("id"))) or {}
            out.setdefault(ev.get("category") or "?", []).append(it)
        return out

    async def on_probe_neg(self, _=None) -> None:
        """После трёх «не моё» по категории она уходит из первой пятёрки ленты этого профиля; второй профиль того же аккаунта не меняется."""
        users = self._probe_users(N_NEG_PROBES // 2, True) + self._probe_users(N_NEG_PROBES - N_NEG_PROBES // 2, False)
        for u in users:
            ps = u.prof
            self.probe_users.add(u.uid)
            other = next((x for x in u.profiles if x is not ps), None)
            items = await self.driver.feed_events(ps)
            top = await self.driver.top_categories(ps)
            cats = self._by_category(items)
            pick = next((c for c in top if c and len(cats.get(c, [])) >= 4), None)
            rec = {"kind": "neg", "u": u.uid, "pid": ps.pid, "category": pick, "has_second": other is not None, "ran": False}
            self.probes.append(rec)
            if pick is None:
                continue
            other_before = await self.driver.top_categories(other) if other else None
            for it in cats[pick][:3]:
                await self.api.decide(u.uid, ps.pid, str(it["event"]["id"]), C.NOT_MINE, reason="не моё")
            after = await self.driver.top_categories(ps)
            rec.update(ran=True, before=top, after=after, passed=pick not in after)
            if other is not None:
                rec["isolated"] = (await self.driver.top_categories(other)) == other_before

    async def on_probe_pos_a(self, _=None) -> None:
        """Этап A: «иду» на три события категории, которой нет в первой пятёрке, плюс «двойник» без этих решений (контроль)."""
        users = self._probe_users(N_POS_PROBES // 2, True) + self._probe_users(N_POS_PROBES - N_POS_PROBES // 2, False)
        horizon = (self.clock.now + timedelta(days=3)).date().isoformat()
        for u in users:
            ps = u.prof
            self.probe_users.add(u.uid)
            items = await self.driver.feed_events(ps)
            top = await self.driver.top_categories(ps)
            soon = [it for it in items if (it.get("day") or "9999") <= horizon]
            cats = self._by_category(soon)
            pick = next((c for c, v in cats.items() if c and c not in top and len(v) >= 3), None)
            rec = {"kind": "pos", "u": u.uid, "pid": ps.pid, "category": pick, "has_second": len(u.profiles) > 1, "ran": False, "before": top}
            self.probes.append(rec)
            if pick is None:
                continue
            twin = await self.driver.make_twin(u, ps)
            chosen = cats[pick][:3]
            for it in chosen:
                await self.api.decide(u.uid, ps.pid, str(it["event"]["id"]), C.GO, day=it.get("day"))
            rec.update(ran=True, events=[str(it["event"]["id"]) for it in chosen], twin=twin,
                       other_before=(await self.driver.top_categories(next(x for x in u.profiles if x is not ps))) if len(u.profiles) > 1 else None)
            self.pos_pending.append(rec)

    async def on_probe_pos_b(self, _=None) -> None:
        """Этап B (после дат событий): «сходил, 5» ×3 → категория поднялась в первую пятёрку профиля и выше, чем у «двойника»; второй профиль не изменился."""
        for rec in self.pos_pending:
            u = self.by_uid.get(rec["u"])
            ps = next(x for x in u.profiles if x.pid == rec["pid"])
            for eid in rec["events"]:
                await self.api.decide(u.uid, ps.pid, eid, C.WENT, rating=5)
            after = await self.driver.top_categories(ps)
            twin_top = await self.driver.top_categories_pid(rec["twin"]["pid"]) if rec.get("twin") else []
            rec.update(after=after, twin_after=twin_top, passed=rec["category"] in after and rec["category"] not in twin_top)
            other = next((x for x in u.profiles if x is not ps), None)
            if other is not None:
                rec["isolated"] = (await self.driver.top_categories(other)) == rec.get("other_before")
            if rec.get("twin"):
                await self.api.delete_account(rec["twin"]["uid"])

    async def run(self) -> None:
        self.schedule()
        while self.heap:
            t, _, _, kind, payload = heapq.heappop(self.heap)
            if t > self.clock.now:
                self.clock.now = t
            await getattr(self, "on_" + kind)(payload)

    # ── метрики п. 11 под приложение ──
    def app_metrics(self) -> dict:
        us = self.users
        started = len(us)
        done = [u for u in us if u.onb.get("completed")]
        n_cyc = self.weeks + 1
        opens = self.driver.opens
        with_dec = [o for o in opens if o["decisions"]]
        ev = [o for o in opens if o["evening"]]
        ev_go = [o for o in ev if o["go"]]
        taps_go = [o["taps_to_go"] for o in ev_go if o["taps_to_go"] is not None]
        go_users: dict[int, set] = {}
        for t in self.driver.taps:
            if t["kind"] == "decision" and t["status"] == C.GO:
                go_users.setdefault(t["cycle"], set()).add(t["u"])
        ratings = [t["rating"] for t in self.driver.taps if t["kind"] == "rating"]
        probes = [p for p in self.probes if p.get("ran")]
        neg = [p for p in probes if p["kind"] == "neg"]
        pos = [p for p in probes if p["kind"] == "pos" and "passed" in p]
        iso = [p for p in probes if "isolated" in p]
        two = [u for u in us if len(u.profiles) > 1]
        return {
            "activation": {"started": started, "completed": len(done)},
            "opens": {"total": len(opens), "per_user_week": round(len(opens) / max(1, len(done) * n_cyc), 2), "with_decision": len(with_dec),
                      "with_decision_share": round(len(with_dec) / len(opens), 4) if opens else None},
            "go_per_week": {c: round(len(go_users.get(c, set())) / max(1, len(done)), 4) for c in range(n_cyc)},
            "retention": {c: round(sum(1 for u in done if c in u.active_cycles) / max(1, len(done)), 4) for c in range(n_cyc)},
            "rating": {"n": len(ratings), "mean": round(sum(ratings) / len(ratings), 2) if ratings else None},
            "evening": {"opens": len(ev), "with_go": len(ev_go), "go_share": round(len(ev_go) / len(ev), 4) if ev else None,
                        "taps_to_go_median": statistics.median(taps_go) if taps_go else None, "target_taps": 3},
            "profiles": {"accounts_with_second": len(two), "share": round(len(two) / max(1, len(done)), 4),
                         "decisions_by_profile": {u.uid: [len(p.decisions) for p in u.profiles] for u in two[:20]}},
            "learning": {"neg_ran": len(neg), "neg_passed": sum(1 for p in neg if p["passed"]), "pos_ran": len(pos), "pos_passed": sum(1 for p in pos if p["passed"]),
                         "isolation_checked": len(iso), "isolation_ok": sum(1 for p in iso if p["isolated"]),
                         "not_run": [p["kind"] for p in self.probes if not p.get("ran")]},
        }


# TODO после того как бэкенд сдаст ленту и профили (по порядку):
#  1. run_app_simulation(): create_database → migrate → install_db_clock → use_database → seed_events → patched_app → AppSim.run() — как run_simulation в runner.py.
#  2. Социальный граф для приложения: app/social.py (порт social_run.py на AppUser/ProfileState); on_going/on_rated уже есть в AppDriver.
#  3. results_from_app(): собрать dict в формате build_results из AppUser/driver.opens/taps; report.py: метрики п. 11 пересчитаны (доля открытий с решением вместо «подборок с решением»),
#     разделы «Вечер освободился», «Несколько профилей», «Персональное обучение»; удалить прежние разделы про рассылку и бота.
#  4. Удалить fakebot.py, actors.py (бот-часть), runner.py (старый), social_run.py (бот-часть); общие утилиты (Clock, at_local, БД, Findings) — в sim/common.py.
