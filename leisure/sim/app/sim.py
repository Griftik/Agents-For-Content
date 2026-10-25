"""Прогон симуляции для приложения, версия 2: люди сами открывают приложение в случайные моменты (1–5 раз в неделю, чаще вечером четверга и
пятницы), выбирают день и направление, смотрят ленту и решают «Иду» / «Не моё»; после даты события отмечают «сходил / не сходил» с оценкой.
Рассылок и уведомлений нет. Часы симуляции подменяют «сейчас» продукта и БД; код продукта не меняется."""
from __future__ import annotations

import asyncio
import contextlib
import heapq
import json
import logging
import random
import statistics
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from ..common import (DEFAULT_WEB, FRI0, MSK, PRIO_JOB, PRIO_USER, START, Clock, Findings, LogCatcher, at_local, create_database, cycle_of, db_call,
                      drop_database, guard_db_name, install_db_clock, migrate, resolve_db_url, seed_events, use_database)
from ..personas import Persona
from . import contract as C
from .api import API_KEY, AppApi, Transport
from .driver import AppDriver, open_times, opens_per_week
from .user import AppUser

SECOND_PROFILE_SHARE = 0.2            # у 20 % персон второй профиль (ребёнок или родитель)
N_NEG_PROBES, N_POS_PROBES = 6, 6     # проб персонального обучения: «три не моё» по категории и «три сходил, 5»


@contextlib.contextmanager
def patched_app(clock: Clock):
    """Часы симуляции в продукте, ключ API и публичный адрес веба на время прогона."""
    from leisure import settings
    from leisure.api import invites as inv_service
    from leisure.api import services

    class SimDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            t = clock.now
            return t.astimezone(tz) if tz else t.replace(tzinfo=None)

    saved = (services.utcnow, services.datetime, inv_service.datetime, settings.API_KEY, settings.WEB_BASE_URL)
    services.utcnow = lambda: clock.now
    services.datetime = inv_service.datetime = SimDatetime
    settings.API_KEY = API_KEY
    if "localhost" in settings.WEB_BASE_URL or "127.0.0.1" in settings.WEB_BASE_URL:
        settings.WEB_BASE_URL = DEFAULT_WEB
    try:
        yield
    finally:
        services.utcnow, services.datetime, inv_service.datetime, settings.API_KEY, settings.WEB_BASE_URL = saved


class AppSim:
    def __init__(self, personas: list[Persona], weeks: int, seed: int, clock: Clock, events: dict[str, dict],
                 transport: Transport | None = None, social: bool = True) -> None:
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
        self.scenarios: dict = {}
        self.jobs: list[dict] = []
        self.catcher: LogCatcher | None = None
        self.social = None
        if social:
            from .social import Social

            self.social = Social(self)
            self.driver.on_going = self.social.on_going
            self.driver.on_rated = self.social.on_rated
        self._clock_eng = None
        self._clock_written = None

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
            self.push(at_local(F - timedelta(days=2), 22), PRIO_JOB, "job", "build")       # журнал показанного (среда 22:00) — остался в воркере
            self.push(at_local(F + timedelta(days=3), 22), PRIO_USER, "close", w)          # понедельник 22:00: конец недели
        self.push(at_local(START.date() + timedelta(days=3), 10), PRIO_USER, "probe_neg")
        self.push(at_local(START.date() + timedelta(days=2), 13), PRIO_USER, "probe_pos_a")
        self.push(at_local(FRI0 + timedelta(days=3), 12), PRIO_USER, "probe_pos_b")        # после дат событий первого уикенда
        self.push(at_local(START.date() + timedelta(days=1), 11), PRIO_USER, "probe_api")
        self.push(at_local(FRI0 + timedelta(days=7 * self.weeks + 2), 20), PRIO_USER, "probe_delete")

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
        await self.driver.open_app(u)                       # лента на сегодня сразу после онбординга
        if self.has_second(u):
            self.push(self.clock.now + timedelta(hours=u.rng.uniform(2, 24)), PRIO_USER, "second_profile", u)

    async def on_second_profile(self, u: AppUser) -> None:
        if u.status == "active":
            kind = "child" if u.p.archetype == "родитель" or u.rng.random() < 0.5 else "parent"
            ok = await self.driver.add_second_profile(u, kind)
            if ok:
                self.by_uid[u.profiles[-1].pid] = u

    async def on_open(self, u: AppUser) -> None:
        if u.status == "active":
            await self.driver.open_app(u)

    async def on_close(self, w: int) -> None:
        for u in self.users + list(self.social.guests.values() if self.social else []):
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

    async def on_job(self, name: str) -> None:
        from leisure.worker import schedules

        fn = {"build": getattr(schedules, "job_build_digests", None)}.get(name)
        if fn is None:
            return
        t0 = time.perf_counter()
        n = await asyncio.to_thread(fn, self.clock.now)
        self.jobs.append({"job": name, "t": self.clock.now.isoformat(), "cycle": cycle_of(self.clock.now), "returned": n, "seconds": round(time.perf_counter() - t0, 3)})

    # ── пробы контракта ──
    async def on_probe_api(self, _=None) -> None:
        """Лента до онбординга — 409; «сходил» до дня события — 400; удаление основного профиля стирает дополнительный (в probe_delete)."""
        out: dict = {}
        st, js = await self.api.session()
        uid = int(js["user_id"])
        await self.api.put_profile(uid, consent=True, name="Проба")
        st, body = await self.api.feed(uid, "today")
        out["feed_before_onboarding"] = {"status": st, "detail": str((body or {}).get("detail"))[:40]}
        u0 = next((u for u in self.users if u.status == "active"), None)
        if u0 is not None:
            items = await self.driver.feed_events(u0.prof, "week")
            fut = next((it for it in items if (it.get("day") or "") > self.clock.now.astimezone().date().isoformat()), None)
            if fut is not None:
                eid = str(fut["event"]["id"])
                st, body = await self.api.decide(u0.prof.pid, eid, C.WENT, day=fut.get("day"), rating=5)
                out["went_before_day"] = {"status": st, "detail": str((body or {}).get("detail"))[:110]}
                if st == 200:
                    await self.api.decide(u0.prof.pid, eid, C.GO, day=fut.get("day"))
        await self.api.delete_profile(uid)
        st, _ = await self.api.get_profile(uid)
        out["deleted_profile_gone"] = st == 404
        self.scenarios["api_probe"] = out

    async def on_probe_delete(self, _=None) -> None:
        u = next((x for x in self.users if x.status == "active" and len(x.profiles) > 1 and x.uid not in self.probe_users), None)
        if u is None:
            return
        second = u.profiles[1].pid
        await self.driver.delete_account(u)
        st_main, _ = await self.api.get_profile(u.uid)
        st_second, _ = await self.api.get_profile(second)
        st_dec, decs = await self.api.decisions(second)
        self.scenarios["delete_account"] = {"u": u.uid, "second": second, "main_gone": st_main == 404, "second_gone": st_second == 404,
                                            "second_decisions_left": len(decs) if st_dec == 200 and isinstance(decs, list) else 0}

    # ── пробы персонального обучения ──
    def _probe_users(self, n: int, need_second: bool) -> list[AppUser]:
        pool = [u for u in self.users if u.status == "active" and u.uid not in self.probe_users and u.profiles and (len(u.profiles) > 1) == need_second]
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
            rec = {"kind": "neg", "u": u.uid, "pid": ps.pid, "category": pick, "has_second": other is not None, "ran": False, "before": top}
            self.probes.append(rec)
            if pick is None:
                continue
            other_before = await self.driver.top_categories(other) if other else None
            for it in cats[pick][:3]:
                await self.api.decide(ps.pid, str(it["event"]["id"]), C.NOT_MINE, reason="не моё")
                ps.decisions[str(it["event"]["id"])] = {"status": C.NOT_MINE, "reason": "не моё", "day": it.get("day"), "cycle": cycle_of(self.clock.now), "probe": True}
            after = await self.driver.top_categories(ps)
            rec.update(ran=True, after=after, passed=pick not in after)
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
            later = (self.clock.now + timedelta(days=4)).date().isoformat(), (self.clock.now + timedelta(days=10)).date().isoformat()

            def more_later(c: str, chosen_ids: set, later=later) -> int:          # события категории в неделе после отметок «сходил»: без них подъёму негде проявиться
                return sum(1 for e in self.events.values() if e.get("category") == c and str(e["id"]) not in chosen_ids
                           and any(later[0] <= d <= later[1] for d in (e.get("dates") or [])))

            cands = [c for c, v in cats.items() if c and c not in top and len(v) >= 3]
            later_n = {c: more_later(c, {str(x["event"]["id"]) for x in cats[c][:3]}) for c in cands}
            pick = next((c for c in cands if later_n[c] >= 2), None) or next((c for c in cands if later_n[c] >= 1), None) or (cands[0] if cands else None)
            rec = {"kind": "pos", "later_events": later_n.get(pick), "u": u.uid, "pid": ps.pid, "category": pick, "has_second": len(u.profiles) > 1, "ran": False, "before": top}
            self.probes.append(rec)
            if pick is None:
                continue
            twin = await self.driver.make_twin(u, ps)
            chosen = cats[pick][:3]
            for it in chosen:
                await self.api.decide(ps.pid, str(it["event"]["id"]), C.GO, day=it.get("day"))
                ps.decisions[str(it["event"]["id"])] = {"status": C.GO, "reason": None, "day": it.get("day"), "cycle": cycle_of(self.clock.now), "probe": True}
            other = next((x for x in u.profiles if x is not ps), None)
            rec.update(ran=True, events=[(str(it["event"]["id"]), it.get("day")) for it in chosen], twin=twin,
                       other_before=(await self.driver.top_categories(other)) if other else None)
            self.pos_pending.append(rec)

    async def on_probe_pos_b(self, _=None) -> None:
        """Этап B (после дат событий): «сходил, 5» ×3 → категория поднялась в первую пятёрку профиля и выше, чем у «двойника»; второй профиль не изменился."""
        for rec in self.pos_pending:
            u = self.by_uid.get(rec["u"])
            if u is None or u.status == "deleted":
                continue
            ps = next(x for x in u.profiles if x.pid == rec["pid"])
            other = next((x for x in u.profiles if x is not ps), None)
            other_before = await self.driver.top_categories(other) if other else None      # прямо перед отметками: лента за дни сама меняется
            statuses = []
            for eid, day in rec["events"]:
                st, js = await self.api.decide(ps.pid, eid, C.WENT, day=day, rating=5)
                statuses.append(st)
                if st == 200 and self.driver.on_rated is not None:
                    self.driver.on_rated(u, ps, 5, js if isinstance(js, dict) else {})
                ps.decisions[eid] = {"status": C.WENT, "rating": 5, "day": day, "cycle": cycle_of(self.clock.now), "probe": True, "marked": True}
            after = await self.driver.top_categories(ps)
            twin_top = await self.driver.top_categories_pid(rec["twin"]["pid"]) if rec.get("twin") else []
            rec["after_scores"] = [((self.events.get(str(it["event"]["id"])) or {}).get("category"), it.get("score")) for it in (await self.driver.feed_events(ps))[:8]]
            if rec.get("twin"):
                st_t, fd_t = await self.api.feed(rec["twin"]["pid"], date="week", segment="all", limit=40)
                rec["twin_scores"] = [((self.events.get(str(it["event"]["id"])) or {}).get("category"), it.get("score")) for it in (fd_t.get("items") or [])[:8]] if st_t == 200 else []
            cat = rec["category"]
            lifted = cat in after and (not rec.get("twin") or cat not in twin_top or after.index(cat) < twin_top.index(cat) or after.count(cat) > twin_top.count(cat))
            rec.update(after=after, twin_after=twin_top, went_statuses=statuses)
            if rec.get("later_events"):
                rec["passed"] = lifted
            else:
                rec["not_evaluable"] = "после отметок событий этой категории в ленте не осталось"
            if other is not None:
                rec["isolated"] = (await self.driver.top_categories(other)) == other_before
            if rec.get("twin"):
                await self.api.delete_profile(rec["twin"]["uid"])

    # ── главный цикл ──
    async def run(self) -> None:
        from sqlalchemy import create_engine, text

        from leisure import settings

        self.schedule()
        self._clock_eng = create_engine(settings.DATABASE_URL, isolation_level="AUTOCOMMIT")
        try:
            while self.heap:
                t, _, _, kind, payload = heapq.heappop(self.heap)
                if t > self.clock.now:
                    self.clock.now = t
                if self._clock_written != self.clock.now:
                    now = self.clock.now

                    def write_clock(t=now):
                        with self._clock_eng.connect() as c:
                            c.execute(text("UPDATE sim_clock SET now = :t"), {"t": t})

                    await asyncio.to_thread(write_clock)
                    self._clock_written = now
                await getattr(self, "on_" + kind)(payload)
            if self.social is not None:
                await self.social.finalize()
        finally:
            self._clock_eng.dispose()

    # ── факты из БД ──
    async def db_facts(self) -> dict:
        from leisure.db.models import Decision, Profile

        pids = {ps.pid: (u, ps) for u in self.users for ps in u.profiles}

        def read(s):
            from sqlalchemy import select
            profs = {p.user_id: dict(acc=p.account_id, kind=p.kind, onb=p.onboarded_at is not None, consent=p.consent_at is not None,
                                     values=p.values or {}, budget=(p.params or {}).get("budget")) for p in s.scalars(select(Profile))}
            decs = [dict(u=d.user_id, ev=str(d.event_id), status=d.status, rating=d.rating, day=d.day.isoformat() if d.day else None)
                    for d in s.scalars(select(Decision).where(Decision.user_id.in_(list(pids))))]
            return profs, decs

        profs, decs = await db_call(read)
        by_pid: dict[int, dict] = {}
        for d in decs:
            by_pid.setdefault(d["u"], {})[d["ev"]] = d
        miss = bad = checked = 0
        for pid, (u, ps) in pids.items():
            if u.status == "deleted":
                continue
            rows = by_pid.get(pid, {})
            for eid, d in ps.decisions.items():
                if not d.get("status"):
                    continue
                checked += 1
                row = rows.get(eid)
                if row is None:
                    miss += 1
                elif row["status"] != d["status"] or (d.get("rating") and row["rating"] != d["rating"]):
                    bad += 1
        # профили аккаунта: решения второго профиля лежат под его user_id, не под основным
        iso_ok = iso_bad = 0
        for u in self.users:
            if len(u.profiles) < 2 or u.status == "deleted":
                continue
            main, second = u.profiles[0], u.profiles[1]
            db_main, db_second = by_pid.get(main.pid, {}), by_pid.get(second.pid, {})
            if profs.get(second.pid, {}).get("acc") == u.uid and set(db_second) == {e for e, d in second.decisions.items() if d.get("status")} \
                    and set(db_main) == {e for e, d in main.decisions.items() if d.get("status")}:
                iso_ok += 1
            else:
                iso_bad += 1
        # «Шаг 1» дошёл до БД: пятёрка ценностей профиля = top_values персоны
        val_bad = sum(1 for pid, (u, ps) in pids.items() if u.status != "deleted" and (ps.onb.get("completed") or (u.onb.get("completed") and ps is u.profiles[0]))
                      and sorted(v for v, w in profs.get(pid, {}).get("values", {}).items() if w == 5) != sorted(ps.p.top_values))
        return {"profiles": {"total": len(profs), "onboarded": sum(1 for p in profs.values() if p["onb"]), "consent_only": sum(1 for p in profs.values() if p["consent"] and not p["onb"]),
                             "no_consent": sum(1 for p in profs.values() if not p["consent"])},
                "decision_integrity": {"checked": checked, "missing": miss, "mismatch": bad},
                "profile_isolation": {"ok": iso_ok, "bad": iso_bad}, "values_mismatch": val_bad}

    # ── метрики п. 11 под приложение ──
    def app_metrics(self) -> dict:
        us = self.users
        done = [u for u in us if u.onb.get("completed")]
        n_cyc = self.weeks + 1
        opens = [o for o in self.driver.opens if o["u"] in {u.uid for u in us}]
        with_dec = [o for o in opens if o["decisions"]]
        ev = [o for o in opens if o["evening"]]
        ev_go = [o for o in ev if o["go"]]
        taps_go = [o["taps_to_go"] for o in ev_go if o["taps_to_go"] is not None]
        main_uids = {u.uid for u in us}
        go_users: dict[int, set] = {}
        for t in self.driver.taps:
            if t["kind"] == "decision" and t["status"] == C.GO and t["u"] in main_uids:
                go_users.setdefault(t["cycle"], set()).add(t["u"])
        ratings = [t["rating"] for t in self.driver.taps if t["kind"] == "rating" and t["u"] in main_uids]
        probes = [p for p in self.probes if p.get("ran")]
        neg = [p for p in probes if p["kind"] == "neg"]
        pos = [p for p in probes if p["kind"] == "pos" and "passed" in p]
        pos_na = [p for p in probes if p["kind"] == "pos" and p.get("not_evaluable")]
        iso = [p for p in probes if "isolated" in p]
        two = [u for u in us if len(u.profiles) > 1]
        by_day = Counter(o["day"] for o in opens)
        by_seg = Counter(o["segment"] for o in opens)
        empty = [o for o in opens if o["cards"] == 0]
        taps_onb = sorted(u.onb["taps_total"] for u in done)
        first_go = sorted(u.first_go_taps for u in done if u.first_go_taps is not None)
        return {
            "activation": {"started": len(us), "completed": len(done), "abandoned_at": dict(Counter(u.onb.get("abandoned_at") for u in us if u.onb.get("abandoned_at")))},
            "onboarding": {"taps_min": taps_onb[0] if taps_onb else None, "taps_median": statistics.median(taps_onb) if taps_onb else None,
                           "taps_max": taps_onb[-1] if taps_onb else None, "taps_le_12": sum(1 for t in taps_onb if t <= 12), "taps_le_9": sum(1 for t in taps_onb if t <= 9),
                           "interest_edits_median": statistics.median([u.onb.get("interest_edits", 0) for u in done]) if done else None,
                           "used_all_screen": sum(1 for u in done if u.onb.get("used_all_screen")), "budget_on_step": sum(1 for u in done if u.onb.get("budget_set")),
                           "shown_match_avg": round(sum(u.onb["prefill"]["shown_match"] for u in done if u.onb.get("prefill")) / max(1, len(done)), 2),
                           "server_prefill_differs": sum(1 for u in done if u.onb.get("server_prefill_differs"))},
            "first_go": {"taps_median": statistics.median(first_go) if first_go else None, "users": len(first_go), "of": len(done)},
            "opens": {"total": len(opens), "per_user_week": round(len(opens) / max(1, len(done) * n_cyc), 2), "with_decision": len(with_dec),
                      "with_decision_share": round(len(with_dec) / len(opens), 4) if opens else None, "empty": len(empty),
                      "by_day": dict(by_day), "by_segment": dict(by_seg), "planned_per_week": dict(Counter(opens_per_week(u.p) for u in us)),
                      "cards_avg": round(sum(o["cards"] for o in opens) / len(opens), 2) if opens else None,
                      "by_cycle": {c: sum(1 for o in opens if o["cycle"] == c) for c in range(n_cyc)}},
            "go_per_week": {c: round(len(go_users.get(c, set())) / max(1, len(done)), 4) for c in range(n_cyc)},
            "retention": {c: round(sum(1 for u in done if c in u.active_cycles) / max(1, len(done)), 4) for c in range(n_cyc)},
            "churned": sum(1 for u in us if u.status == "churned"),
            "rating": {"n": len(ratings), "mean": round(sum(ratings) / len(ratings), 2) if ratings else None, "dist": dict(Counter(ratings)),
                       "went": sum(1 for t in self.driver.taps if t["kind"] == "rating" and t["u"] in main_uids)},
            "decisions": dict(Counter(t["status"] for t in self.driver.taps if t["kind"] == "decision" and t["u"] in main_uids)),
            "evening": {"opens": len(ev), "with_go": len(ev_go), "go_share": round(len(ev_go) / len(ev), 4) if ev else None, "empty": sum(1 for o in ev if o["cards"] == 0),
                        "fallback_tomorrow": sum(1 for o in ev if o.get("fallback")), "with_decision": sum(1 for o in ev if o["decisions"]),
                        "cards_avg": round(sum(o["cards"] for o in ev) / len(ev), 2) if ev else None,
                        "taps_to_go_median": statistics.median(taps_go) if taps_go else None, "taps_to_go_max": max(taps_go) if taps_go else None,
                        "taps_le_3": sum(1 for t in taps_go if t <= 3), "target_taps": 3},
            "profiles": {"accounts_with_second": len(two), "share": round(len(two) / max(1, len(done)), 4) if done else None,
                         "planned_second": sum(1 for u in us if self.has_second(u)), "planned_second_abandoned": sum(1 for u in us if self.has_second(u) and not u.onb.get("completed")),
                         "second_kinds": dict(Counter(u.profiles[1].kind for u in two)),
                         "second_onboarding_taps": [u.profiles[1].onb.get("taps_total") for u in two],
                         "decisions_by_profile": [[len(p.decisions) for p in u.profiles] for u in two],
                         "opens_second_share": round(sum(1 for o in opens if o["pid"] != o["u"]) / len(opens), 4) if opens else None},
            "learning": {"neg_ran": len(neg), "neg_passed": sum(1 for p in neg if p["passed"]), "pos_ran": len(pos), "pos_passed": sum(1 for p in pos if p["passed"]),
                         "pos_not_evaluable": len(pos_na),
                         "isolation_checked": len(iso), "isolation_ok": sum(1 for p in iso if p["isolated"]),
                         "not_run": dict(Counter(p["kind"] for p in self.probes if not p.get("ran")))},
        }


def run_app_simulation(users: int = 50, weeks: int = 4, seed: int = 20261024, db_url: str | None = None, keep_db: bool = False,
                       quiet: bool = False, social: bool = True) -> dict:
    """База симуляции (имя содержит «sim») создаётся, мигрируется, наполняется seed и удаляется; возвращает результаты для report.py."""
    from .. import personas as persmod

    t_start = time.perf_counter()
    url = resolve_db_url(db_url)
    guard_db_name(url)
    if not quiet:
        print(f"[sim] база {url.rsplit('/', 1)[-1]}: пересоздаю, миграции, seed…", flush=True)
    create_database(url)
    results: dict | None = None
    try:
        migrate(url)
        install_db_clock(url)
        with use_database(url):
            created = seed_events()
            from sqlalchemy import select

            from leisure.db.models import Event
            from leisure.db.session import session_factory

            with session_factory()() as s:
                events = {str(e.id): e.as_core() for e in s.scalars(select(Event))}
            clock = Clock()
            personas = persmod.generate(users, seed)
            catcher = LogCatcher()
            lg = logging.getLogger("leisure")
            old_prop, old_level = lg.propagate, lg.level
            lg.addHandler(catcher)
            lg.propagate = False
            lg.setLevel(logging.INFO)
            try:
                with patched_app(clock):
                    sim = AppSim(personas, weeks, seed, clock, events, social=social)
                    sim.catcher = catcher
                    if not quiet:
                        print(f"[sim] {len(personas)} персон, {weeks + 1} недель, старт {START.date()}, приложение без рассылок", flush=True)

                    async def go():
                        await sim.run()
                        return await sim.db_facts()

                    facts = asyncio.run(go())
            finally:
                lg.removeHandler(catcher)
                lg.propagate, lg.level = old_prop, old_level
            results = build_results(sim, {"users": users, "weeks": weeks, "seed": seed}, url, facts, catcher.records, time.perf_counter() - t_start, created)
    finally:
        if not keep_db:
            with contextlib.suppress(Exception):
                drop_database(url)
    return results


def build_results(sim: AppSim, args: dict, db_url: str, facts: dict, logs: list[dict], duration: float, seed_created: int) -> dict:
    pers = []
    for u in sim.users:
        p = u.p
        pers.append({"idx": p.idx, "user_id": u.uid, "archetype": p.archetype, "tz": p.tz, "status": u.status, "planned_abandon": p.abandon_step,
                     "abandoned_at": u.onb.get("abandoned_at"), "completed": bool(u.onb.get("completed")), "onboarding_taps": u.onb.get("taps_total"),
                     "steps_taps": u.onb.get("steps"), "interest_edits": u.onb.get("interest_edits"), "prefill": u.onb.get("prefill"), "misclick": u.onb.get("misclick"),
                     "budget_set": u.onb.get("budget_set"), "used_all_screen": u.onb.get("used_all_screen"), "opens_per_week": opens_per_week(p), "opens": len(u.opens),
                     "active_cycles": sorted(u.active_cycles), "decision_cycles": sorted(u.decision_cycles), "churn_cycle": u.churn_cycle,
                     "first_go_taps": u.first_go_taps, "E": round(u.E, 3), "top_values": p.top_values,
                     "profiles": [{"kind": ps.kind, "decisions": len(ps.decisions), "ratings": len(ps.ratings), "onboarding_taps": ps.onb.get("taps_total"),
                                   "archetype": ps.p.archetype} for ps in u.profiles]})
    growth = sim.social.final if sim.social is not None else None
    return {
        "meta": {**args, "db_name": db_url.rsplit("/", 1)[-1], "start": START.isoformat(), "events_seeded": seed_created, "product": "app-v2",
                 "archetypes": dict(Counter(u.p.archetype for u in sim.users)), "api_calls": sum(sim.api.calls.values())},
        "volatile": {"duration_s": round(duration, 1), "jobs": sim.jobs},
        "personas": pers, "opens": sim.driver.opens, "decisions": sim.driver.taps, "probes": sim.probes, "scenarios": sim.scenarios,
        "metrics": sim.app_metrics(), "findings": sim.f.to_dict(), "api": {"calls": dict(sorted(sim.api.calls.items())), "errors": sim.api.errors[:10],
                                                                              "n_errors": len(sim.api.errors)},
        "db": facts, "growth": growth, "log_errors": logs,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    import os
    import sys

    ap = argparse.ArgumentParser(description="Симулятор пользователей «Успею» (приложение, версия 2)")
    ap.add_argument("--users", type=int, default=50)
    ap.add_argument("--weeks", type=int, default=4, help="недель после недели онбординга")
    ap.add_argument("--seed", type=int, default=20261024)
    ap.add_argument("--db-url", default=None, help="база симуляции (имя содержит «sim»); по умолчанию leisure_sim на сервере из DATABASE_URL")
    ap.add_argument("--out-dir", default=str(Path(__file__).resolve().parents[1]), help="куда писать REPORT.md и report.json")
    ap.add_argument("--keep-db", action="store_true")
    ap.add_argument("--no-social", action="store_true", help="без графа друзей (приглашения, рекомендации)")
    ap.add_argument("--no-log", action="store_true", help="(совместимость) журнала вызовов в версии 2 нет")
    args = ap.parse_args(argv)
    os.environ.setdefault("WEB_BASE_URL", DEFAULT_WEB)
    out = Path(args.out_dir)
    try:
        results = run_app_simulation(args.users, args.weeks, args.seed, args.db_url, args.keep_db, social=not args.no_social)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        print(f"[sim] прогон упал: {type(e).__name__}: {e}", file=sys.stderr)
        raise
    from .. import report

    (out / "out").mkdir(parents=True, exist_ok=True)
    (out / "out" / "run_data.json").write_text(json.dumps(results, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    m = report.write_reports(results, out)
    print(report.console_summary(m, results))
    return 0


_ = MSK
