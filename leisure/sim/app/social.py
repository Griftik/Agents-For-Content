"""Социальный граф в приложении (ТЗ-B, docs/GROWTH.md; версия 2 — без Telegram): приглашения через API, момент рекомендации в ответе на оценку.

Пригласивший после «иду» зовёт друга — POST /api/invites. Друг открывает ссылку: гостевая сессия → GET /api/invites/{code} → POST …/open →
POST …/accept (going / maybe / declined, consent при первом касании) → предложение онбординга «Давай» / «Потом» → онбординг через
PUT /api/profile → дальше живёт в приложении как все. «Имя идёт с тобой» пригласивший видит в плане (companions). Момент рекомендации —
`ref_ask` в ответе POST /api/decisions при оценке 4–5; «Поделиться» — системный диалог, сервер его не видит, симулятор решает за человека
и открывает ссылку /?ref=<код> новыми людьми. Гости (друзья вне сервиса и пришедшие по ссылке) живут в `Social.guests`, не в `AppSim.users`:
основные метрики п. 11 считаются по 50 персонам."""
from __future__ import annotations

import random
import re
from collections import Counter, defaultdict
from datetime import timedelta

from ..common import db_call
from ..personas import Persona, make_persona
from ..social import NEIGHBORS, Friend, build_graph, friend_pick, p_accept, p_invite, p_share, p_take_onboarding, sociability
from . import contract as C
from .user import AppUser, ProfileState

CONSENT_TICK_P = 0.93         # поставил галочку согласия, а не ушёл
DECLINE_P = 0.35              # из открывших, но не принявших: нажал «Другие выходные под меня»
MAYBE_P = 0.2                 # из принявших: «Может быть», а не «Иду»
OPEN_P = 0.9                  # друг вообще открыл ссылку
REF_NEWCOMERS = ([0, 1, 2], [0.5, 0.35, 0.15])        # сколько людей открывает ссылку-рекомендацию после «Поделиться»
REF_IDX0 = 5000
CODE_RE = re.compile(r"^[2-9A-HJKMNP-TV-Z]{8}$")


def _first_name(name: str) -> str:
    return (name or "").split()[0] if (name or "").strip() else ""


class Social:
    def __init__(self, sim) -> None:
        self.sim = sim
        self.api = sim.api
        self.seed = sim.seed
        personas = [u.p for u in sim.users]
        self.graph = build_graph(personas, self.seed, n_users=len(personas))
        self.soc = {p.idx: sociability(p, self.seed) for p in personas}
        self.user_of_idx = {u.p.idx: u for u in sim.users}
        self.asked: set = set()
        self.invites: list[dict] = []
        self.guests: dict[int, AppUser] = {}
        self.guest_of_idx: dict[int, AppUser] = {}
        self.ref_asks: list[dict] = []
        self.ref_shares: list[dict] = []
        self.ref_newcomers: list[dict] = []
        self.ref_counter = 0
        self.checks: Counter = Counter()
        self.examples: dict[str, list[str]] = defaultdict(list)
        self.offers: list[dict] = []
        self.onboard_api: list[dict] = []
        self.last_ask: dict[int, object] = {}
        self.final: dict = {}

    # ───────── служебное ─────────
    def note(self, code: str, msg: str) -> None:
        self.checks[code] += 1
        if len(self.examples[code]) < 4:
            self.examples[code].append(msg)

    @property
    def now(self):
        return self.sim.clock.now

    def push(self, t, *payload) -> None:
        self.sim.push(t, 1, "social", payload)

    def new_guest(self, persona: Persona, via: str) -> AppUser:
        g = self.guest_of_idx.get(persona.idx)
        if g is None:
            if persona.idx % 10 == 3:                               # имя бывает любым: проверяем экранирование и в вебе
                persona.name = f"<{persona.name}>"
            elif persona.idx % 10 == 7:
                persona.name = f"{persona.name}&Ко"
            g = AppUser(p=persona, rng=random.Random(f"{self.seed}:{persona.idx}:behavior"), E=persona.engagement)
            g.onb["via"] = via
            self.guest_of_idx[persona.idx] = g
        return g

    async def ensure_session(self, g: AppUser) -> bool:
        if g.uid is not None:
            return True
        st, js = await self.api.session()
        if st != 200 or not js.get("user_id"):
            self.note("session_failed", f"гость: POST /api/session → {st}")
            return False
        g.uid, g.status = int(js["user_id"]), "guest"
        g.profiles = [ProfileState(pid=g.uid, kind="self", p=g.p, name=g.p.name)]
        self.guests[g.uid] = g
        self.sim.by_uid[g.uid] = g
        self.sim.f.ignore.add(g.uid)
        return True

    # ───────── пригласивший ─────────
    def on_going(self, u: AppUser, ps: ProfileState, eid: str, day: str | None) -> None:
        friends = self.graph.get(u.p.idx)
        ev = self.sim.events.get(eid)
        if not friends or ev is None or not day or u.uid in self.guests:
            return
        key = (u.uid, eid)
        if key in self.asked:
            return
        rng = random.Random(f"{self.seed}:{u.p.idx}:invite:{ev['slug']}")
        fits = {f.idx: f.persona.fit(ev) for f in friends if f.persona is not None}
        f = friend_pick(rng, friends, fits)
        if f is None or rng.random() >= p_invite(u.p, self.soc[u.p.idx], fits.get(f.idx, 0.3)):
            return
        self.asked.add(key)
        self.push(self.now + timedelta(hours=rng.uniform(0.02, 3.0)), "invite", u, ps, eid, day, f)

    async def invite(self, u: AppUser, ps: ProfileState, eid: str, day: str, fr: Friend) -> None:
        from leisure import settings

        ev = self.sim.events[eid]
        st, body = await self.api.invite_create(ps.pid, ev["slug"], day)
        if st != 200:
            self.note("invite_create_failed", f"u{u.uid}: POST /api/invites → {st} {str(body)[:80]}")
            return
        code = body.get("code", "")
        link = body.get("url") or ""
        ok = (bool(CODE_RE.match(code)) and link.startswith(settings.WEB_BASE_URL.rstrip("/")) and f"/e/{ev['slug']}?inv={code}" in link
              and link in (body.get("share_text") or "") and ev["title"][:20] in (body.get("share_text") or ""))
        self.note("invite_contract_ok" if ok else "invite_contract_bad",
                  f"u{u.uid}: код {'ok' if CODE_RE.match(code) else repr(code)}, ссылка {'на веб' if link.startswith(settings.WEB_BASE_URL.rstrip('/')) else repr(link)[:50]}")
        rec = {"n": len(self.invites), "code": code, "inviter": ps.pid, "inviter_idx": u.p.idx, "friend_idx": fr.idx, "inside": fr.inside,
               "event_id": eid, "event_slug": ev["slug"], "day": day, "t": self.now.isoformat(), "opened": False, "accept": None,
               "declined": False, "fnew": None, "consent_409": False, "notified": None, "together_with": None, "profile_state": None,
               "viewed_status": None, "friend": None}
        self.invites.append(rec)
        rng = random.Random(f"{self.seed}:{u.p.idx}:invite2:{ev['slug']}")
        if rng.random() < 0.12:                                   # повторное нажатие «Позвать друга»: тот же код
            st2, b2 = await self.api.invite_create(ps.pid, ev["slug"], day)
            self.note("invite_idempotent" if st2 == 200 and b2.get("code") == code else "invite_not_idempotent", f"u{u.uid}: повтор → {'тот же код' if b2.get('code') == code else 'другой код'}")
        if rng.random() < OPEN_P:
            self.push(self.now + timedelta(hours=rng.uniform(0.1, 30.0)), "friend_open", rec, fr)

    # ───────── друг ─────────
    async def _is_new(self, uid: int) -> bool:
        from leisure.db.models import Profile
        return bool(await db_call(lambda s: (lambda p: p is None or p.consent_at is None)(s.get(Profile, uid))))

    async def friend_open(self, rec: dict, fr: Friend) -> None:
        sim = self.sim
        ev = sim.events[rec["event_id"]]
        if fr.inside:
            g = self.user_of_idx.get(fr.idx)
            if g is None or g.uid is None or g.status in ("deleted",):
                self.note("friend_without_app", f"#{rec['n']}: друг внутри сервиса ещё не открывал приложение, ссылку не открыл")
                return
        else:
            g = self.new_guest(fr.persona, "invite")
            if not await self.ensure_session(g):
                return
        rec["friend"] = g.uid
        persona = g.p
        rng = random.Random(f"{self.seed}:{fr.idx}:friend:{rec['n']}")
        rec["fnew"] = await self._is_new(g.uid)
        st, view = await self.api.invite_view(rec["code"], g.uid)
        if st != 200:
            self.note("invite_view_failed", f"#{rec['n']} → {st}")
            return
        rec["viewed_status"] = view.get("status")
        inviter = sim.by_uid.get(rec["inviter"])
        inv_ps = next((x for x in inviter.profiles if x.pid == rec["inviter"]), None) if inviter else None
        exp = _first_name(inv_ps.name) if inv_ps else None
        good = view.get("event") is not None and view.get("day") == rec["day"] and view.get("inviter_name") in (exp, None)
        late = view.get("status") in ("past", "unpublished", "gone")
        self.note("view_past" if late and good else "view_ok" if good and view.get("status") == "active" else "view_bad",
                  f"#{rec['n']}: status={view.get('status')} day={view.get('day')} inviter={view.get('inviter_name')!r}")
        st, _ = await self.api.invite_open(rec["code"], g.uid, persona.name, persona.username)
        rec["opened"] = st == 200
        if st != 200:
            self.note("open_failed", f"#{rec['n']} → {st}")
            return
        g.taps += 1
        if rng.random() >= p_accept(persona.fit(ev)):
            if rng.random() < DECLINE_P:
                await self.respond(rec, fr, g, "declined", rng)
            return
        await self.respond(rec, fr, g, "going" if rng.random() >= MAYBE_P else "maybe", rng)

    async def respond(self, rec: dict, fr: Friend, g: AppUser, status: str, rng: random.Random) -> None:
        sim = self.sim
        persona = g.p
        g.taps += 1
        st, js = await self.api.invite_accept(rec["code"], g.uid, status, consent=False, name=persona.name, username=persona.username)
        if st == 409:
            rec["consent_409"] = True
            self.note("consent_required_409", f"#{rec['n']}")
            if rng.random() >= CONSENT_TICK_P:
                self.note("consent_not_given", f"#{rec['n']}")
                return
            g.taps += 2                                           # галочка согласия + подтвердить
            st, js = await self.api.invite_accept(rec["code"], g.uid, status, consent=True, name=persona.name, username=persona.username)
        if st == 410:
            self.note("accept_gone_410", f"#{rec['n']}: событие прошло ({js.get('detail')})")
            return
        if st != 200:
            self.note("accept_failed", f"#{rec['n']} {status} → {st} {str(js)[:60]}")
            return
        rec["accept"] = status
        rec["profile_state"] = js.get("profile_state")
        rec["together_with"] = js.get("together_with")
        rec["accept_t"] = self.now.isoformat()
        if status == "declined":
            rec["declined"] = True
            rec["accept"] = None
            self.note("declined_ok" if js.get("decision") is None else "declined_has_decision", f"#{rec['n']}")
            return
        d = js.get("decision") or {}
        self.note("accept_ok" if d.get("status") == {"going": C.GO, "maybe": C.MAYBE}[status] and d.get("day") == rec["day"] else "accept_bad",
                  f"#{rec['n']}: решение {d.get('status')} на {d.get('day')}")
        inviter = sim.by_uid.get(rec["inviter"])
        if status == "going" and inviter is not None:
            ps_inv = next((x for x in inviter.profiles if x.pid == rec["inviter"]), None)
            st2, plan = await self.api.plan(rec["inviter"])
            comp = [c for it in ((plan.get("days") or {}).values() if st2 == 200 and isinstance(plan, dict) else [])
                    for it2 in [it] for e in it2 if str((e.get("event") or {}).get("id")) == rec["event_id"] for c in (e.get("companions") or [])]
            comp += [c for e in ((plan.get("horizon") or []) if st2 == 200 and isinstance(plan, dict) else []) if str((e.get("event") or {}).get("id")) == rec["event_id"] for c in (e.get("companions") or [])]
            rec["notified"] = bool(comp)
            exp_name = _first_name(persona.name)
            if comp:
                self.note("inviter_sees_companion", f"#{rec['n']}: в плане пригласившего «вдвоём с {comp[0]}»")
                if any(ch in persona.name for ch in "<>&"):
                    self.note("companion_special_chars", f"#{rec['n']}: имя с <, > или & показано в плане как {comp[0]!r}")
                if comp[0] not in (exp_name, "другом"):
                    self.note("companion_name_bad", f"#{rec['n']}: ожидали {exp_name!r}, в плане {comp[0]!r}")
            elif ps_inv is not None and inviter.status != "deleted":
                self.note("inviter_not_notified", f"#{rec['n']}: у пригласившего в плане нет «вдвоём с …» по событию")
            inv_exp = _first_name(ps_inv.name) if ps_inv else None
            self.note("together_name_ok" if js.get("together_with") in (inv_exp, None) else "together_name_bad", f"#{rec['n']}: {js.get('together_with')!r}, ждали {inv_exp!r}")
        ps = next((x for x in g.profiles if x.pid == g.uid), g.prof)      # приглашение принимает аккаунт: решение ложится в основной профиль
        ps.decisions[rec["event_id"]] = {"status": d.get("status"), "reason": None, "day": rec["day"], "cycle": None, "via_invite": rec["n"]}
        if g.uid in self.guests:
            await self.after_accept_guest(rec, g, rng)

    async def after_accept_guest(self, rec: dict, g: AppUser, rng: random.Random) -> None:
        if g.status == "guest":
            g.status = "consented"
            g.onb["consent_t"] = self.now.isoformat()
        if rec["profile_state"] == "new" and not g.onb.get("completed") and not g.onb.get("offer_round"):
            g.onb["offer_round"] = 1
            g.onb["offer_day"] = rec["day"]
            await self.offer(g, 1, rng)

    async def offer(self, g: AppUser, rnd: int, rng: random.Random) -> None:
        """«Хочешь свою ленту? Два шага»: «Давай» / «Потом» (повтор один раз, на следующий день после события)."""
        p_yes = p_take_onboarding(g.p) * (1.0 if rnd == 1 else 0.5)
        yes = rng.random() < p_yes
        self.offers.append({"u": g.uid, "round": rnd, "yes": yes, "t": self.now.isoformat()})
        g.taps += 1
        if yes:
            self.push(self.now + timedelta(minutes=rng.uniform(1, 20)), "onboard_guest", g)
        elif rnd == 1:
            from datetime import date

            from ..common import at_local
            day = date.fromisoformat(g.onb["offer_day"]) if g.onb.get("offer_day") else self.now.date()
            t2 = at_local(day + timedelta(days=1), 12, minute=30)
            if t2 <= self.now:
                t2 = self.now + timedelta(hours=26)
            self.push(t2, "offer2", g)

    async def onboard_guest(self, g: AppUser) -> None:
        """Онбординг гостя в приложении: те же два шага через PUT /api/profile; бросить может на тех же шагах."""
        if g.onb.get("completed") or g.onb.get("api_onboarding") or g.uid is None:
            return
        g.onb["api_onboarding"] = self.now.isoformat()
        g.onb.setdefault("taps_at_start", 0)
        rec = {"u": g.uid, "via": g.onb.get("via"), "t": self.now.isoformat(), "done": False, "abandon": g.p.abandon_step}
        self.onboard_api.append(rec)
        out = await self.sim.driver.onboard_profile(g, g.profiles[0], g.onb, first=True)
        rec["done"] = out == "completed"
        if rec["done"]:
            g.status = "active"
            g.onboarded_t = self.now
            g.onb["taps_total"] = g.taps
            self.sim.schedule_opens(g)
        else:
            g.status = "consented" if g.status != "guest" else "guest"

    # ───────── момент рекомендации ─────────
    def on_rated(self, u: AppUser, ps: ProfileState, rating: int, js: dict) -> None:
        ask = js.get("ref_ask") if isinstance(js, dict) else None
        key = ps.pid                                               # правило «не чаще раза в 14 дней» у продукта — на профиль
        if rating >= 4:
            prev = self.last_ask.get(key)
            if ask is None:
                if prev is None or (self.now - prev) >= timedelta(days=14):
                    self.note("ref_ask_missing", f"u{u.uid}: оценка {rating}, давно не просили, ref_ask в ответе нет")
                return
            if prev is not None and (self.now - prev) < timedelta(days=14):
                self.note("ref_ask_too_soon", f"u{u.uid}: вторая просьба через {(self.now - prev).days} дн.")
            self.last_ask[key] = self.now
            self.ref_asks.append({"u": u.uid, "pid": ps.pid, "t": self.now.isoformat(), "rating": rating})
            link = str(ask.get("url") or "")
            m = re.search(r"[?&]ref=([A-Z0-9]{8})", link)
            if not m or link not in str(ask.get("share_text") or ""):
                self.note("ref_ask_bad", f"u{u.uid}: url={link[:60]!r}, share_text {'со ссылкой' if link and link in str(ask.get('share_text')) else 'без ссылки'}")
                return
            rng = random.Random(f"{self.seed}:{u.p.idx}:ref:{len(self.ref_asks)}")
            if rng.random() < p_share(rating, self.soc.get(u.p.idx, 0.4)):
                self.ref_shares.append({"u": u.uid, "t": self.now.isoformat()})
                k = rng.choices(*REF_NEWCOMERS)[0]
                for j in range(k):
                    self.push(self.now + timedelta(hours=rng.uniform(1, 72)), "ref_open", u, m.group(1), j)
        elif ask is not None:
            self.note("ref_ask_on_low_rating", f"u{u.uid}: оценка {rating}, но пришёл ref_ask")
        if rating <= 2 and not (isinstance(js, dict) and js.get("ask_reason")):
            self.note("ask_reason_missing", f"u{u.uid}: оценка {rating}, ask_reason в ответе нет")

    async def ref_open(self, u: AppUser, code: str, j: int) -> None:
        sim = self.sim
        r = random.Random(f"{self.seed}:{u.p.idx}:refnew:{len(self.ref_shares)}:{j}")
        self.ref_counter += 1
        idx = REF_IDX0 + self.ref_counter
        persona = make_persona(self.seed, idx, r.choice(NEIGHBORS[u.p.archetype]), len(sim.users))
        g = self.new_guest(persona, "ref")
        if not await self.ensure_session(g):
            return
        st, _ = await self.api.invite_open(code, g.uid, persona.name, persona.username)
        rec = {"u": g.uid, "code": code, "sharer": u.uid, "t": self.now.isoformat(), "opened": st == 200, "consented": False, "source": None}
        self.ref_newcomers.append(rec)
        if st != 200:
            self.note("ref_open_failed", f"ссылка-рекомендация → {st}")
            return
        if self.ref_counter == 1 or r.random() < p_take_onboarding(persona) * 0.8:   # первый пришедший всегда проходит путь целиком (проба контракта)
            g.status = "consented"
            g.onb["consent_t"] = self.now.isoformat()
            rec["consented"] = True
            g.taps += 2
            pst, prof = await self.api.put_profile(g.uid, consent=True, name=persona.name, ref_code=code)
            rec["source"] = prof.get("source") if pst == 200 and isinstance(prof, dict) else None
            self.note("ref_source_ok" if rec["source"] == "ref" else "ref_source_bad", f"u{g.uid}: PUT профиля → {pst}, source={rec['source']!r}")
            self.push(self.now + timedelta(minutes=r.uniform(1, 15)), "onboard_guest", g)
        else:
            pst, _ = await self.api.get_profile(g.uid)
            self.note("ref_no_profile_without_consent" if pst == 404 else "ref_profile_without_consent", f"u{g.uid}: GET профиля → {pst}")

    # ───────── диспетчер ─────────
    async def handle(self, payload: tuple) -> None:
        kind, *args = payload
        if kind == "invite":
            await self.invite(*args)
        elif kind == "friend_open":
            await self.friend_open(*args)
        elif kind == "onboard_guest":
            await self.onboard_guest(*args)
        elif kind == "offer2":
            (g,) = args
            if not g.onb.get("completed"):
                await self.offer(g, 2, random.Random(f"{self.seed}:{g.p.idx}:offer2"))
        elif kind == "ref_open":
            await self.ref_open(*args)

    # ───────── итоги ─────────
    async def finalize(self) -> None:
        from leisure.db.models import Decision, Invite, InviteAccept, Profile

        sim = self.sim
        st, api_metrics = await self.api.growth()

        def read(s):
            from sqlalchemy import select
            profs = [dict(u=p.user_id, acc=p.account_id, kind=p.kind, source=p.source, consent=p.consent_at, onb=p.onboarded_at, created=p.created_at)
                     for p in s.scalars(select(Profile))]
            decs = [dict(u=d.user_id, ev=str(d.event_id), status=d.status, rating=d.rating, inv=d.invite_id, day=d.day) for d in s.scalars(select(Decision))]
            invs = [dict(id=i.id, code=i.code, kind=i.kind, inviter=i.inviter_id, opened=i.opened, accepted=i.accepted) for i in s.scalars(select(Invite))]
            accs = [dict(inv=a.invite_id, u=a.user_id, status=a.status, new=a.was_new, notified=a.notified_at) for a in s.scalars(select(InviteAccept))]
            return profs, decs, invs, accs

        profs, decs, invs, accs = await db_call(read)
        main_pids = {ps.pid for u in sim.users for ps in u.profiles}
        main_uids = {u.uid for u in sim.users if u.uid is not None}
        going = [d for d in decs if d["status"] == C.GO]
        going_ever = [d for d in decs if d["status"] in (C.GO, C.WENT, C.SKIPPED)]      # «иду», в том числе уже отмеченные «сходил / не сходил»
        gone = {uid for uid, x in sim.by_uid.items() if x.status == "deleted"}
        made = list(self.invites)
        recs = [r for r in made if r["friend"] not in gone]
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

        own = {"invite_share": (len(made), len(going_ever)), "acceptance": (len(accepted), len(opened)), "activation_invited": (len(new_activated), len(new_opened)),
               "onboarding_invited": (len(inv_onb14), len(invited)), "new_via_friends": (len(new_friends), len(new_total)),
               "virality": (len(new_friends), len(active_users)), "positive_experience": (len(good), len(rated)),
               "recommendation": (len([x for x in self.ref_shares if x["u"] not in gone]), len([x for x in self.ref_asks if x["u"] not in gone])),
               "together_going": (together_n, len(going_ever))}
        api_m = (api_metrics or {}).get("metrics", {}) if st == 200 else {}
        table = {k: {"own": {"value": ratio(*v), "numerator": v[0], "denominator": v[1]}, "api": api_m.get(k)} for k, v in own.items()}
        ref_codes_seen = len({r["code"] for r in self.ref_newcomers if r["opened"]})
        mism = [k for k, v in table.items() if k != "recommendation" and v["api"] and v["api"].get("numerator") is not None
                and (v["api"]["numerator"], v["api"]["denominator"]) != (v["own"]["numerator"], v["own"]["denominator"])]
        if (table["recommendation"]["api"] or {}).get("numerator") not in (None, ref_codes_seen):
            mism.append("recommendation")
        started = len(sim.users)
        completed = sum(1 for u in sim.users if u.onb.get("completed"))
        consented = sum(1 for u in sim.users if u.p.abandon_step != "consent")

        def stat(rows):
            r = [d["rating"] for d in rows if d["rating"] is not None]
            return {"n": len(r), "mean": round(sum(r) / len(r), 2) if r else None, "share_4_5": ratio(sum(1 for x in r if x >= 4), len(r))}

        inv_users = {p["u"] for p in invited}
        pair = {(r["inviter"], r["event_id"]) for r in opened if r["accept"] == "going"} | {(r["friend"], r["event_id"]) for r in opened if r["accept"] == "going"}
        org_rows = [d for d in decs if d["u"] in main_pids and d["inv"] is None]
        compare = {
            "activation": {"organic": {"num": completed, "den": started}, "invited": {"num": len(new_activated), "den": len(new_opened)}},
            "onboarding": {"organic": {"num": completed, "den": consented}, "invited": {"num": len(inv_onb14), "den": len(invited)}},
            "ratings": {"organic": stat(org_rows), "invited_decisions": stat([d for d in decs if d["inv"] is not None]),
                        "invited_users_all": stat([d for d in decs if d["u"] in inv_users]),
                        "together": stat([d for d in decs if (d["u"], d["ev"]) in pair]),
                        "solo": stat([d for d in org_rows if (d["u"], d["ev"]) not in pair])},
        }
        ck = self.checks
        guests = set(self.guests)
        funnel = {
            "invites": len(made), "opened": len(opened), "accepted": len(accepted), "going": sum(1 for r in opened if r["accept"] == "going"),
            "maybe": sum(1 for r in opened if r["accept"] == "maybe"), "declined": sum(1 for r in opened if r["declined"]),
            "new_openers": len(new_opened), "new_accepted": len(new_activated), "consent_409": sum(1 for r in opened if r["consent_409"]),
            "to_inside": sum(1 for r in recs if r["inside"]), "to_outside": sum(1 for r in recs if not r["inside"]),
            "inviters": len({r["inviter"] for r in recs}), "notified": sum(1 for r in opened if r["accept"] == "going" and r["notified"]),
            "offers_round1": sum(1 for o in self.offers if o["round"] == 1), "offers_yes1": sum(1 for o in self.offers if o["round"] == 1 and o["yes"]),
            "offers_round2": sum(1 for o in self.offers if o["round"] == 2), "offers_yes2": sum(1 for o in self.offers if o["round"] == 2 and o["yes"]),
            "onboarding_started": len(self.onboard_api), "onboarding_done": sum(1 for o in self.onboard_api if o["done"]),
            "guests_total": len(guests), "guests_active": sum(1 for g in self.guests.values() if g.status == "active"),
            "guests_opened_app": sum(1 for g in self.guests.values() if g.opens),
            "ref_asks": len(self.ref_asks), "ref_shares": len(self.ref_shares), "ref_newcomers": len(self.ref_newcomers),
            "ref_newcomers_consented": sum(1 for r in self.ref_newcomers if r["consented"]), "ref_codes_seen": ref_codes_seen,
            "ref_ask_users": len({r["u"] for r in self.ref_asks}),
            "opened_anonymous_api": (api_metrics or {}).get("counts", {}).get("opened_without_consent") if st == 200 else None,
            "second_profiles_in_new_total": sum(1 for p in new_total if p["u"] in main_pids and p["u"] not in main_uids),
            "going_now": len(going), "going_ever": len(going_ever),
        }
        self.final = {"metrics": table, "mismatch": mism, "funnel": funnel, "compare": compare, "api_status": st,
                      "sources": dict(Counter(p["source"] for p in profs)), "api_counts": (api_metrics or {}).get("counts"),
                      "checks": dict(ck), "examples": dict(self.examples), "n_api_errors": len(self.api.errors), "api_errors": self.api.errors[:5],
                      "friends": {"avg": round(sum(len(v) for v in self.graph.values()) / max(1, len(self.graph)), 2),
                                  "outside": sum(1 for v in self.graph.values() for f in v if not f.inside),
                                  "inside": sum(1 for v in self.graph.values() for f in v if f.inside)},
                      "invites": [{k: r.get(k) for k in ("n", "inviter", "friend", "inside", "event_slug", "day", "t", "opened", "accept", "declined", "fnew",
                                                        "consent_409", "notified", "profile_state")} for r in self.invites],
                      "ref": {"asks": self.ref_asks, "shares": self.ref_shares, "newcomers": [{k: v for k, v in x.items() if k != "code"} for x in self.ref_newcomers]},
                      "offers": self.offers, "onboarding_api": self.onboard_api, "guest_findings": dict(sim.f.guest_count)}
