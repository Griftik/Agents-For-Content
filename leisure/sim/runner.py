"""Прогон симуляции: база → онбординг 50 персон через Dispatcher.feed_update → недели с задачами воркера → отчёт.

    python -m leisure.sim.runner --users 50 --weeks 5 --seed 20261024 [--db-url postgresql+psycopg://…/leisure_sim]

Симуляция пишет только в свою базу (имя обязано содержать «sim»): она пересоздаётся в начале и удаляется в конце
(--keep-db оставляет). База разработки не затрагивается никогда.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import heapq
import json
import logging
import os
import random
import re
import subprocess
import sys
import time
from collections import Counter
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

SIM_DIR = Path(__file__).resolve().parent
LEISURE_DIR = SIM_DIR.parent
REPO_DIR = LEISURE_DIR.parent
UTC = timezone.utc
START = datetime(2026, 10, 20, tzinfo=UTC)      # вторник недели, в которой сид ещё свежий
FRI0 = date(2026, 10, 23)                       # пятница первого уикенда
MSK = "Europe/Moscow"
PRIO_JOB, PRIO_USER = 0, 1
JOB_NAMES = ("build", "send", "plan", "feedback")
DEFAULT_WEB = "https://leisure.example.org"


def cycle_of(t: datetime) -> int:
    """Номер недели прогона: цикл 0 = вт 20.10 … пн 26.10 (онбординг, первый уикенд, оценки)."""
    return int((t - START) // timedelta(days=7))


def at_local(d: date, hour: int, tz: str = MSK, minute: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=ZoneInfo(tz)).astimezone(UTC)


class Clock:
    def __init__(self) -> None:
        self.now = START


# ───────────────────────── база ─────────────────────────
def resolve_db_url(db_url: str | None) -> str:
    from sqlalchemy.engine import make_url

    if db_url:
        return db_url
    if os.environ.get("LEISURE_SIM_DATABASE_URL"):
        return os.environ["LEISURE_SIM_DATABASE_URL"]
    from leisure import settings
    return make_url(settings.DATABASE_URL).set(database="leisure_sim").render_as_string(hide_password=False)


def _admin_engine(url: str):
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url

    return create_engine(make_url(url).set(database="postgres"), isolation_level="AUTOCOMMIT")


def guard_db_name(url: str) -> str:
    from sqlalchemy.engine import make_url

    from leisure import settings

    name = make_url(url).database or ""
    dev = make_url(settings.DATABASE_URL).database or ""
    if "sim" not in name.lower() or name == dev:
        raise SystemExit(f"отказ: база симуляции должна содержать «sim» в имени и не совпадать с базой разработки ({dev}); получено «{name}»")
    return name


def create_database(url: str) -> None:
    from sqlalchemy import text

    name = guard_db_name(url)
    eng = _admin_engine(url)
    with eng.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        c.execute(text(f'CREATE DATABASE "{name}"'))
    eng.dispose()


def drop_database(url: str) -> None:
    from sqlalchemy import text

    name = guard_db_name(url)
    eng = _admin_engine(url)
    with eng.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    eng.dispose()


def migrate(url: str) -> None:
    env = {**os.environ, "DATABASE_URL": url}
    r = subprocess.run([sys.executable, "-m", "alembic", "-c", str(LEISURE_DIR / "alembic.ini"), "upgrade", "head"],
                       cwd=REPO_DIR, env=env, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("alembic upgrade head не прошёл:\n" + r.stderr[-1500:])


@contextlib.contextmanager
def use_database(url: str):
    """Переключает движок продукта на url (и возвращает назад): settings.DATABASE_URL + сброс кэшей engine/session_factory."""
    from leisure import settings
    from leisure.db import session as dbs

    old = settings.DATABASE_URL
    try:
        dbs.engine.cache_clear()
        dbs.session_factory.cache_clear()
    except Exception:  # noqa: BLE001
        pass
    settings.DATABASE_URL = url
    try:
        yield
    finally:
        with contextlib.suppress(Exception):
            dbs.engine().dispose()
        dbs.engine.cache_clear()
        dbs.session_factory.cache_clear()
        settings.DATABASE_URL = old


def seed_events() -> int:
    from leisure.db.session import session_factory
    from leisure.seed.load import DEFAULT_FILE, upsert_events

    items = json.loads(Path(DEFAULT_FILE).read_text(encoding="utf-8"))
    with session_factory()() as s:
        created, _ = upsert_events(s, items)
    return created


async def db_call(fn, *args):
    from leisure.db.session import session_factory

    def _c():
        with session_factory()() as s:
            return fn(s, *args)

    return await asyncio.to_thread(_c)


# ───────────────────────── подмена часов и отправки ─────────────────────────
@contextlib.contextmanager
def patched_product(world, clock: Clock):
    """Подменяет в процессе: «сегодня» (часы симуляции), отправку воркера (в FakeTelegram), паузу между сообщениями
    и публичный URL. Код продукта не меняется — только атрибуты модулей на время прогона."""
    from leisure import settings
    from leisure.api import services
    from leisure.bot import onboarding
    from leisure.worker import send as send_mod

    saved = (services.local_today, send_mod.send_messages, send_mod.SEND_INTERVAL, settings.WEB_BASE_URL, onboarding.POLICY_URL)

    def local_today(p=None, now=None):
        zone = ZoneInfo((p.tz if p else None) or settings.DEFAULT_TZ)
        return (now or clock.now).astimezone(zone).date()

    async def fake_send_messages(messages):
        return await send_mod.send_with_bot(world.bot, messages)

    services.local_today = local_today
    send_mod.send_messages = fake_send_messages
    send_mod.SEND_INTERVAL = 0
    if "localhost" in settings.WEB_BASE_URL or "127.0.0.1" in settings.WEB_BASE_URL:
        settings.WEB_BASE_URL = DEFAULT_WEB
    onboarding.POLICY_URL = f"{settings.WEB_BASE_URL.rstrip('/')}/policy"
    try:
        yield
    finally:
        (services.local_today, send_mod.send_messages, send_mod.SEND_INTERVAL, settings.WEB_BASE_URL, onboarding.POLICY_URL) = saved


class LogCatcher(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.records: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append({"logger": record.name, "level": record.levelname, "msg": record.getMessage()[:300],
                             "exc": (record.exc_text or (self.format(record).splitlines()[-1] if record.exc_info else ""))[:300]})


# ───────────────────────── симуляция ─────────────────────────
class Sim:
    def __init__(self, personas, weeks: int, seed: int, world, bot, clock: Clock, events: dict[str, dict]) -> None:
        from leisure.bot.main import build_dispatcher

        from .actors import Driver, Findings, PState

        self.weeks, self.seed, self.world, self.bot, self.clock = weeks, seed, world, bot, clock
        self.f = Findings()
        self.states = [PState(p=p, rng=random.Random(f"{seed}:{p.idx}:behavior"), E=p.engagement) for p in personas]
        self.by_uid = {ps.p.user_id: ps for ps in self.states}
        self.events = events
        self.dp = build_dispatcher()
        self.driver = Driver(world, bot, lambda: self.dp, clock, self.f, events, cycle_of)
        self.heap: list = []
        self.seq = 0
        self.jobs: list[dict] = []
        self.plan_pushes: list[dict] = []
        self.empty_notices: list[dict] = []
        self.digest_recs: list = []
        self.feedback_sent: list[dict] = []
        self.scenarios: dict = {}
        self.job_fns: dict = {}

    # ── очередь ──
    def push(self, t: datetime, prio: int, kind: str, payload=None) -> None:
        heapq.heappush(self.heap, (t, prio, self.seq, kind, payload))
        self.seq += 1

    def schedule(self) -> None:
        tzs = sorted({ps.p.tz for ps in self.states} | {MSK})
        for ps in self.states:
            self.push(START + timedelta(hours=ps.p.onboard_offset_h), PRIO_USER, "onboard", ps)
        for w in range(self.weeks + 1):
            F = FRI0 + timedelta(days=7 * w)
            wed, thu, fri, sat, mon = (F + timedelta(days=d) for d in (-2, -1, 0, 1, 3))
            self.push(at_local(wed, 22), PRIO_JOB, "job", "build")
            for tz in tzs:
                self.push(at_local(thu, 19, tz), PRIO_JOB, "job", "send")
            self.push(at_local(thu, 20), PRIO_JOB, "job", "send")     # «часовые» повторные запуски: ловят дубли
            self.push(at_local(fri, 9), PRIO_JOB, "job", "send")
            for tz in tzs:
                self.push(at_local(sat, 9, tz), PRIO_JOB, "job", "plan")
            self.push(at_local(sat, 15), PRIO_JOB, "job", "plan")
            for tz in tzs:
                self.push(at_local(mon, 12, tz), PRIO_JOB, "job", "feedback")
            self.push(at_local(mon, 18), PRIO_JOB, "job", "feedback")
            for kind, d, h in (("cmd_fri", fri, 12), ("cmd_sat", sat, 11), ("cmd_mon", mon, 19)):
                for ps in self.states:
                    self.push(at_local(d, h), PRIO_USER, kind, (ps, w))
            for ps in self.states:
                if ps.p.reset_week == w:
                    self.push(at_local(mon, 20, minute=30), PRIO_USER, "reset", ps)
                if ps.p.delete_week == w:
                    self.push(at_local(mon, 20), PRIO_USER, "delete", ps)
            self.push(at_local(mon, 22), PRIO_USER, "close", w)
        if self.weeks >= 3:
            self.push(at_local(FRI0 + timedelta(days=21 - 2), 12), PRIO_USER, "fsm_restart")

    # ── разбор того, что пришло пользователям ──
    def collect(self, origin: str) -> None:
        from leisure.core.timeutil import MONTHS_GEN

        from .actors import CardRec, DigestRec, parse_card

        msgs = self.world.drain_new()
        by_uid: dict[int, list] = {}
        for m in msgs:
            by_uid.setdefault(m.chat_id, []).append(m)
        for uid in sorted(by_uid):
            ps = self.by_uid.get(uid)
            ms = by_uid[uid]
            i = 0
            while i < len(ms):
                m = ms[i]
                if m.text.startswith("Выходные ") and "подобрал" in m.text:
                    m.tag = "digest_header"
                    mm = re.match(r"Выходные (\d{1,2})(?:\s*[–-]\s*\d{1,2})?\s+([а-я]+)", m.text)
                    week = None
                    if mm and mm.group(2) in MONTHS_GEN:
                        d = date(2026, MONTHS_GEN.index(mm.group(2)) + 1, int(mm.group(1)))
                        week = (d - FRI0).days // 7
                    rec = DigestRec(uid, week, origin, self.clock.now.isoformat(), cycle_of(self.clock.now), m.mid, m.text.split("\n")[0])
                    j = i + 1
                    while j < len(ms):
                        card = parse_card(ms[j])
                        if card is None:
                            break
                        ms[j].tag = "card"
                        rec.cards.append(card)
                        j += 1
                    i = j
                    if ps is not None:
                        ps.digests.append(rec)
                        ps.last_digest = rec
                        if origin in ("first", "weekly", "reset"):
                            ps.digest_cycles.add(rec.cycle)
                    self.digest_recs.append(rec)
                    if ps is not None and ps.status == "active":
                        self.push(self.clock.now + timedelta(hours=self._delay(ps, origin)), PRIO_USER, "react_digest", (ps, rec))
                    continue
                if m.text.startswith("План на сегодня"):
                    m.tag = "plan_header"
                    titles = []
                    j = i + 1
                    while j < len(ms) and any(b.get("text") == "Google Календарь" for b in ms[j].buttons()):
                        ms[j].tag = "plan_item"
                        titles.append(ms[j].text.split("\n")[0])
                        j += 1
                    self.plan_pushes.append({"t": self.clock.now.isoformat(), "u": uid, "cycle": cycle_of(self.clock.now), "titles": titles})
                    i = j
                    continue
                if m.text.startswith("Как прошло?"):
                    j = i
                    fb = []
                    while j < len(ms) and ms[j].text.startswith("Как прошло?"):
                        ms[j].tag = "feedback"
                        fb.append(ms[j])
                        j += 1
                    self.feedback_sent.append({"t": self.clock.now.isoformat(), "u": uid, "n": len(fb), "cycle": cycle_of(self.clock.now)})
                    if ps is not None and ps.status == "active":
                        h = ps.rng.uniform(0.5, 30)
                        self.push(self.clock.now + timedelta(hours=h), PRIO_USER, "react_feedback", (ps, fb))
                    i = j
                    continue
                if "ничего не нашлось" in m.text or "пока пусто" in m.text:
                    m.tag = "empty_notice"
                    self.empty_notices.append({"t": self.clock.now.isoformat(), "u": uid, "origin": origin, "text": m.text[:120]})
                i += 1

    @staticmethod
    def _delay(ps, origin: str) -> float:
        rng = ps.rng
        r = rng.random()
        if origin in ("first", "manual", "reset"):
            return rng.uniform(0, 1) if r < 0.85 else rng.uniform(5, 30)
        fast, mid = {"evening": (0.7, 0.2), "next_day": (0.15, 0.65), "weekend": (0.1, 0.3)}[ps.p.delay_profile]
        if r < fast:
            return rng.uniform(0, 3)
        if r < fast + mid:
            return rng.uniform(10, 22)
        return rng.uniform(30, 60)

    # ── обработчики событий очереди ──
    async def run(self) -> None:
        from leisure.worker import schedules

        self.job_fns = {"build": schedules.job_build_digests, "send": schedules.job_send_digests,
                        "plan": schedules.job_plan_today, "feedback": schedules.job_how_was_it}
        self.schedule()
        while self.heap:
            t, _, _, kind, payload = heapq.heappop(self.heap)
            if t > self.clock.now:
                self.clock.now = t
            await getattr(self, "on_" + kind)(payload)

    async def on_job(self, name: str) -> None:
        t0 = time.perf_counter()
        n = await asyncio.to_thread(self.job_fns[name], self.clock.now)
        dt = time.perf_counter() - t0
        before = len(self.world.new_since_drain)
        self.jobs.append({"job": name, "t": self.clock.now.isoformat(), "cycle": cycle_of(self.clock.now), "returned": n,
                          "messages": before, "seconds": round(dt, 3)})
        self.collect("weekly" if name == "send" else name)

    async def on_onboard(self, ps) -> None:
        res = await self.driver.onboard(ps)
        if ps.status != "active":
            ps.onb["result"] = res
            ps.onb["taps_total"] = ps.taps - ps.onb.get("taps_at_start", 0)
        elif ps.p.tz != MSK:
            from leisure.api import services
            tz = ps.p.tz
            await db_call(lambda s: services.update_profile(s, services.get_profile(s, ps.p.user_id), {"tz": tz}))
        self.collect("first")

    async def on_react_digest(self, payload) -> None:
        ps, rec = payload
        await self.driver.react_digest(ps, rec)

    async def on_react_feedback(self, payload) -> None:
        ps, fb = payload
        await self.driver.react_feedback(ps, fb)

    async def on_cmd_fri(self, payload) -> None:
        ps, w = payload
        if ps.status != "active" or w == 0:
            return
        silent = w not in ps.digest_cycles
        if ps.rng.random() < (0.5 if silent else ps.p.p_cmd["digest"]):
            await self.driver.run_cmd(ps, "/digest")
            self.collect("manual")

    async def on_cmd_sat(self, payload) -> None:
        ps, w = payload
        if ps.status != "active":
            return
        going = any(d.get("status") == "иду" for d in ps.decisions.values())
        if ps.rng.random() < min(0.9, ps.p.p_cmd["plan"] * (1.6 if going else 0.4)):
            replies = await self.driver.run_cmd(ps, "/plan")
            self.driver.commands[-1]["empty"] = bool(replies) and "пока пуст" in replies[0].text
            self.collect("cmd_plan")

    async def on_cmd_mon(self, payload) -> None:
        ps, w = payload
        if ps.status != "active" or w == 0:
            return
        if ps.rng.random() < ps.p.p_cmd["profile"]:
            await self.driver.run_cmd(ps, "/profile")
        if ps.rng.random() < ps.p.p_cmd["help"]:
            await self.driver.run_cmd(ps, "/help")

    async def on_reset(self, ps) -> None:
        if ps.status != "active":
            return
        before = ps.taps
        res = await self.driver.onboard(ps, "/reset")
        ps.status = "active"
        self.scenarios.setdefault("reset", []).append({"u": ps.p.user_id, "result": res, "taps": ps.taps - before})
        self.collect("reset")

    async def on_delete(self, ps) -> None:
        if ps.status != "active":
            return
        from leisure.db.models import Decision, Profile

        uid = ps.p.user_id
        ok = await self.driver.delete_flow(ps)
        rec = {"u": uid, "deleted": ok}
        if ok:
            exists = await db_call(lambda s: s.get(Profile, uid) is not None)
            rec["profile_after_delete"] = exists
            if ps.last_digest and ps.rng.random() < 0.6:
                card = ps.last_digest.cards[0] if ps.last_digest.cards else None
                st = self.world.get(uid, card.mid) if card else None
                btn = self.driver.find(st, lambda t: t.removeprefix("● ") == "Иду") if st else None
                if btn is not None:
                    res = await self.driver.tap(ps, st, btn, "(старая карточка после /delete)")
                    rec["stale_tap"] = {"handled": res["handled"], "toast": res["toast"]}
                    rec["profile_after_tap"] = await db_call(lambda s: s.get(Profile, uid) is not None)
                    rec["decisions_after_tap"] = await db_call(lambda s: s.query(Decision).filter(Decision.user_id == uid).count())
                    if rec["profile_after_tap"]:
                        self.f.add("profile_resurrected", f"после /delete нажал «Иду» на старой карточке «{card.title[:40]}» → профиль и решение "
                                   f"снова в БД (consent_at пуст)", uid, self.clock.now)
        self.scenarios.setdefault("delete", []).append(rec)
        self.collect("other")

    async def on_close(self, w: int) -> None:
        for ps in self.states:
            if ps.status != "active":
                continue
            if w not in ps.digest_cycles and w > 0:
                ps.E *= 0.85
            if w >= 1 and ps.E < ps.p.churn_thr and ps.rng.random() < 0.5:
                ps.status = "churned"
                ps.churn_cycle = w
                if ps.p.blocks_on_churn:
                    self.world.blocked.add(ps.p.user_id)
                    self.f.add("user_blocked_bot", f"перестал пользоваться (E={ps.E:.2f}) и заблокировал бота", ps.p.user_id, self.clock.now)

    async def on_fsm_restart(self, _=None) -> None:
        """Брошенный онбординг: человек возвращается к старому экрану. Сначала при живом FSM, затем после перезапуска бота."""
        cand = [ps for ps in self.states if ps.status == "abandoned" and ps.onb.get("abandoned_at") not in (None, "consent")
                and ps.onb.get("last_mid")]
        rec: dict = {"before": [], "after": []}

        async def stale(ps, bucket: str) -> None:
            st = self.world.get(ps.p.user_id, ps.onb["last_mid"])
            btn = next((b for b in (st.buttons() if st else []) if "callback_data" in b and b["callback_data"] != "ob:noop"), None)
            if btn is None:
                return
            res = await self.driver.tap(ps, st, btn, "(старый экран онбординга)")
            rec[bucket].append({"u": ps.p.user_id, "screen": ps.onb.get("abandoned_at"), "button": btn["text"], "handled": res["handled"],
                                "answered": res["answered"]})
            if bucket == "after" and not res["handled"]:
                self.f.add("stale_button_dead", f"после перезапуска бота (MemoryStorage пуст) кнопка «{btn['text']}» старого экрана "
                           f"«{ps.onb.get('abandoned_at')}»: handled={res['handled']}, ответа на callback нет — у человека крутится часик",
                           ps.p.user_id, self.clock.now)

        for ps in cand[:2]:
            await stale(ps, "before")
        # перезапуск процесса бота: роутеры — синглтоны модулей, поэтому «теряем» именно то, что теряется при рестарте, — MemoryStorage
        from aiogram.fsm.storage.memory import MemoryStorage

        self.dp.fsm.storage = MemoryStorage()
        for ps in cand[2:4]:
            await stale(ps, "after")
        self.scenarios["fsm_restart"] = rec
        self.collect("other")


# ───────────────────────── проверки по БД после прогона ─────────────────────────
def db_facts(sim: Sim) -> dict:
    from sqlalchemy import select

    from leisure.db.models import Decision, Digest, Profile
    from leisure.db.session import session_factory

    uids = [ps.p.user_id for ps in sim.states]
    out: dict = {}
    with session_factory()() as s:
        profs = {p.user_id: p for p in s.scalars(select(Profile).where(Profile.user_id.in_(uids)))}
        decs = s.scalars(select(Decision).where(Decision.user_id.in_(uids))).all()
        digs = s.scalars(select(Digest).where(Digest.user_id.in_(uids))).all()
        ddec = {(d.user_id, str(d.event_id)): d for d in decs}
        out["profiles"] = {"total": len(profs), "onboarded": sum(1 for p in profs.values() if p.onboarded_at),
                           "consent_only": sum(1 for p in profs.values() if p.consent_at and not p.onboarded_at),
                           "created_not_onboarded": sum(1 for p in profs.values() if not p.onboarded_at)}
        # 1. целостность решений: то, что нажали, лежит в БД
        miss = bad = 0
        for ps in sim.states:
            if ps.status == "deleted":
                continue
            for eid, d in ps.decisions.items():
                row = ddec.get((ps.p.user_id, eid))
                if d.get("status") is None:
                    continue
                if row is None:
                    miss += 1
                    sim.f.add("decision_not_saved", f"нажатие «{d['status']}» не нашлось в БД", ps.p.user_id)
                elif row.status != d["status"] or (d["status"] == "мимо" and (row.reason or "") != (d.get("reason") or "")):
                    bad += 1
                    sim.f.add("decision_mismatch", f"в БД {row.status}/{row.reason}, нажато {d['status']}/{d.get('reason')}", ps.p.user_id)
                if d.get("rating") and row is not None and row.rating != d["rating"]:
                    sim.f.add("rating_mismatch", f"в БД {row.rating}, поставлено {d['rating']}", ps.p.user_id)
        out["decision_integrity"] = {"missing": miss, "mismatch": bad,
                                     "checked": sum(len(ps.decisions) for ps in sim.states if ps.status != "deleted")}
        # 2. день решения в БД против дня на карточке
        from collections import defaultdict
        dd = {"checked": 0, "mismatch": 0, "examples": []}
        by_wd: dict = defaultdict(int)
        for ps in sim.states:
            for eid, d in ps.decisions.items():
                row = ddec.get((ps.p.user_id, eid))
                if row is None or d.get("status") != "иду" or not d.get("card_day") or row.day is None:
                    continue
                dd["checked"] += 1
                if row.day.isoformat() != d["card_day"]:
                    dd["mismatch"] += 1
                    ev = sim.events.get(eid, {})
                    if len(dd["examples"]) < 4:
                        dd["examples"].append(f"«{(ev.get('title') or '')[:46]}»: на карточке {d['card_day']}, в БД Decision.day={row.day.isoformat()}, "
                                              f"даты события {ev.get('dates')[:4] if ev.get('dates') else '—'}")
        out["decision_day"] = dd
        # 3. что лежит в Digest.items против отправленного
        delivered: dict = {}
        for rec in sim.digest_recs:
            if rec.origin in ("first", "weekly", "reset") and rec.week is not None:
                delivered.setdefault((rec.uid, rec.week), []).append([c.event_id for c in rec.cards])
        dg = {"rows_sent": 0, "items_differ": 0, "opened_true": 0, "decisions_count_nonzero": 0, "sent_not_delivered": 0, "examples": []}
        for row in digs:
            if row.sent_at is None:
                continue
            dg["rows_sent"] += 1
            dg["opened_true"] += int(bool(row.opened))
            dg["decisions_count_nonzero"] += int(bool(row.decisions_count))
            week = (row.weekend_start - FRI0).days // 7
            got = delivered.get((row.user_id, week))
            if not got:
                dg["sent_not_delivered"] += 1
                continue
            stored = {str(it.get("event_id")) for it in (row.items or [])}
            if stored != set(got[-1]):
                dg["items_differ"] += 1
                if len(dg["examples"]) < 3:
                    only_db = len(stored - set(got[-1]))
                    only_msg = len(set(got[-1]) - stored)
                    dg["examples"].append(f"u{row.user_id}, уикенд {row.weekend_start}: в сообщении {len(got[-1])} событий, в Digest.items "
                                          f"{len(stored)} (только в БД: {only_db}, только в сообщении: {only_msg})")
        out["digest_rows"] = dg
        out["decisions_with_activity"] = len(decs)
        # 4. сохранённый профиль против намерений персоны
        mism = Counter()
        for ps in sim.states:
            if ps.onb.get("completed") is None or ps.status == "deleted":
                continue
            pr = profs.get(ps.p.user_id)
            if pr is None:
                continue
            p = ps.p
            prm = pr.params or {}
            top5 = sorted(v for v, w in (pr.values or {}).items() if w == 5)
            if top5 != sorted(p.top_values):
                mism["values"] += 1
            if prm.get("company") != p.company:
                mism["company"] += 1
            if sorted(prm.get("times") or []) != sorted(p.times):
                mism["times"] += 1
            if prm.get("budget") != p.budget:
                mism["budget"] += 1
            if bool(prm.get("aesthetics")) != p.aesthetics:
                mism["aesthetics"] += 1
            if (prm.get("areas") or [None])[0] != p.area:
                mism["areas"] += 1
            want_note = "/help" if p.help_at_notes else p.note
            if (pr.notes or "") != want_note:
                mism["notes"] += 1
        out["profile_mismatch"] = dict(mism)
        # 5. «Иду» → попал ли в напоминание «План на сегодня»; по дням недели
        titles = {e["id"]: e["title"] for e in sim.events.values()}
        reminded: dict = defaultdict(set)
        for pp in sim.plan_pushes:
            reminded[pp["u"]].update(pp["titles"])
        plan_take = {t["event_id"]: t for t in sim.driver.taps if t.get("kind") == "decision" and t["status"] == "иду"}
        rem = {"Пт": [0, 0], "Сб": [0, 0], "Вс": [0, 0], "прочее": [0, 0]}
        late = 0
        sat_plan_time: dict = defaultdict(list)
        for j in sim.jobs:
            if j["job"] == "plan":
                sat_plan_time[j["cycle"]].append(j["t"])
        for d in decs:
            if d.status != "иду" or d.day is None or d.day > FRI0 + timedelta(days=7 * sim.weeks + 2):
                continue
            wd = d.day.weekday()
            key = {4: "Пт", 5: "Сб", 6: "Вс"}.get(wd, "прочее")
            got = titles.get(str(d.event_id)) in reminded.get(d.user_id, set())
            rem[key][0] += 1
            rem[key][1] += int(got)
            if key == "Сб" and not got:
                tt = plan_take.get(str(d.event_id))
                cyc = (d.day - FRI0).days // 7
                if tt and sat_plan_time.get(cyc) and tt["t"] > min(sat_plan_time[cyc]):
                    late += 1
        out["plan_reminders"] = {k: {"going": v[0], "reminded": v[1]} for k, v in rem.items()}
        out["plan_reminders"]["saturday_missed_decided_after_plan_job"] = late
        # 6. заблокировавшие бота: сколько попыток отправки, что с профилем
        blocked = []
        for uid in sorted(sim.world.blocked):
            att = sum(1 for c in sim.world.calls if c.get("chat_id") == uid and c.get("method") == "SendMessage" and not c.get("ok"))
            blocked.append({"u": uid, "failed_sends": att, "profile_active": bool(profs.get(uid) and profs[uid].active)})
        out["blocked"] = blocked
        out["profiles_active_after_block"] = sum(1 for b in blocked if b["profile_active"])
    return out


def sensitivity(sim: Sim) -> dict:
    """Какие ответы онбординга реально меняют подборку: пересчёт дайджеста четверга недели 0 при смене одного параметра."""
    from leisure.api import services
    from leisure.core.catalog import AREA_OPTIONS, COMPANY_OPTIONS
    from leisure.core.recommend import build_digest
    from leisure.core.scoring import score_events
    from leisure.core.timeutil import weekend_iso
    from leisure.db.models import Profile
    from leisure.db.session import session_factory

    today = date(2026, 10, 22)
    wk = weekend_iso(today)
    uids = [ps.p.user_id for ps in sim.states if ps.onb.get("completed")]
    changed: Counter = Counter()
    total = 0
    with session_factory()() as s:
        for uid in uids:
            p = s.get(Profile, uid)
            if p is None or p.onboarded_at is None:
                continue
            events = services.upcoming_events(s, p.city, today)
            base = p.as_core()

            def ids(prof) -> tuple:
                sc = score_events(events, prof, [], aff=None)
                return tuple(build_digest(events, prof, [], wk, scores=sc).event_ids())

            ref = ids(base)
            total += 1

            def variant(**prm):
                v = {**base, "params": {**base["params"], **prm}}
                return v

            tests = {
                "company": [variant(company=c) for c in COMPANY_OPTIONS if c != base["params"].get("company")],
                "areas": [variant(areas=[a]) for a in AREA_OPTIONS if [a] != base["params"].get("areas")],
                "kids": [variant(kids=not base["params"].get("kids"))],
                "notes": [{**base, "notes": "ищу тишину, природу и камерные места, не люблю шум"}],
                "budget (контроль)": [variant(budget=b) for b in (0, 1000, 5000) if b != base["params"].get("budget")],
                "times (контроль)": [variant(times=t) for t in (["утро"], ["ночь"])],
                "aesthetics (контроль)": [variant(aesthetics=not base["params"].get("aesthetics"))],
            }
            for name, vs in tests.items():
                if any(ids(v) != ref for v in vs):
                    changed[name] += 1
    return {"personas": total, "changed": dict(changed)}


# ───────────────────────── сборка результата ─────────────────────────
def build_results(sim: Sim, args: dict, db_url: str, facts: dict, sens: dict, logs: list[dict], duration: float, seed_created: int) -> dict:
    world = sim.world
    viol: dict = {}
    for v in world.violations:
        e = viol.setdefault(v["code"], {"count": 0, "examples": []})
        e["count"] += 1
        if len(e["examples"]) < 3:
            e["examples"].append(v["detail"][:200])
    pers = []
    for ps in sim.states:
        p = ps.p
        pers.append({
            "idx": p.idx, "user_id": p.user_id, "name": p.name, "archetype": p.archetype, "tz": p.tz, "status": ps.status,
            "planned_abandon": p.abandon_step, "abandoned_at": ps.onb.get("abandoned_at"), "stuck": ps.onb.get("stuck"),
            "completed": bool(ps.onb.get("completed")), "onboarding_taps": ps.onb.get("taps_total"),
            "steps_taps": ps.onb.get("steps"), "interest_edits": ps.onb.get("interest_edits"), "redo": ps.onb.get("redo", 0),
            "misclick": ps.onb.get("misclick"), "screens_back": ps.onb.get("screens"),
            "interest_buttons": ps.onb.get("interest_buttons"), "interest_rows": ps.onb.get("interest_rows"),
            "weight_prompts": ps.onb.get("weight_prompts"), "first_go_taps": ps.first_go_taps, "first_go_cycle": ps.first_go_cycle,
            "active_cycles": sorted(ps.active_cycles), "digest_cycles": sorted(ps.digest_cycles), "churn_cycle": ps.churn_cycle,
            "decisions": len(ps.decisions), "blocked": p.user_id in world.blocked, "E": round(ps.E, 3),
        })
    digests = []
    for r in sim.digest_recs:
        digests.append({"u": r.uid, "week": r.week, "origin": r.origin, "cycle": r.cycle, "t": r.t, "header": r.header,
                        "cards": len(r.cards), "slot_cards": sum(1 for c in r.cards if c.in_weekend),
                        "horizon_cards": sum(1 for c in r.cards if not c.in_weekend), "opened": r.opened,
                        "decisions": r.decisions, "go": r.go, "events": [sim.events.get(c.event_id, {}).get("slug", "?") for c in r.cards],
                        "event_ids": [c.event_id for c in r.cards], "days": [c.day for c in r.cards],
                        "has_interest_button": any("Интересно" in b for c in r.cards for b in c.buttons)})
    jobs = [{k: v for k, v in j.items() if k != "seconds"} for j in sim.jobs]
    job_secs = Counter()
    job_runs = Counter()
    for j in sim.jobs:
        job_secs[j["job"]] += j["seconds"]
        job_runs[j["job"]] += 1
    return {
        "meta": {**args, "db_name": re.sub(r".*/", "", db_url.split("?")[0]), "events_seeded": seed_created,
                 "sim_start": START.isoformat(), "sim_end": sim.clock.now.isoformat(), "updates_fed": sim.driver.updates,
                 "world_calls": len(world.calls), "archetypes": dict(Counter(ps.p.archetype for ps in sim.states))},
        "volatile": {"duration_s": round(duration, 1), "job_seconds": {k: round(v, 2) for k, v in job_secs.items()},
                     "job_runs": dict(job_runs)},
        "personas": pers, "digests": digests, "decisions": sim.driver.taps, "commands": sim.driver.commands, "jobs": jobs,
        "plan_pushes": sim.plan_pushes, "feedback_sent": sim.feedback_sent, "empty_notices": sim.empty_notices,
        "findings": sim.f.to_dict(), "violations": viol, "db": facts, "sensitivity": sens, "scenarios": sim.scenarios,
        "log_errors": logs, "handler_errors": sim.driver.handler_errors,
    }


def run_simulation(users: int = 50, weeks: int = 5, seed: int = 20261024, db_url: str | None = None, keep_db: bool = False,
                   out_dir: Path | None = None, log_path: Path | None = None, quiet: bool = False) -> dict:
    t_start = time.perf_counter()
    url = resolve_db_url(db_url)
    guard_db_name(url)
    from . import personas as persmod
    from .fakebot import FakeTelegram, make_bot

    if not quiet:
        print(f"[sim] база {url.rsplit('/', 1)[-1]}: пересоздаю, миграции, seed…", flush=True)
    create_database(url)
    results: dict | None = None
    try:
        migrate(url)
        with use_database(url):
            created = seed_events()
            from leisure.db.models import Event
            from leisure.db.session import session_factory
            from sqlalchemy import select

            with session_factory()() as s:
                events = {str(e.id): e.as_core() for e in s.scalars(select(Event))}
            clock = Clock()
            world = FakeTelegram(now_fn=lambda: clock.now)
            bot = make_bot(world)
            personas = persmod.generate(users, seed)
            catcher = LogCatcher()
            lg = logging.getLogger("leisure")
            old_prop, old_level = lg.propagate, lg.level
            lg.addHandler(catcher)
            lg.propagate = False
            lg.setLevel(logging.WARNING)
            logging.getLogger("aiogram").setLevel(logging.WARNING)
            try:
                with patched_product(world, clock):
                    sim = Sim(personas, weeks, seed, world, bot, clock, events)
                    if not quiet:
                        print(f"[sim] {len(personas)} персон, {weeks + 1} уикендов, старт {START.date()}", flush=True)
                    asyncio.run(sim.run())
                    facts = db_facts(sim)
                    sens = sensitivity(sim)
            finally:
                lg.removeHandler(catcher)
                lg.propagate, lg.level = old_prop, old_level
            args = {"users": users, "weeks": weeks, "seed": seed}
            results = build_results(sim, args, url, facts, sens, catcher.records, time.perf_counter() - t_start, created)
            if log_path is not None:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                with log_path.open("w", encoding="utf-8") as fh:
                    for rec in world.calls:
                        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                results["meta"]["log_file"] = str(log_path.name)
    finally:
        if not keep_db:
            with contextlib.suppress(Exception):
                drop_database(url)
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Симулятор пользователей планировщика досуга")
    ap.add_argument("--users", type=int, default=50)
    ap.add_argument("--weeks", type=int, default=5, help="недель после недели онбординга (всего уикендов = weeks + 1)")
    ap.add_argument("--seed", type=int, default=20261024)
    ap.add_argument("--db-url", default=None, help="база симуляции (имя содержит «sim»); по умолчанию leisure_sim на сервере из DATABASE_URL")
    ap.add_argument("--out-dir", default=str(SIM_DIR), help="куда писать REPORT.md и report.json")
    ap.add_argument("--keep-db", action="store_true", help="не удалять базу симуляции после прогона")
    ap.add_argument("--no-log", action="store_true", help="не писать журнал вызовов out/sim_log.jsonl")
    args = ap.parse_args(argv)
    os.environ.setdefault("WEB_BASE_URL", DEFAULT_WEB)
    out = Path(args.out_dir)
    log_path = None if args.no_log else SIM_DIR / "out" / "sim_log.jsonl"
    try:
        results = run_simulation(args.users, args.weeks, args.seed, args.db_url, args.keep_db, out, log_path)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        print(f"[sim] прогон упал: {type(e).__name__}: {e}", file=sys.stderr)
        raise
    from . import report

    (SIM_DIR / "out").mkdir(exist_ok=True)
    (SIM_DIR / "out" / "run_data.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    metrics = report.write_reports(results, out)
    print(report.console_summary(metrics, results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
