"""Социальный граф в прогоне (ТЗ-B, docs/GROWTH.md): приглашения друзей через API Mini App, момент рекомендации через бота.

Пригласивший: после «иду» (в боте) с вероятностью от общительности зовёт друга — POST /api/invites. Друг: GET /api/invites/{code},
POST …/open, POST …/accept (going / maybe / declined, consent при первом касании), предложение онбординга «Давай» / «Потом» (повтор вместе
с «Как прошло?»), онбординг через PUT /api/profile/{id}. Через бота идут только уведомление пригласившему, «План на сегодня», «Как прошло?»
и момент рекомендации после оценки 4–5 (URL-кнопка: бот нажатия не видит, симулятор «нажимает» её сам и открывает ref-ссылку через API).
Новые люди (друзья вне сервиса и пришедшие по ссылке-рекомендации) живут в `Sim.guests`, а не в `Sim.states`: основные метрики п. 11
считаются по 50 персонам, как в прошлых прогонах; рост через друзей и сравнение приглашённых с органическими — отдельный раздел отчёта.
"""
from __future__ import annotations

import asyncio
import random
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from urllib.parse import parse_qs, unquote, urlparse

from .personas import Persona, make_persona
from .social import NEIGHBORS, Friend, build_graph, friend_pick, p_accept, p_invite, p_share, p_take_onboarding, sociability, user_id_of

API_KEY = "sim-api-key"
BOT_USERNAME = "leisure_sim_bot"
MINIAPP = "app"
WRITE_ACCESS_P = 0.6          # «Получать план в Telegram»: доля друзей, давших боту право писать (FLOW-INVITE, В2)
CONSENT_TICK_P = 0.93         # поставил галочку согласия, а не ушёл
DECLINE_P = 0.35              # из открывших, но не принявших: нажал «Другие выходные под меня»
MAYBE_P = 0.2                 # из принявших: «Может быть», а не «Иду»
OPEN_P = 0.9                  # друг вообще открыл ссылку
REF_NEWCOMERS = ([0, 1, 2], [0.5, 0.35, 0.15])        # сколько людей открывает ссылку-рекомендацию после «Поделиться»
TOGETHER_RATING_BONUS = 0.0   # намеренно 0: «вдвоём приятнее» — допущение, его в оценку не закладываем (см. отчёт)
REF_IDX0 = 5000
EXTERNAL_BEHAVIOR = "behavior"


async def db_call(fn, *args):
    from leisure.db.session import session_factory

    def _c():
        with session_factory()() as s:
            return fn(s, *args)

    return await asyncio.to_thread(_c)


def _first_name(name: str) -> str:
    return (name or "").split()[0] if (name or "").strip() else ""


class Social:
    def __init__(self, sim, env: dict) -> None:
        self.sim = sim
        self.env = env
        self.seed = sim.seed
        personas = [ps.p for ps in sim.states]
        self.graph = build_graph(personas, self.seed, n_users=len(personas))
        self.soc = {p.idx: sociability(p, self.seed) for p in personas}
        self.persona_of: dict[int, Persona] = {p.idx: p for p in personas}
        self.client = None
        self.asked: set = set()
        self.invites: list[dict] = []
        self.inv_by_code: dict[str, dict] = {}
        self.guests: dict[int, object] = {}
        self.ref_asks: list[dict] = []
        self.ref_shares: list[dict] = []
        self.ref_newcomers: list[dict] = []
        self.ref_counter = 0
        self.calls: Counter = Counter()
        self.api_errors: list[dict] = []
        self.checks: Counter = Counter()
        self.examples: dict[str, list[str]] = defaultdict(list)
        self.offers: list[dict] = []
        self.onboard_api: list[dict] = []
        self.last_ask: dict[int, datetime] = {}

    # ───────── служебное ─────────
    def note(self, code: str, msg: str, n: int = 1) -> None:
        self.checks[code] += n
        if len(self.examples[code]) < 4:
            self.examples[code].append(msg)

    def _client(self):
        if self.client is None:
            from fastapi.testclient import TestClient

            from leisure.api.main import app
            self.client = TestClient(app)
        return self.client

    async def api(self, method: str, path: str, **kw) -> tuple[int, dict]:
        """Вызов API продукта через FastAPI TestClient (в потоке: обработчик синхронный и сам ходит в БД и в бота)."""
        client = self._client()

        def go():
            return getattr(client, method)(path, headers={"X-API-Key": API_KEY}, **kw)

        r = await asyncio.to_thread(go)
        key = re.sub(r"/[A-Z0-9]{8}(?=/|$)", "/{code}", re.sub(r"/\d{6,}", "/{id}", path.split("?")[0]))
        self.calls[f"{method.upper()} {key} {r.status_code}"] += 1
        try:
            body = r.json()
        except Exception:  # noqa: BLE001
            body = {}
        if r.status_code >= 500:
            self.api_errors.append({"path": f"{method.upper()} {path}", "status": r.status_code, "body": str(body)[:200]})
        return r.status_code, body

    def push(self, t: datetime, *payload) -> None:
        self.sim.push(t, self.env["PRIO_USER"], "social", payload)

    @property
    def now(self) -> datetime:
        return self.sim.clock.now

    def state_of(self, uid: int):
        return self.sim.by_uid.get(uid)

    def new_guest(self, persona: Persona, via: str):
        """Состояние человека, пришедшего по приглашению или ссылке. В `Sim.states` не входит, но принимает рассылки (by_uid)."""
        from .actors import PState

        ps = self.guests.get(persona.user_id)
        if ps is None:
            ps = PState(p=persona, rng=random.Random(f"{self.seed}:{persona.idx}:behavior"), E=persona.engagement, status="new")
            ps.onb["via"] = via
            self.guests[persona.user_id] = ps
            self.sim.by_uid[persona.user_id] = ps
            self.sim.f.ignore.add(persona.user_id)
        return ps

    # ───────── пригласивший ─────────
    def on_going(self, ps, card) -> None:
        """Хук Driver: человек нажал «Иду» на карточке. Зовёт ли друга — розыгрыш от общительности и подходящести события другу."""
        p = ps.p
        friends = self.graph.get(p.idx)
        ev = self.sim.events.get(card.event_id)
        if not friends or ev is None or not card.day:
            return
        key = (p.user_id, card.event_id)
        if key in self.asked:
            return
        rng = random.Random(f"{self.seed}:{p.idx}:invite:{card.event_id}")
        fits = {f.idx: f.persona.fit(ev) for f in friends if f.persona is not None}
        f = friend_pick(rng, friends, fits)
        if f is None or rng.random() >= p_invite(p, self.soc[p.idx], fits.get(f.idx, 0.3)):
            return
        self.asked.add(key)
        self.push(self.now + timedelta(hours=rng.uniform(0.02, 3.0)), "invite", ps, card.event_id, card.day, f)

    async def invite(self, ps, eid: str, day: str, fr: Friend) -> None:
        p = ps.p
        ev = self.sim.events[eid]
        st, body = await self.api("post", "/api/invites", json={"user_id": p.user_id, "event_slug": ev["slug"], "day": day, "kind": "event"})
        if st != 200:
            self.note("invite_create_failed", f"u{p.user_id}: POST /api/invites → {st} {str(body)[:80]}")
            return
        code = body.get("code", "")
        link = body.get("url") or body.get("web_url") or ""
        ok = bool(re.fullmatch(r"[2-9A-HJKMNP-TV-Z]{8}", code)) and link in (body.get("share_text") or "") and ev["title"][:20] in (body.get("share_text") or "")
        self.note("invite_contract_ok" if ok else "invite_contract_bad", f"u{p.user_id}: code={code!r} url={body.get('url')!r} share_text={str(body.get('share_text'))[:60]!r}")
        if not body.get("url") or "startapp=inv_" not in body["url"]:
            self.note("invite_no_miniapp_url", f"url={body.get('url')!r}")
        rec = {"code": code, "inviter": p.user_id, "inviter_idx": p.idx, "friend": user_id_of(fr), "friend_idx": fr.idx, "inside": fr.inside,
               "event_id": eid, "event_slug": ev["slug"], "day": day, "t": self.now.isoformat(), "opened": False, "accept": None,
               "declined": False, "was_new": None, "consent_409": False, "notified": None, "together_with": None, "profile_state": None,
               "viewed_status": None}
        self.invites.append(rec)
        self.inv_by_code[code] = rec
        rng = random.Random(f"{self.seed}:{p.idx}:invite2:{eid}")
        if rng.random() < 0.12:                                   # повторное нажатие «Позвать друга»: тот же код
            st2, b2 = await self.api("post", "/api/invites", json={"user_id": p.user_id, "event_slug": ev["slug"], "day": day, "kind": "event"})
            self.note("invite_idempotent" if st2 == 200 and b2.get("code") == code else "invite_not_idempotent", f"u{p.user_id}: {code} → {b2.get('code')}")
        if rng.random() < OPEN_P:
            self.push(self.now + timedelta(hours=rng.uniform(0.1, 30.0)), "friend_open", rec, fr)

    # ───────── друг ─────────
    async def _is_new(self, uid: int) -> bool:
        from leisure.db.models import Profile

        return bool(await db_call(lambda s: (lambda p: p is None or p.consent_at is None)(s.get(Profile, uid))))

    async def friend_open(self, rec: dict, fr: Friend) -> None:
        sim = self.sim
        ev = sim.events[rec["event_id"]]
        uid = rec["friend"]
        persona = fr.persona
        ps = sim.by_uid.get(uid) if fr.inside else None
        if not fr.inside:
            ps = self.new_guest(persona, "invite")
            if uid not in sim.world.cannot_initiate and ps.status == "new":
                sim.world.cannot_initiate.add(uid)             # профиль создаст Mini App: бот первым писать не может
        rng = random.Random(f"{self.seed}:{fr.idx}:friend:{rec['code']}")
        rec["fnew"] = await self._is_new(uid)                    # нет профиля или согласия: так же считает продукт (InviteAccept.was_new)
        st, view = await self.api("get", f"/api/invites/{rec['code']}", params={"user_id": uid})
        if st != 200:
            self.note("invite_view_failed", f"{rec['code']} → {st}")
            return
        rec["viewed_status"] = view.get("status")
        inv_p = sim.by_uid[rec["inviter"]].p
        good = (view.get("status") == "active" and view.get("event") is not None and view.get("day") == rec["day"]
                and (view.get("inviter_name") == _first_name(inv_p.name) or view.get("inviter_name") is None))
        self.note("view_ok" if good else "view_bad", f"{rec['code']}: status={view.get('status')} day={view.get('day')} inviter={view.get('inviter_name')!r}")
        st, _ = await self.api("post", f"/api/invites/{rec['code']}/open", json={"user_id": uid, "name": persona.name, "username": persona.username})
        rec["opened"] = st == 200
        if st != 200:
            self.note("open_failed", f"{rec['code']} → {st}")
            return
        fit = persona.fit(ev)
        if rng.random() >= p_accept(fit):
            if rng.random() < DECLINE_P:
                await self.respond(rec, fr, ps, "declined", rng)
            return
        await self.respond(rec, fr, ps, "going" if rng.random() >= MAYBE_P else "maybe", rng)

    async def respond(self, rec: dict, fr: Friend, ps, status: str, rng: random.Random) -> None:
        sim = self.sim
        uid, persona = rec["friend"], fr.persona
        body = {"user_id": uid, "status": status, "consent": False, "name": persona.name, "username": persona.username}
        inviter_chat = sim.world.chats[rec["inviter"]]
        n0 = len(inviter_chat)
        st, js = await self.api("post", f"/api/invites/{rec['code']}/accept", json=body)
        if st == 409:
            rec["consent_409"] = True
            self.note("consent_required_409", f"{rec['code']} u{uid}")
            if rng.random() >= CONSENT_TICK_P:
                self.note("consent_not_given", f"{rec['code']} u{uid}")
                return
            body["consent"] = True
            st, js = await self.api("post", f"/api/invites/{rec['code']}/accept", json=body)
        if st != 200:
            self.note("accept_failed", f"{rec['code']} u{uid} {status} → {st} {str(js)[:60]}")
            return
        rec["accept"] = status
        rec["profile_state"] = js.get("profile_state")
        rec["together_with"] = js.get("together_with")
        rec["accept_t"] = self.now.isoformat()
        if status == "declined":
            rec["declined"] = True
            rec["accept"] = None
            self.note("declined_ok" if js.get("decision") is None else "declined_has_decision", f"{rec['code']} u{uid}")
            return
        d = js.get("decision") or {}
        self.note("accept_ok" if d.get("status") == {"going": "иду", "maybe": "может"}[status] and d.get("day") == rec["day"] else "accept_bad",
                  f"{rec['code']}: decision={d}")
        inviter_ps = sim.by_uid[rec["inviter"]]
        if status == "going":
            msgs = [m for m in inviter_chat[n0:] if not m.from_user and any(b.get("callback_data") == "pl:s" for b in m.buttons())]
            rec["notified"] = bool(msgs)
            if msgs:
                self.note("inviter_notified", f"u{rec['inviter']}: «{msgs[0].text[:60]}»")
            elif inviter_ps.status == "active" and rec["inviter"] not in sim.world.blocked:
                self.note("inviter_not_notified", f"{rec['code']}: пригласивший u{rec['inviter']} не получил уведомления")
            exp_name = _first_name(inviter_ps.p.name)
            self.note("together_name_ok" if js.get("together_with") in (exp_name, None) else "together_name_bad", f"{rec['code']}: {js.get('together_with')!r}")
        # учёт решения в состоянии человека (для планов и оценок)
        eid = rec["event_id"]
        if ps is not None:
            ps.decisions[eid] = {"status": d.get("status"), "reason": None, "week": None, "card_day": rec["day"], "cycle": None,
                                 "redecided": False, "via_invite": rec["code"]}
        rec["was_new"] = rec.get("fnew")
        if not fr.inside:
            await self.after_accept_guest(rec, fr, ps, rng)

    async def after_accept_guest(self, rec: dict, fr: Friend, ps, rng: random.Random) -> None:
        sim = self.sim
        uid = rec["friend"]
        if ps.status == "new":
            ps.status = "active"                                   # получает «План на сегодня» и «Как прошло?», если бот может писать
            ps.onb["consent_t"] = self.now.isoformat()
            ps.onb["first_accept_t"] = self.now.isoformat()
            ps.onboarded_t = None
            if rng.random() < WRITE_ACCESS_P:                      # «Получать план в Telegram»
                st, _ = await self.api("put", f"/api/profile/{uid}", json={"can_write": True})
                if st == 200:
                    sim.world.cannot_initiate.discard(uid)
                    ps.onb["can_write"] = True
            else:
                ps.onb["can_write"] = False
        if rec["profile_state"] == "new" and not ps.onb.get("completed") and not ps.onb.get("offer_round"):
            ps.onb["offer_round"] = 1
            ps.onb["offer_day"] = rec["day"]
            await self.offer(ps, fr, 1, rng)

    async def offer(self, ps, fr: Friend, rnd: int, rng: random.Random) -> None:
        """«Хочешь свою подборку на выходные? Два шага»: «Давай» / «Потом» (повтор один раз вместе с «Как прошло?»)."""
        uid = ps.p.user_id
        p_yes = p_take_onboarding(ps.p) * (1.0 if rnd == 1 else 0.5)
        yes = rng.random() < p_yes
        self.offers.append({"u": uid, "round": rnd, "yes": yes, "t": self.now.isoformat()})
        if yes:
            self.push(self.now + timedelta(minutes=rng.uniform(1, 20)), "onboard_api", ps, fr)
            await self.api("put", f"/api/profile/{uid}", json={"offer_seen": rnd})
        else:
            await self.api("put", f"/api/profile/{uid}", json={"offer_seen": rnd})
            if rnd == 1:
                day = datetime.fromisoformat(ps.onb["offer_day"]).date() if ps.onb.get("offer_day") else self.now.date()
                t2 = self.env["at_local"](day + timedelta(days=1), 12, minute=30)
                if t2 <= self.now:
                    t2 = self.now + timedelta(hours=26)
                self.push(t2, "offer2", ps, fr)

    async def onboard_via_api(self, ps, fr) -> None:
        """Онбординг в Mini App: два шага (ценности, интересы) и параметры одним PUT; бросить могут на тех же шагах, что и в боте."""
        sim = self.sim
        p = ps.p
        uid = p.user_id
        if ps.onb.get("completed") or ps.onb.get("api_onboarding"):
            return
        ps.onb["api_onboarding"] = self.now.isoformat()
        rec = {"u": uid, "via": ps.onb.get("via"), "t": self.now.isoformat(), "done": False, "abandon": p.abandon_step}
        self.onboard_api.append(rec)
        st, _ = await self.api("put", f"/api/profile/{uid}", json={"values": {v: int(w) for v, w in p.value_w.items()}, "consent": True})
        if st != 200 or p.abandon_step == "values":
            return
        levels = {c: int(t) for c, t in p.interest_targets.items()}
        params = {"budget": p.budget, "times": list(p.times), "aesthetics": bool(p.aesthetics),
                  "company": "с детьми" if p.company == "с детьми" else "любая", "kids": p.company == "с детьми"}
        await asyncio.sleep(0)
        st, _ = await self.api("put", f"/api/profile/{uid}", json={"interests": levels, "params": params})
        if st != 200 or p.abandon_step == "interests":
            return
        st, js = await self.api("put", f"/api/profile/{uid}", json={"onboarded": True})
        if st != 200:
            return
        rec["done"] = bool(js.get("onboarded"))
        if rec["done"]:
            ps.onb["completed"] = self.now.isoformat()
            ps.onboarded_t = self.now
            ps.onb["taps_total"] = 0
            if ps.onb.get("can_write") is None:
                ps.onb["can_write"] = True
            sim.world.cannot_initiate.discard(uid) if ps.onb.get("can_write") else None

    # ───────── момент рекомендации ─────────
    def on_rated(self, ps, rating: int, new_msgs: list) -> None:
        """Хук Driver после оценки. Ищем просьбу о рекомендации (T-REF-ASK); бот нажатия «Поделиться» не видит — решаем за человека сами."""
        ask = next((m for m in new_msgs if not m.from_user and m.text.startswith("Рад, что зашло")), None)
        p = ps.p
        if rating >= 4:
            if ask is None:
                prev = self.last_ask.get(p.user_id)
                if prev is None or (self.now - prev) >= timedelta(days=14):
                    self.note("ref_ask_missing", f"u{p.user_id}: оценка {rating}, давно не просили, просьбы нет")
                return
            btn = next((b for b in ask.buttons() if "url" in b), None)
            prev = self.last_ask.get(p.user_id)
            if prev is not None and (self.now - prev) < timedelta(days=14):
                self.note("ref_ask_too_soon", f"u{p.user_id}: вторая просьба через {(self.now - prev).days} дн.")
            self.last_ask[p.user_id] = self.now
            rec = {"u": p.user_id, "t": self.now.isoformat(), "rating": rating, "url": btn["url"] if btn else None}
            self.ref_asks.append(rec)
            if btn is None:
                self.note("ref_ask_no_button", f"u{p.user_id}")
                return
            rng = random.Random(f"{self.seed}:{p.idx}:ref:{len(self.ref_asks)}")
            if rng.random() < p_share(rating, self.soc.get(p.idx, 0.4)):
                link = unquote((parse_qs(urlparse(btn["url"]).query).get("url") or [""])[0])
                m = re.search(r"(?:ref_|[?&]ref=)([A-Z0-9]{8})", link)
                self.ref_shares.append({"u": p.user_id, "code": m.group(1) if m else None, "link": link, "t": self.now.isoformat()})
                if not m:
                    self.note("ref_link_unparsed", f"u{p.user_id}: {link[:80]!r}")
                    return
                k = rng.choices(*REF_NEWCOMERS)[0]
                for j in range(k):
                    self.push(self.now + timedelta(hours=rng.uniform(1, 72)), "ref_open", ps, m.group(1), j)
        elif ask is not None:
            self.note("ref_ask_on_low_rating", f"u{p.user_id}: оценка {rating}, но пришла просьба о рекомендации")

    async def ref_open(self, ps, code: str, j: int) -> None:
        sim = self.sim
        sharer = ps.p
        r = random.Random(f"{self.seed}:{sharer.idx}:refnew:{code}:{j}")
        self.ref_counter += 1
        idx = REF_IDX0 + self.ref_counter
        arch = r.choice(NEIGHBORS[sharer.archetype])
        persona = make_persona(self.seed, idx, arch, len(sim.states))
        gps = self.new_guest(persona, "ref")
        uid = persona.user_id
        sim.world.cannot_initiate.add(uid)
        st, view = await self.api("post", f"/api/invites/{code}/open", json={"user_id": uid, "name": persona.name, "username": persona.username})
        rec = {"u": uid, "code": code, "sharer": sharer.user_id, "t": self.now.isoformat(), "opened": st == 200, "consented": False, "onboarded": False,
               "source": None}
        self.ref_newcomers.append(rec)
        if st != 200:
            self.note("ref_open_failed", f"{code} → {st}")
            return
        _, prof = await self.api("get", f"/api/profile/{uid}")
        rec["source"] = prof.get("source")
        self.note("ref_source_ok" if prof.get("source") == "ref" else "ref_source_bad", f"u{uid}: source={prof.get('source')!r}")
        gps.status = "new"
        if r.random() < p_take_onboarding(persona) * 0.8:
            gps.status = "active"
            gps.onb["consent_t"] = self.now.isoformat()
            rec["consented"] = True
            await self.api("put", f"/api/profile/{uid}", json={"consent": True, "name": persona.name})
            if r.random() < WRITE_ACCESS_P:
                await self.api("put", f"/api/profile/{uid}", json={"can_write": True})
                sim.world.cannot_initiate.discard(uid)
                gps.onb["can_write"] = True
            self.push(self.now + timedelta(minutes=r.uniform(1, 15)), "onboard_api", gps, None)

    # ───────── диспетчер событий ─────────
    async def handle(self, payload: tuple) -> None:
        kind, *args = payload
        if kind == "invite":
            await self.invite(*args)
        elif kind == "friend_open":
            await self.friend_open(*args)
        elif kind == "onboard_api":
            await self.onboard_via_api(*args)
            rec = self.onboard_api[-1] if self.onboard_api else None
            if rec and rec["done"] and rec["u"] == args[0].p.user_id:
                await self.after_onboarding(args[0])
        elif kind == "offer2":
            ps, fr = args
            if not ps.onb.get("completed"):
                await self.offer(ps, fr, 2, random.Random(f"{self.seed}:{ps.p.idx}:offer2"))
        elif kind == "ref_open":
            await self.ref_open(*args)

    async def after_onboarding(self, ps) -> None:
        """Человек прошёл онбординг в Mini App: первая подборка придёт в ближайший четверг по расписанию (в чат её никто не шлёт)."""
        ps.onb["after_onboarding"] = self.now.isoformat()

    # ───────── итоги ─────────
    async def finalize(self) -> None:
        """Конец прогона: метрики роста по данным БД и симулятора, ответ GET /api/metrics/growth, сравнение приглашённых с органическими."""
        from leisure.db.models import Decision, Invite, InviteAccept, Profile

        sim = self.sim
        st, api_metrics = await self.api("get", "/api/metrics/growth")
        main = {ps.p.user_id for ps in sim.states}
        guests = set(self.guests)

        def read(s):
            from sqlalchemy import select
            profs = [dict(u=p.user_id, source=p.source, ref=p.referred_by, consent=p.consent_at, onb=p.onboarded_at, created=p.created_at,
                          can_write=p.can_write, offer=p.offer_seen, active=p.active) for p in s.scalars(select(Profile))]
            decs = [dict(u=d.user_id, ev=str(d.event_id), status=d.status, rating=d.rating, inv=d.invite_id, day=d.day) for d in s.scalars(select(Decision))]
            invs = [dict(id=i.id, code=i.code, kind=i.kind, inviter=i.inviter_id, opened=i.opened, accepted=i.accepted) for i in s.scalars(select(Invite))]
            accs = [dict(inv=a.invite_id, u=a.user_id, status=a.status, new=a.was_new, opened=a.opened_at, accepted=a.accepted_at, notified=a.notified_at)
                    for a in s.scalars(select(InviteAccept))]
            return profs, decs, invs, accs

        profs, decs, invs, accs = await db_call(read)
        by_u = {p["u"]: p for p in profs}
        going = [d for d in decs if d["status"] == "иду"]
        gone = {u for u, x in sim.by_uid.items() if x.status == "deleted"}       # /delete каскадом стирает их приглашения и принятия
        recs = [r for r in self.invites if r["inviter"] not in gone and r["friend"] not in gone]
        opened = [r for r in recs if r["opened"]]
        accepted = [r for r in opened if r["accept"] in ("going", "maybe")]
        new_opened = [r for r in opened if r.get("fnew")]
        new_activated = [r for r in new_opened if r["accept"] in ("going", "maybe")]
        invited = [p for p in profs if p["source"] == "invite"]
        inv_onb14 = [p for p in invited if p["onb"] is not None and p["onb"] <= p["created"] + timedelta(days=14)]
        new_total = [p for p in profs if p["consent"] is not None]
        new_friends = [p for p in new_total if p["source"] in ("invite", "ref", "share")]
        active_users = {d["u"] for d in decs}
        rated = [d for d in decs if d["rating"] is not None]
        good = [d for d in rated if d["rating"] >= 4]
        together_n = 2 * sum(1 for r in opened if r["accept"] == "going")

        def ratio(n, d):
            return round(n / d, 4) if d else None

        own = {
            "invite_share": (len(recs), len(going)),
            "acceptance": (len(accepted), len(opened)),
            "activation_invited": (len(new_activated), len(new_opened)),
            "onboarding_invited": (len(inv_onb14), len(invited)),
            "new_via_friends": (len(new_friends), len(new_total)),
            "virality": (len(new_friends), len(active_users)),
            "positive_experience": (len(good), len(rated)),
            "recommendation": (len(self.ref_shares), len(self.ref_asks)),
            "together_going": (together_n, len(going)),
        }
        api_m = (api_metrics or {}).get("metrics", {}) if st == 200 else {}
        table = {k: {"own": {"value": ratio(*v), "numerator": v[0], "denominator": v[1]}, "api": api_m.get(k)} for k, v in own.items()}
        # ссылки-рекомендации: открыли по данным БД
        ref_invs = [i for i in invs if i["kind"] == "ref"]
        ref_opened_db = sum(1 for i in ref_invs if i["opened"] > 0)

        # сравнение приглашённых с органическими
        organic = main
        inv_users = {p["u"] for p in invited}
        started = len(main)
        completed = sum(1 for ps in sim.states if ps.onb.get("completed"))
        consented = sum(1 for ps in sim.states if ps.p.abandon_step != "consent")

        def stat(rows):
            r = [d["rating"] for d in rows if d["rating"] is not None]
            return {"n": len(r), "mean": round(sum(r) / len(r), 2) if r else None, "share_4_5": ratio(sum(1 for x in r if x >= 4), len(r))}

        org_rows = [d for d in decs if d["u"] in organic and d["inv"] is None]
        inv_rows = [d for d in decs if d["inv"] is not None]
        inv_users_rows = [d for d in decs if d["u"] in inv_users]
        pair_events = {(r["inviter"], r["event_id"]) for r in opened if r["accept"] == "going"} | {(r["friend"], r["event_id"]) for r in opened if r["accept"] == "going"}
        tog = [d for d in decs if d["status"] == "иду" and (d["u"], d["ev"]) in pair_events]
        solo = [d for d in decs if d["status"] == "иду" and d["u"] in organic and (d["u"], d["ev"]) not in pair_events and d["inv"] is None]
        compare = {
            "activation": {"organic": {"num": completed, "den": started}, "invited": {"num": len(new_activated), "den": len(new_opened)}},
            "onboarding": {"organic": {"num": completed, "den": consented}, "invited": {"num": len(inv_onb14), "den": len(invited)},
                           "organic_note": "прошли онбординг / дали согласие", "invited_note": "полный профиль за 2 недели / принявшие (source=invite)"},
            "ratings": {"organic": stat(org_rows), "invited_decisions": stat(inv_rows), "invited_users_all": stat(inv_users_rows),
                        "together": stat(tog), "solo": stat(solo)},
        }
        # воронка приглашений
        funnel = {
            "invites": len(recs), "opened": len(opened), "accepted": len(accepted), "going": sum(1 for r in opened if r["accept"] == "going"),
            "maybe": sum(1 for r in opened if r["accept"] == "maybe"), "declined": sum(1 for r in opened if r["declined"]),
            "new_openers": len(new_opened), "new_accepted": len(new_activated), "consent_409": sum(1 for r in opened if r["consent_409"]),
            "to_inside": sum(1 for r in recs if r["inside"]), "to_outside": sum(1 for r in recs if not r["inside"]),
            "inviters": len({r["inviter"] for r in recs}), "notified": sum(1 for r in opened if r["accept"] == "going" and r["notified"]),
            "offers_round1": sum(1 for o in self.offers if o["round"] == 1), "offers_yes1": sum(1 for o in self.offers if o["round"] == 1 and o["yes"]),
            "offers_round2": sum(1 for o in self.offers if o["round"] == 2), "offers_yes2": sum(1 for o in self.offers if o["round"] == 2 and o["yes"]),
            "onboarding_started": len(self.onboard_api), "onboarding_done": sum(1 for o in self.onboard_api if o["done"]),
            "guests_total": len(guests), "guests_can_write": sum(1 for u in guests if by_u.get(u, {}).get("can_write")),
            "guests_with_digest": len({r.uid for r in sim.digest_recs if r.uid in guests}),
            "ref_asks": len(self.ref_asks), "ref_shares": len(self.ref_shares), "ref_newcomers": len(self.ref_newcomers),
            "ref_newcomers_consented": sum(1 for r in self.ref_newcomers if r["consented"]), "ref_opened_db": ref_opened_db, "ref_codes_opened": ref_codes_opened,
            "ref_ask_users": len({r["u"] for r in self.ref_asks}),
        }
        ref_codes_opened = len({r["code"] for r in self.ref_newcomers if r["opened"]})
        mism = [k for k, v in table.items() if k != "recommendation" and v["api"] and v["api"].get("numerator") is not None
                and (v["api"]["numerator"], v["api"]["denominator"]) != (v["own"]["numerator"], v["own"]["denominator"])]
        if (table["recommendation"]["api"] or {}).get("numerator") not in (None, ref_codes_opened):
            mism.append("recommendation")
        sources = Counter(p["source"] for p in profs)
        self.final = {"metrics": table, "mismatch": mism, "funnel": funnel, "compare": compare, "api_status": st, "sources": dict(sources),
                      "api_counts": (api_metrics or {}).get("counts"), "calls": dict(sorted(self.calls.items())), "checks": dict(self.checks),
                      "examples": {k: v for k, v in self.examples.items()}, "api_errors": self.api_errors[:5], "n_api_errors": len(self.api_errors),
                      "friends": {"avg": round(sum(len(v) for v in self.graph.values()) / max(1, len(self.graph)), 2),
                                  "outside": sum(1 for v in self.graph.values() for f in v if not f.inside),
                                  "inside": sum(1 for v in self.graph.values() for f in v if f.inside)},
                      "guest_findings": dict(sim.f.guest_count)}
