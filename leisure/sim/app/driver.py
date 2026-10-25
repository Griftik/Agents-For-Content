"""Действия людей в приложении (версия 2: живая лента, без рассылок): гостевой аккаунт, согласие, онбординг профиля, второй профиль,
открытие приложения в случайный момент, лента на день и направление, «Иду» / «Не моё», отметка «сходил / не сходил» с оценкой после даты события.

Нажатия онбординга считаются по web/FLOW-ONBOARDING.md: галочка согласия 1, «Начать» 1, пять ценностей по 1 (автопереход), правки интересов,
бюджет строкой 1, «Показать подборку» 1 — минимум 8 (9 с бюджетом), типично 12. Состояние экрана живёт на клиенте, на сервер уходят PUT'ы."""
from __future__ import annotations

import random
from collections import Counter
from datetime import datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

from leisure.core.catalog import ALL_CATS, propose_interests, proposed_categories
from leisure.core.config import scoring_config
from leisure.core.feed import adult_only

from ..common import Findings
from ..personas import Persona, make_persona, sigmoid
from . import contract as C
from .api import AppApi
from .user import AppUser, ProfileState

REASONS = ["не моё", "дорого", "далеко", "уже был", "не в это время", "не та компания"]
SECOND_ARCH = {"child": ["спортсмен", "тусовщик", "мастер"], "parent": ["эстет", "интеллектуал", "экономный"]}
DOW_W = [0.8, 0.8, 0.9, 1.7, 1.9, 1.1, 1.0]                  # пн … вс: чаще четверг и пятница
HOUR_W = {h: (0.4 if h < 12 else 0.6 if h < 17 else 1.0 if h < 20 else 1.3) for h in range(8, 24)}
EVENING = (17, 19)                                          # «освободился вечер»: открытие в будний день с 17:00 до 19:59


def opens_per_week(p: Persona) -> int:
    """Сколько раз в неделю человек сам открывает приложение: 1–5 по характеру (вовлечённость)."""
    return max(1, min(5, round(0.8 + 4.4 * p.engagement)))


def open_times(p: Persona, seed: int, cycle: int, start: datetime) -> list[datetime]:
    """Моменты открытий в неделе `cycle` (вт–пн, как cycle_of): случайные, чаще вечером четверга и пятницы. Детерминированы от seed."""
    rng = random.Random(f"{seed}:{p.idx}:opens:{cycle}")
    tz = ZoneInfo(p.tz)
    base = (start + timedelta(days=7 * cycle)).astimezone(tz).date()
    slots = [(d, h) for d in range(7) for h in range(8, 24)]
    w = []
    for d, h in slots:
        dow = (base + timedelta(days=d)).weekday()
        w.append(DOW_W[dow] * HOUR_W[h] * (1.3 if dow in (3, 4) and h >= 18 else 1.0))
    out: set = set()
    n = opens_per_week(p)
    while len(out) < n:
        out.add(rng.choices(slots, w)[0])
    return sorted(datetime(*(base + timedelta(days=d)).timetuple()[:3], h, rng.randrange(60), tzinfo=tz).astimezone(start.tzinfo) for d, h in out)


def is_evening_window(local: datetime) -> bool:
    return local.weekday() < 5 and EVENING[0] <= local.hour <= EVENING[1]


class AppDriver:
    def __init__(self, api: AppApi, now_fn: Callable[[], datetime], events: dict[str, dict], cycle_of: Callable[[datetime], int],
                 findings: Findings, seed: int = 0) -> None:
        self.api, self.now, self.events, self.cycle_of, self.f, self.seed = api, now_fn, events, cycle_of, findings, seed
        self.taps: list[dict] = []                           # решения, причины, оценки
        self.opens: list[dict] = []                          # открытия приложения (для метрик)
        self.on_going: Callable[[AppUser, ProfileState, str, str | None], None] | None = None   # «иду» → социальный граф
        self.on_rated: Callable[[AppUser, ProfileState, int, dict], None] | None = None         # оценка → момент рекомендации
        self.slug_of: dict[str, str] = {}

    # ───────── базовое ─────────
    def tap(self, u: AppUser, n: int = 1) -> None:
        u.taps += n
        u.active_cycles.add(self.cycle_of(self.now()))

    def _note(self, u: AppUser, code: str, msg: str) -> None:
        self.f.add(code, msg, u.uid, self.now())

    # ───────── первый вход и онбординг ─────────
    async def first_visit(self, u: AppUser) -> str:
        """Ссылка → гостевой аккаунт → галочка согласия → «Начать». До галочки ничего не сохраняется (кроме самой сессии)."""
        p = u.p
        u.onb.setdefault("started", self.now().isoformat())
        u.onb.setdefault("taps_at_start", u.taps)
        st, js = await self.api.session()
        if st != 200 or not isinstance(js, dict) or not js.get("user_id"):
            self._note(u, "session_failed", f"POST /api/session → {st} {str(js)[:80]}")
            u.status = "abandoned"
            return "stuck"
        u.uid, u.status = int(js["user_id"]), "guest"
        u.profiles = [ProfileState(pid=u.uid, kind="self", p=p, name=p.name)]              # основной профиль «я»: user_id = id аккаунта
        steps = u.onb.setdefault("steps", {})
        if p.abandon_step == "consent":
            steps["consent"] = 0
            u.status = "abandoned"
            u.onb["abandoned_at"] = "consent"
            return "abandoned"
        self.tap(u)                                         # галочка
        st, prof = await self.api.put_profile(u.uid, consent=True, name=p.name)
        if st != 200 or not (isinstance(prof, dict) and prof.get("has_consent")):
            self._note(u, "consent_failed", f"PUT consent → {st} has_consent={prof.get('has_consent') if isinstance(prof, dict) else None}")
            u.status = "abandoned"
            return "stuck"
        self.tap(u)                                         # «Начать»
        steps["consent"] = u.taps - u.onb["taps_at_start"]
        return "ok"

    async def onboard(self, u: AppUser) -> str:
        """Профиль «я»: аккаунт, согласие, Шаг 1, Шаг 2. Возвращает completed | abandoned | stuck."""
        res = await self.first_visit(u)
        if res != "ok":
            return res
        u.status = "onboarding"
        out = await self.onboard_profile(u, u.profiles[0], u.onb, first=True)
        if out == "completed":
            u.status = "active"
            u.onboarded_t = self.now()
            u.onb["taps_total"] = u.taps - u.onb["taps_at_start"]
        elif out == "abandoned":
            u.status = "abandoned"
            u.onb["taps_total"] = u.taps - u.onb["taps_at_start"]
        return out

    async def onboard_profile(self, u: AppUser, ps: ProfileState, onb: dict, first: bool = False) -> str:
        """Шаг 1 (пять ценностей, автопереход) → Шаг 2 (восемь направлений, бюджет) → «Показать подборку» для одного профиля."""
        p = ps.p
        steps = onb.setdefault("steps", {})
        mark = u.taps
        for i, _v in enumerate(p.top_values):
            if first and p.abandon_step == "values" and i == p.abandon_sub:
                steps["values"] = u.taps - mark
                onb["abandoned_at"] = "values"
                return "abandoned"
            self.tap(u)
        onb["auto_advance"] = True
        if first and p.misclick_step == "values" and not onb.get("misclick"):
            self.tap(u, 4)                                  # «← Назад», снять, выбрать, «Дальше →»
            onb["misclick"] = {"step": "values", "recovery": "back"}
            self._note(u, "misclick_fixed_with_back", "ошибся в ценностях, исправил через «← Назад» (4 нажатия)")
        weights = {v: int(w) for v, w in p.value_w.items()}
        st, prof = await self.api.put_profile(ps.pid, values=weights)
        steps["values"] = u.taps - mark
        mark = u.taps
        if st != 200:
            self._note(u, "values_failed", f"PUT values → {st}")
            return "stuck"
        shown = proposed_categories(dict(weights))                       # восемь предложенных направлений (как на экране веба)
        pre = {c: int(v) for c, v in propose_interests(dict(weights)).items()}
        srv = {c: int(v) for c, v in (prof.get("interests") or {}).items()} if isinstance(prof, dict) else {}
        if srv and srv != pre:
            onb["server_prefill_differs"] = True
        onb["prefill"] = {"counts": {}, "match": sum(1 for c in ALL_CATS if pre[c] == p.interest_targets[c]), "total": len(ALL_CATS),
                          "shown": len(shown), "shown_match": sum(1 for c in shown if pre[c] == p.interest_targets[c])}
        final = dict(pre)
        left = p.max_interest_taps if not (first and p.abandon_step == "interests") else min(3, p.max_interest_taps)
        edits = 0
        if p.budget_on_step:
            self.tap(u)
            onb["budget_set"] = "step"
        for c in [c for c in shown if p.interest_targets[c] == 0]:
            if left <= 0:
                break
            self.tap(u)
            final[c] = 0
            left -= 1
            edits += 1
        want = sorted([c for c in ALL_CATS if p.interest_targets[c] >= 2 and pre[c] < 2], key=lambda c: -p.interest_targets[c])
        if want and left >= 2:
            self.tap(u)                                     # «Все направления»
            left -= 1
            edits += 1
            onb["used_all_screen"] = True
            brush = 2
            for c in want:
                if left <= 0:
                    break
                tgt = p.interest_targets[c]
                if tgt != brush:
                    self.tap(u)
                    brush = tgt
                    left -= 1
                    edits += 1
                    if left <= 0:
                        break
                self.tap(u)
                final[c] = tgt
                left -= 1
                edits += 1
        onb["interest_edits"] = edits
        if first and p.abandon_step == "interests":
            steps["interests"] = u.taps - mark
            onb["abandoned_at"] = "interests"
            return "abandoned"
        self.tap(u)                                         # «Показать подборку →»
        st, prof = await self.api.put_profile(ps.pid, interests=final, params={"budget": p.budget if onb.get("budget_set") else 0}, onboarded=True)
        prof = prof if isinstance(prof, dict) else {}
        steps["interests"] = u.taps - mark
        if st != 200 or not prof.get("onboarded"):
            self._note(u, "onboarded_failed", f"PUT onboarded → {st} onboarded={prof.get('onboarded') if isinstance(prof, dict) else None}")
            return "stuck"
        onb["completed"] = self.now().isoformat()
        return "completed"

    async def add_second_profile(self, u: AppUser, kind: str) -> bool:
        """У ~20 % персон второй профиль («ребёнок» или «мама»): другие ценности, свой онбординг, решения по нему отдельно."""
        if u.uid is None or len(u.profiles) > 1:
            return False
        rng = u.rng
        arch = rng.choice(SECOND_ARCH[kind])
        persona = make_persona(self.seed, 3000 + u.p.idx, arch, 50)
        self.tap(u)                                         # «+» в переключателе профилей
        known = {x.pid for x in u.profiles}
        pname = "Ребёнок" if kind == "child" else "Мама"
        st, js = await self.api.create_profile(u.uid, pname, kind)
        new = [x for x in (js.get("profiles") or []) if isinstance(js, dict) and x.get("user_id") not in known] if st == 200 else []
        if st != 200 or len(new) != 1 or new[0].get("kind") != kind:
            self._note(u, "profile_create_failed", f"POST /api/profiles → {st} {str(js)[:100]}")
            return False
        ps = ProfileState(pid=int(new[0]["user_id"]), kind=kind, p=persona, name=pname)
        u.profiles.append(ps)
        u.second = persona
        out = await self.onboard_profile(u, ps, ps.onb)
        if out != "completed":
            u.profiles.pop()
            return False
        ps.onb["taps_total"] = sum(ps.onb.get("steps", {}).values())
        return True

    # ───────── решения ─────────
    @staticmethod
    def decide(u: AppUser, ps: ProfileState, f: float) -> str | None:
        """go | notmine | None. В ленте два действия («Иду», «Не моё»): «может быть» превращается в «Иду» реже, «интересно» — в пропуск."""
        p, rng = ps.p, u.rng
        likes = rng.random() < sigmoid((f - 0.5) * 8)
        if likes:
            if rng.random() > p.decisive:
                return None
            wg, wm, wi = p.w_go_maybe_interest
            wg *= 0.6 + f
            x = rng.random() * (wg + wm + wi)
            if x < wg:
                return "go"
            return "go" if x < wg + wm and rng.random() < 0.35 else None
        return "notmine" if rng.random() < p.decisive * 0.7 else None

    def pick_day(self, u: AppUser, ps: ProfileState, local: datetime) -> str:
        """Сегодня / завтра / неделя: вечером буднего дня — «Сегодня»; иначе по характеру (спонтанные чаще «сегодня», планирующие — «неделя»)."""
        if is_evening_window(local):
            return "today"
        w = {"evening": (0.55, 0.25, 0.2), "next_day": (0.25, 0.4, 0.35), "weekend": (0.15, 0.25, 0.6)}[ps.p.delay_profile]
        return u.rng.choices(C.DAYS, w)[0]

    def pick_segment(self, u: AppUser, ps: ProfileState) -> str:
        biz = {"нетворкер", "занятой"}
        r = u.rng.random()
        if ps.p.archetype in biz and r < 0.35:
            return "business"
        return "all" if r > 0.92 else "leisure"

    async def open_app(self, u: AppUser) -> dict | None:
        """Человек сам открыл приложение: профиль (иногда переключил), день, направление, лента, решения, затем «План» с отметкой прошедших."""
        if u.status != "active" or u.uid is None or not u.profiles:
            return None
        rng = u.rng
        now = self.now()
        local = now.astimezone(ZoneInfo(u.p.tz))
        start_taps = u.taps
        if len(u.profiles) > 1 and rng.random() < 0.25:
            u.cur = 1 - u.cur if len(u.profiles) == 2 else rng.randrange(len(u.profiles))
            self.tap(u)
        ps = u.prof
        evening = is_evening_window(local)
        day = self.pick_day(u, ps, local)
        seg = self.pick_segment(u, ps)
        self.tap(u, int(day != "today") + int(seg != "leisure"))
        rec = {"u": u.uid, "pid": ps.pid, "kind": ps.kind, "archetype": ps.p.archetype, "t": now.isoformat(), "cycle": self.cycle_of(now), "evening": evening,
               "day": day, "segment": seg, "cards": 0, "viewed": 0, "decisions": 0, "go": 0, "notmine": 0, "taps_to_go": None, "went": 0, "rated": 0,
               "total": None, "next_offset": None, "days_in_feed": 0, "max_per_day": 0, "paged": 0}
        self.opens.append(rec)
        u.opens.append(rec)
        u.active_cycles.add(rec["cycle"])
        st, fd = await self.api.feed(ps.pid, date=day, segment=seg, limit=20)
        if st != 200 or not isinstance(fd, dict):
            self._note(u, "feed_failed", f"GET feed → {st} {str(fd)[:80]}")
            return rec
        items = list(fd.get("items") or [])
        rec["total"], rec["next_offset"] = fd.get("total"), fd.get("next_offset")
        if fd.get("next_offset") is not None and rng.random() < 0.3:          # долистал до конца страницы: догрузка
            self.tap(u)
            st2, fd2 = await self.api.feed(ps.pid, date=day, segment=seg, limit=20, offset=int(fd["next_offset"]))
            if st2 == 200 and isinstance(fd2, dict):
                items += list(fd2.get("items") or [])
                rec["paged"] = 1
            else:
                self._note(u, "feed_page_failed", f"GET feed offset={fd.get('next_offset')} → {st2}")
        if evening or day == "today":
            bad = [it for it in items if it.get("can_make_it") is False]
            if bad:
                self._note(u, "feed_today_not_reachable", f"в «Сегодня» {len(bad)} событий, на которые не успеть (can_make_it=false)")
            items = [it for it in items if it.get("can_make_it") is not False]
        if not items and day == "today" and rng.random() < 0.6:            # «Сегодня» пусто: переключился на «Завтра»
            self.tap(u)
            rec["fallback"] = "tomorrow"
            st, fd = await self.api.feed(ps.pid, date="tomorrow", segment=seg, limit=20)
            items = list(fd.get("items") or []) if st == 200 and isinstance(fd, dict) else []
        rec["cards"] = len(items)
        per_day = Counter(it.get("day") for it in items)
        rec["days_in_feed"], rec["max_per_day"] = len(per_day), max(per_day.values(), default=0)
        if ps.kind == "child":
            cfg = scoring_config()
            bad = [str((it.get("event") or {}).get("slug")) for it in items if adult_only(self.events.get(str((it.get("event") or {}).get("id"))) or {}, cfg)]
            rec["child_checked"], rec["child_adult"] = len(items), len(bad)
            if bad:
                self._note(u, "child_adult_item", f"в ленте профиля-ребёнка взрослое: {bad[:3]}")
        lo, hi = ps.p.view_range
        n_view = min(len(items), rng.randint(lo, hi) if not evening else rng.randint(3, 5))
        for it in items[:n_view]:
            ev = self.events.get(str((it.get("event") or {}).get("id")))
            if ev is None:
                continue
            rec["viewed"] += 1
            if ps.decisions.get(str(it["event"]["id"]), {}).get("status") in (C.GO, C.MAYBE) or (it.get("decision") or {}).get("status") in (C.GO, C.MAYBE):
                self.tap(u)                                 # уже в плане: листает дальше
                rec["already_going"] = rec.get("already_going", 0) + 1
                continue
            action = self.decide(u, ps, ps.p.fit(ev))
            if action is None:
                self.tap(u)                                 # свайп мимо
                continue
            await self._act(u, ps, rec, it, ev, action, start_taps)
            if evening and action == "go":
                break                                       # «освободился вечер»: выбрал и пошёл, лента больше не нужна
        if rec["decisions"]:
            u.decision_cycles.add(rec["cycle"])
        if rng.random() < (0.8 if ps.decisions else 0.15):
            await self.mark_past(u, ps, rec)
        fits_cover = min(1.0, len(items) / 5.0)
        if rec["viewed"]:
            u.E = max(0.0, min(1.0, 0.8 * u.E + 0.2 * (0.15 + 0.85 * fits_cover * (rec["decisions"] > 0))))
        return rec

    async def _act(self, u: AppUser, ps: ProfileState, rec: dict, it: dict, ev: dict, action: str, start_taps: int) -> None:
        rng = u.rng
        eid = str(it["event"]["id"])
        day = it.get("day")
        days = list(it.get("days") or [])
        if action == "go" and len(days) > 1 and rng.random() < 0.2:
            day = rng.choice([d for d in days if d != day] or days)
            self.tap(u)
        self.tap(u)
        status = C.GO if action == "go" else C.NOT_MINE
        reason = "не моё" if action == "notmine" else None
        st, js = await self.api.decide(ps.pid, eid, status, reason=reason, day=day if action == "go" else None)
        if st != 200 or not isinstance(js, dict) or js.get("status") != status:
            self._note(u, "decision_failed", f"POST decision {status} → {st} {str(js)[:80]}")
            return
        d = ps.decisions.get(eid)
        fresh = d is None or d.get("status") != status
        ps.decisions[eid] = {"status": status, "reason": reason, "day": day, "cycle": rec["cycle"], "category": ev.get("category")}
        self.taps.append({"t": self.now().isoformat(), "u": u.uid, "pid": ps.pid, "kind": "decision", "status": status, "event_id": eid,
                          "cycle": rec["cycle"], "card_day": day, "evening": rec["evening"], "taps": u.taps})
        rec["decisions"] += 1
        if action == "go":
            rec["go"] += 1
            if rec["taps_to_go"] is None:
                rec["taps_to_go"] = u.taps - start_taps
            if u.first_go_taps is None:
                u.first_go_taps = u.taps
            if fresh and self.on_going is not None:
                self.on_going(u, ps, eid, day)
        else:
            rec["notmine"] += 1

    async def mark_past(self, u: AppUser, ps: ProfileState, rec: dict) -> None:
        """Вкладка «План»: прошедшие события с «иду» — «сходил / не сходил» и оценка ★1–5."""
        rng, p = u.rng, ps.p
        self.tap(u)
        st, plan = await self.api.plan(ps.pid)
        if st != 200 or not isinstance(plan, dict):
            self._note(u, "plan_failed", f"GET plan → {st}")
            return
        past = list(plan.get("past") or [])
        for it in past:
            items = [it]
            for it in items:
                eid = str((it.get("event") or {}).get("id"))
                ev = self.events.get(eid)
                if ev is None or it.get("status") not in (C.GO, C.MAYBE) or it.get("rating") or ps.decisions.get(eid, {}).get("marked"):
                    continue
                if rng.random() > p.p_rate:
                    continue
                ps.decisions.setdefault(eid, {})["marked"] = True
                if rng.random() > p.p_attend:
                    self.tap(u)
                    if rng.random() < 0.7:
                        await self.api.decide(ps.pid, eid, C.SKIPPED)
                        ps.decisions[eid]["status"] = C.SKIPPED
                    continue
                f = p.fit(ev)
                rating = int(max(1, min(5, round(1 + 4 * f + p.rating_bias + rng.gauss(0.05, 0.9)))))
                self.tap(u, 2)                              # «сходил» + звёзды
                st, js = await self.api.decide(ps.pid, eid, C.WENT, rating=rating)
                if st != 200 or (isinstance(js, dict) and js.get("rating") not in (None, rating)):
                    self._note(u, "rating_failed", f"POST went/rating {rating} → {st} {str(js)[:80]}")
                    continue
                ps.ratings.append({"event": eid, "rating": rating, "category": ev.get("category")})
                ps.decisions[eid].update(status=C.WENT, rating=rating)
                rec["went"] += 1
                rec["rated"] += 1
                self.taps.append({"t": self.now().isoformat(), "u": u.uid, "pid": ps.pid, "kind": "rating", "rating": rating, "event_id": eid,
                                  "cycle": rec["cycle"]})
                u.E = max(0.0, min(1.0, u.E + (0.05 if rating >= 4 else -0.06 if rating <= 2 else 0.0)))
                if self.on_rated is not None:
                    self.on_rated(u, ps, rating, js if isinstance(js, dict) else {})

    # ───────── персональное обучение: пробы ─────────
    async def top_categories(self, ps: ProfileState, date_: str = "week", segment: str = "all", n: int = C.TOP_N) -> list[str]:
        """Категории первых n событий ленты профиля (для проб обучения)."""
        st, fd = await self.api.feed(ps.pid, date=date_, segment=segment, limit=40)
        if st != 200 or not isinstance(fd, dict):
            return []
        out = []
        for it in (fd.get("items") or [])[:n]:
            ev = self.events.get(str((it.get("event") or {}).get("id"))) or {}
            out.append(ev.get("category"))
        return out

    async def feed_events(self, ps: ProfileState, date_: str = "week", segment: str = "all", limit: int = 40, per_day: int | None = None) -> list[dict]:
        return await self.feed_events_pid(ps.pid, date_, segment, limit, per_day)

    async def feed_events_pid(self, pid: int, date_: str = "week", segment: str = "all", limit: int = 40, per_day: int | None = None) -> list[dict]:
        """per_day=50 снимает лимит «5 карточек на день»: для проб обучения нужен весь ранжированный список, а не первая страница."""
        st, fd = await self.api.feed(pid, date=date_, segment=segment, limit=limit, per_day=per_day)
        return list(fd.get("items") or []) if st == 200 and isinstance(fd, dict) else []

    async def top_categories_pid(self, pid: int, date_: str = "week", segment: str = "all", n: int = C.TOP_N) -> list[str]:
        st, fd = await self.api.feed(pid, date=date_, segment=segment, limit=40)
        if st != 200 or not isinstance(fd, dict):
            return []
        return [(self.events.get(str((it.get("event") or {}).get("id"))) or {}).get("category") for it in (fd.get("items") or [])[:n]]

    async def make_twin(self, u: AppUser, ps: ProfileState) -> dict | None:
        """«Двойник» профиля для проб обучения: новый гостевой аккаунт с теми же ценностями, интересами и бюджетом, но без решений. Контроль."""
        st, js = await self.api.session()
        if st != 200 or not js.get("user_id"):
            return None
        pid = int(js["user_id"])
        prof = (await self.api.get_profile(ps.pid))[1] or {}
        await self.api.put_profile(pid, consent=True, name="Двойник", values=prof.get("values") or {}, interests=prof.get("interests") or {},
                                   params={"budget": int((prof.get("params") or {}).get("budget") or 0)}, onboarded=True)
        return {"uid": pid, "pid": pid}

    async def delete_account(self, u: AppUser) -> bool:
        st, _ = await self.api.delete_profile(u.uid)
        if st == 200:
            u.status = "deleted"
        return st == 200
