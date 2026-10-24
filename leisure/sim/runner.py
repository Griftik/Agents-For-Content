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


def _fb_title(text: str) -> str:
    """Название события из «Как прошло?\n«Название», суббота, 24 окт.»."""
    lines = text.split("\n")
    line = lines[1] if len(lines) > 1 else ""
    if line.startswith("«") and "»" in line:
        return line[1:line.rfind("»")]
    return line


def cycle_of(t: datetime) -> int:
    """Номер недели прогона: цикл 0 = вт 20.10 … пн 26.10 (онбординг, первый уикенд, оценки)."""
    return int((t - START) // timedelta(days=7))


def at_local(d: date, hour: int, tz: str = MSK, minute: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=ZoneInfo(tz)).astimezone(UTC)


WEB_ORIGINAL: dict = {}


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


CLOCK_SQL = [
    "CREATE TABLE sim_clock (id int PRIMARY KEY, now timestamptz NOT NULL)",
    "INSERT INTO sim_clock VALUES (1, '2026-10-20T00:00:00+00')",
    """CREATE FUNCTION sim_stamp() RETURNS trigger AS $$
       BEGIN
         IF TG_TABLE_NAME = 'invite_accepts' THEN
           IF TG_OP = 'INSERT' THEN NEW.opened_at := (SELECT now FROM sim_clock WHERE id = 1); END IF;
         ELSIF TG_TABLE_NAME IN ('invites', 'growth_events') THEN
           IF TG_OP = 'INSERT' THEN NEW.created_at := (SELECT now FROM sim_clock WHERE id = 1); END IF;
         ELSE
           IF TG_OP = 'INSERT' THEN NEW.created_at := (SELECT now FROM sim_clock WHERE id = 1); END IF;
           NEW.updated_at := (SELECT now FROM sim_clock WHERE id = 1);
         END IF;
         RETURN NEW;
       END $$ LANGUAGE plpgsql""",
] + [f"CREATE TRIGGER sim_stamp_{t} BEFORE INSERT OR UPDATE ON {t} FOR EACH ROW EXECUTE FUNCTION sim_stamp()"
     for t in ("profiles", "decisions", "invites", "invite_accepts", "growth_events")]


def install_db_clock(url: str) -> None:
    """Часы БД: `server_default=now()` у created_at/opened_at/updated_at подменяются триггерами, читающими sim_clock. Без этого метрики
    «онбординг в течение двух недель», «просьба о рекомендации не чаще раза в 14 дней» сравнивали бы время симуляции с настоящим."""
    from sqlalchemy import create_engine, text

    eng = create_engine(url, isolation_level="AUTOCOMMIT")
    with eng.connect() as c:
        for q in CLOCK_SQL:
            c.execute(text(q))
    eng.dispose()


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
    """Подменяет в процессе: «сейчас» (services.utcnow → часы симуляции), отправку воркера (в FakeTelegram), паузу между сообщениями
    и публичный URL. Код продукта не меняется — только атрибуты модулей на время прогона."""
    from leisure import settings
    from leisure.api import services
    from leisure.bot import onboarding
    from leisure.worker import send as send_mod

    from leisure.api import invites as inv_service

    from .social_run import API_KEY, BOT_USERNAME, MINIAPP

    saved = (services.utcnow, send_mod.send_messages, send_mod.SEND_INTERVAL, send_mod.RETRY_DELAYS, settings.WEB_BASE_URL,
             onboarding.POLICY_URL)
    saved_api = (settings.API_KEY, settings.BOT_USERNAME, settings.MINIAPP_SHORT_NAME, services.datetime, inv_service.datetime)
    WEB_ORIGINAL.setdefault("url", settings.WEB_BASE_URL)

    class SimDatetime(datetime):
        """`datetime.now()` продукта в модулях профилей и приглашений (consent_at, onboarded_at, accepted_at, просьба о рекомендации)
        отдаёт часы симуляции; остальные операции datetime — настоящие."""

        @classmethod
        def now(cls, tz=None):
            t = clock.now
            return t.astimezone(tz) if tz else t.replace(tzinfo=None)

    settings.API_KEY, settings.BOT_USERNAME, settings.MINIAPP_SHORT_NAME = API_KEY, BOT_USERNAME, MINIAPP
    services.datetime = inv_service.datetime = SimDatetime

    async def fake_send_messages(messages):
        return await send_mod.send_with_bot(world.bot, messages)

    services.utcnow = lambda: clock.now          # единая точка «сейчас» в живых путях бота и воркера (local_today берёт её же)
    send_mod.send_messages = fake_send_messages
    send_mod.SEND_INTERVAL = 0
    send_mod.RETRY_DELAYS = (0, 0, 0)            # паузы повторов 5xx в симуляции не ждём
    if "localhost" in settings.WEB_BASE_URL or "127.0.0.1" in settings.WEB_BASE_URL:
        settings.WEB_BASE_URL = DEFAULT_WEB
    onboarding.POLICY_URL = f"{settings.WEB_BASE_URL.rstrip('/')}/policy"
    try:
        yield
    finally:
        (services.utcnow, send_mod.send_messages, send_mod.SEND_INTERVAL, send_mod.RETRY_DELAYS, settings.WEB_BASE_URL,
         onboarding.POLICY_URL) = saved
        settings.API_KEY, settings.BOT_USERNAME, settings.MINIAPP_SHORT_NAME, services.datetime, inv_service.datetime = saved_api


class LogCatcher(logging.Handler):
    """Собирает WARNING/ERROR продукта и INFO-сообщения воркера «нечего отправить» (пустая подборка → молчание)."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.records: list[dict] = []
        self.nothing: set[tuple[int, str]] = set()

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.WARNING:
            if "нечего отправить" in str(record.msg) and record.args and len(record.args) >= 2:
                self.nothing.add((int(record.args[0]), str(record.args[1])))
            return
        self.records.append({"logger": record.name, "level": record.levelname, "msg": record.getMessage()[:300],
                             "exc": (record.exc_text or (self.format(record).splitlines()[-1] if record.exc_info else ""))[:300]})


# ───────────────────────── симуляция ─────────────────────────
class Sim:
    def __init__(self, personas, weeks: int, seed: int, world, clock: Clock, events: dict[str, dict]) -> None:
        from .actors import Findings, PState

        self.weeks, self.seed, self.world, self.clock = weeks, seed, world, clock
        self.bot = None
        self.dp = None
        self.driver = None
        self.catcher = None
        self.lazy_ticks: set = set()
        self.f = Findings()
        self.states = [PState(p=p, rng=random.Random(f"{seed}:{p.idx}:behavior"), E=p.engagement) for p in personas]
        self.by_uid = {ps.p.user_id: ps for ps in self.states}
        self.events = events
        self.heap: list = []
        self.seq = 0
        self.jobs: list[dict] = []
        self.plan_pushes: list[dict] = []
        self.empty_notices: list[dict] = []
        self.digest_recs: list = []
        self.feedback_sent: list[dict] = []
        self.scenarios: dict = {}
        self.job_fns: dict = {}
        self.resend: dict = {"stage": 0, "tried": []}
        self.social = None              # социальный граф (ТЗ-B); None — без приглашений (--no-social)
        self.social_enabled = True
        self.guest_data: dict = {}
        self._clock_eng = None
        self._clock_written = None

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
            # «План на сегодня» (с 09:00) и «Как прошло?» (с 12:00 на следующий день) теперь идут ежедневно, по флагам на решении
            for off in range(-3, 4):                                    # вт … пн недели прогона
                day = F + timedelta(days=off)
                for tz in tzs:
                    self.push(at_local(day, 9, tz), PRIO_JOB, "job", "plan")
                    self.push(at_local(day, 12, tz), PRIO_JOB, "job", "feedback")
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
        self.push(at_local(FRI0 + timedelta(days=7), 13), PRIO_USER, "not_ready")
        self.push(at_local(FRI0 + timedelta(days=1), 15), PRIO_USER, "nudge_probe")

    def _local_date(self, ps, uid: int) -> str:
        tz = ps.p.tz if ps is not None else MSK
        return self.clock.now.astimezone(ZoneInfo(tz)).date().isoformat()

    def lazy_plan(self, ps) -> None:
        """«Иду» на сегодня после 09:00: в проде часовой запуск плана подберёт его в ближайший :00 — эмулируем этот запуск."""
        nxt = self.clock.now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        if nxt not in self.lazy_ticks:
            self.lazy_ticks.add(nxt)
            self.push(nxt, PRIO_JOB, "job", "plan")

    # ── разбор того, что пришло пользователям ──
    def collect(self, origin: str) -> None:
        from leisure.core.timeutil import MONTHS_GEN

        from .actors import DigestRec, parse_card

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
                if m.text.startswith("Выходные ") and not any(str(b.get("callback_data", "")).startswith("d:") for b in m.buttons()):
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
                    if not rec.cards:                      # пустая подборка: заголовок без карточек — сообщение «ничего не нашлось»
                        m.tag = "empty_notice"
                        self.empty_notices.append({"t": self.clock.now.isoformat(), "u": uid, "origin": origin, "text": m.text[:120]})
                        if ps is not None and origin in ("first", "weekly", "reset"):
                            ps.digest_cycles.add(rec.cycle)
                        continue
                    if ps is not None:
                        ps.digests.append(rec)
                        ps.last_digest = rec
                        if origin in ("first", "weekly", "reset"):
                            ps.digest_cycles.add(rec.cycle)
                    self._inspect_digest(ps, rec, origin)
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
                    self.plan_pushes.append({"t": self.clock.now.isoformat(), "u": uid, "cycle": cycle_of(self.clock.now), "titles": titles,
                                             "date": self._local_date(ps, uid),
                                             "messy_lines": sum(1 for ln in m.text.splitlines() if ln.startswith("• ") and ";" in ln),
                                             "lines": sum(1 for ln in m.text.splitlines() if ln.startswith("• "))})
                    i = j
                    continue
                if m.text.startswith("Как прошло?"):
                    j = i
                    fb = []
                    while j < len(ms) and ms[j].text.startswith("Как прошло?"):
                        ms[j].tag = "feedback"
                        fb.append(ms[j])
                        j += 1
                    self.feedback_sent.append({"t": self.clock.now.isoformat(), "u": uid, "n": len(fb), "cycle": cycle_of(self.clock.now),
                                               "date": self._local_date(ps, uid),
                                               "titles": [_fb_title(x.text) for x in fb]})
                    if ps is not None and ps.status == "active":
                        h = ps.rng.uniform(0.5, 30)
                        self.push(self.clock.now + timedelta(hours=h), PRIO_USER, "react_feedback", (ps, fb))
                    i = j
                    continue
                if "ничего не нашлось" in m.text or "пока пусто" in m.text:
                    m.tag = "empty_notice"
                    self.empty_notices.append({"t": self.clock.now.isoformat(), "u": uid, "origin": origin, "text": m.text[:120]})
                i += 1

    def _inspect_digest(self, ps, rec, origin: str) -> None:
        """Проверки доставленной подборки глазами человека: события уже начались? решение видно на повторной карточке?"""
        local = self.clock.now.astimezone(ZoneInfo(MSK))
        for card in rec.cards:
            ev = self.events.get(card.event_id) or {}
            # выставки и места открыты весь день: «начавшимися» считаем их только после end_time (как и продукт)
            start = ev.get("end_time") if ev.get("kind") in ("выставка", "место") else ev.get("start_time")
            if origin != "weekly" and card.day == local.date().isoformat() and start and start < local.strftime("%H:%M"):
                rec.already_started += 1
                self.f.add("card_already_started", f"«{card.title[:40]}» {'заканчивается' if ev.get('kind') in ('выставка', 'место') else 'начинается'} в {start}, а карточка пришла в {local.strftime('%H:%M')} "
                           f"того же дня ({origin})", rec.uid, self.clock.now)
            if ";" in card.time_text or card.time_text.count(" — ") >= 2:
                rec.messy_time += 1
            prev = ps.decisions.get(card.event_id) if ps is not None else None
            if prev and prev.get("status") in ("иду", "может", "мимо", "интересно") and not any(b.startswith("● ") for b in card.buttons):
                rec.resent_no_status += 1
                self.f.add("resent_card_no_status", f"«{card.title[:40]}» уже отмечена как «{prev['status']}», но пришла без отметки ● ({origin})",
                           rec.uid, self.clock.now)

    @staticmethod
    def _delay(ps, origin: str) -> float:
        rng = ps.rng
        r = rng.random()
        if origin in ("first", "manual", "reset", "rebuilt"):
            return rng.uniform(0, 1) if r < 0.85 else rng.uniform(5, 30)
        fast, mid = {"evening": (0.7, 0.2), "next_day": (0.15, 0.65), "weekend": (0.1, 0.3)}[ps.p.delay_profile]
        if r < fast:
            return rng.uniform(0, 3)
        if r < fast + mid:
            return rng.uniform(10, 22)
        return rng.uniform(30, 60)

    # ── запуск бота так, как это делает продукт ──
    async def startup(self) -> None:
        """Выполняет настоящий leisure.bot.main.run() с подменой токена, класса Bot и start_polling: бот создаётся с теми же
        DefaultBotProperties, набирает команды меню (SetMyCommands) и собирает Dispatcher, который потом принимает все апдейты."""
        from aiogram import Dispatcher

        from leisure import settings
        from leisure.bot import main as bot_main

        from .actors import Driver
        from .fakebot import BOT_TOKEN, make_bot

        seen: dict = {}

        async def fake_polling(dp_self, bot, **kw):
            seen["dp"], seen["allowed_updates"] = dp_self, kw.get("allowed_updates")

        saved = (bot_main.Bot, settings.bot_token, Dispatcher.start_polling)
        root = logging.getLogger()
        root_state = (list(root.handlers), root.level)
        bot_main.Bot = lambda token, **kw: make_bot(self.world, kw.get("default"))
        settings.bot_token = lambda: BOT_TOKEN
        Dispatcher.start_polling = fake_polling
        try:
            await bot_main.run()
        finally:
            bot_main.Bot, settings.bot_token, Dispatcher.start_polling = saved
            root.handlers[:] = root_state[0]
            root.setLevel(root_state[1])
        self.dp, self.bot = seen["dp"], self.world.bot
        cmds = self.world.commands[-1] if self.world.commands else []
        self.scenarios["startup"] = {"commands": [c["command"] for c in cmds], "allowed_updates": seen.get("allowed_updates"),
                                     "parse_mode": str(getattr(self.bot.default, "parse_mode", None))}
        self.driver = Driver(self.world, self.bot, lambda: self.dp, self.clock, self.f, self.events, cycle_of)
        self.driver.on_same_day_go = self.lazy_plan
        if self.social_enabled:
            from .social_run import Social

            self.social = Social(self, {"at_local": at_local, "PRIO_USER": PRIO_USER, "MSK": MSK, "FRI0": FRI0})
            self.driver.on_going = self.social.on_going
            self.driver.on_rated = self.social.on_rated
        await self.fault_probe()

    async def fault_probe(self) -> None:
        """Пробы доставки на трёх сообщениях: разовый 502, стойкий 502 (больше числа повторов), 429, блокировка бота,
        а также консент-экран при WEB_BASE_URL=localhost. Работает настоящий send_with_bot; результат — SendResult."""
        from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter, TelegramServerError
        from aiogram.methods import SendMessage

        from leisure import settings
        from leisure.bot import onboarding
        from leisure.worker import send as send_mod

        uid = 900_999_999
        dummy = SendMessage(chat_id=uid, text="x")

        def e502():
            return TelegramServerError(method=dummy, message="Bad Gateway")

        out: dict = {}
        n_logs = len(self.catcher.records) if self.catcher else 0
        probes = (("server_error_once", [None, e502()]),
                  ("server_error_persistent", [None] + [e502() for _ in range(len(send_mod.RETRY_DELAYS) + 1)]),
                  ("retry_after", [TelegramRetryAfter(method=dummy, message="Too Many Requests", retry_after=0)]),
                  ("blocked", [None, TelegramForbiddenError(method=dummy, message="Forbidden: bot was blocked by the user")]))
        for name, plan in probes:
            before = len(self.world.chats[uid])
            self.world.fail_plan = list(plan)
            res = await send_mod.send_with_bot(self.bot, [(uid, f"m{i}", None) for i in (1, 2, 3)])
            got = [m.text for m in self.world.chats[uid][before:]]
            out[name] = {"sent": res.sent, "undelivered": list(res.undelivered), "blocked": list(res.blocked), "delivered": got,
                         "lost": [f"m{i}" for i in (1, 2, 3) if f"m{i}" not in got]}
        self.world.fail_plan = []
        # согласие при WEB_BASE_URL=localhost: Telegram отклоняет такие URL-кнопки, бот должен дать ссылку текстом
        old = (settings.WEB_BASE_URL, onboarding.POLICY_URL)
        settings.WEB_BASE_URL = "http://localhost:8000"
        onboarding.POLICY_URL = "http://localhost:8000/policy"
        try:
            text, rows = onboarding.hello_message()
            res = await send_mod.send_with_bot(self.bot, [(uid, text, rows)])
            out["localhost"] = {"sent": res.sent, "url_buttons": sum(1 for r in rows for b in r if "url" in b), "link_in_text": "localhost" in text}
        finally:
            settings.WEB_BASE_URL, onboarding.POLICY_URL = old
        self.world.drain_new()
        if self.catcher:
            del self.catcher.records[n_logs:]          # WARNING/ERROR из проб вызваны нами и в статистику логов не входят
        self.scenarios["fault_probe"] = out

    # ── обработчики событий очереди ──
    async def run(self) -> None:
        from leisure.worker import schedules

        await self.startup()

        self.job_fns = {"build": schedules.job_build_digests, "send": schedules.job_send_digests,
                        "plan": schedules.job_plan_today, "feedback": schedules.job_how_was_it,
                        "invites": schedules.job_invite_notifications}
        self.schedule()
        if self.social is not None:
            last = FRI0 + timedelta(days=7 * self.weeks + 3)
            day = START.date()
            while day <= last:                              # в проде job_invite_notifications крутится каждую минуту: гоняем раз в час
                for h in range(24):
                    self.push(datetime(day.year, day.month, day.day, h, 5, tzinfo=UTC), PRIO_JOB, "job", "invites")
                day += timedelta(days=1)
        from sqlalchemy import create_engine, text

        from leisure import settings
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

    # ── проба «недоставленная карточка досылается»: одному человеку в четверговой рассылке 4 раза подряд 502 на первой карточке ──
    def _resend_before(self, name: str) -> None:
        from aiogram.exceptions import TelegramServerError
        from aiogram.methods import SendMessage

        rp = self.resend
        now = self.clock.now
        thu = now.weekday() == 3 and now.hour == 16 and now.minute == 0       # чт 19:00 МСК
        if name != "send" or rp["stage"] != 0 or not thu or now < at_local(FRI0 + timedelta(days=6), 0):
            return
        cands = [ps for ps in self.states if ps.status == "active" and ps.p.tz == MSK and ps.p.user_id not in self.world.blocked
                 and ps.p.user_id not in rp["tried"]]
        if not cands:
            return
        uid = cands[0].p.user_id
        rp.update(uid=uid, stage=1, week=(now.date() - FRI0).days // 7 + 1, chat_len=len(self.world.chats[uid]), log_len=len(self.catcher.records) if self.catcher else 0)
        rp["tried"].append(uid)
        dummy = SendMessage(chat_id=uid, text="x")
        self.world.fail_for[uid] = [None] + [TelegramServerError(method=dummy, message="Bad Gateway") for _ in range(4)]

    async def _resend_after(self, name: str) -> None:
        from leisure.db.models import Digest

        rp = self.resend
        if name != "send" or rp["stage"] == 0 or rp["stage"] == 3:
            return
        uid = rp["uid"]
        wk_start = FRI0 + timedelta(days=7 * rp["week"])

        def facts(s):
            row = s.query(Digest).filter(Digest.user_id == uid, Digest.weekend_start == wk_start).first()
            items = list(row.items or []) if row else []
            return {"row": row is not None and row.sent_at is not None, "items": len(items), "flagged": sum(1 for it in items if it.get("undelivered"))}

        f = await db_call(facts)
        new = [m for m in self.world.chats[uid][rp["chat_len"]:] if not m.from_user]
        cards = [m for m in new if any(str(b.get("callback_data", "")).startswith("d:g:") for b in m.buttons())]
        if rp["stage"] == 1:
            self.world.fail_for.pop(uid, None)
            if not f["row"] or not f["flagged"]:          # у человека не было подборки в эту неделю — попробуем на следующей
                rp["stage"] = 0
                if self.catcher:
                    del self.catcher.records[rp["log_len"]:]
                return
            rp.update(stage=2, items=f["items"], flagged_first=f["flagged"], cards_first=len(cards))
            if self.catcher:
                del self.catcher.records[rp["log_len"]:]       # WARNING о недоставке вызван нашей пробой
            return
        rp.update(stage=3, flagged_after=f["flagged"], cards_after=len(cards), resent=len(cards) - rp["cards_first"])
        self.scenarios["resend_probe"] = {k: rp[k] for k in ("uid", "week", "items", "flagged_first", "cards_first", "flagged_after", "cards_after", "resent")} | {"ran": True}

    async def on_job(self, name: str) -> None:
        self._resend_before(name)
        t0 = time.perf_counter()
        n = await asyncio.to_thread(self.job_fns[name], self.clock.now)
        dt = time.perf_counter() - t0
        before = len(self.world.new_since_drain)
        self.jobs.append({"job": name, "t": self.clock.now.isoformat(), "cycle": cycle_of(self.clock.now), "returned": n,
                          "messages": before, "seconds": round(dt, 3)})
        self.collect("weekly" if name == "send" else name)
        await self._resend_after(name)

    async def on_onboard(self, ps) -> None:
        res = await self.driver.onboard(ps)
        if ps.status != "active":
            ps.onb["result"] = res
            ps.onb["taps_total"] = ps.taps - ps.onb.get("taps_at_start", 0)
        elif ps.p.tz != MSK:
            from leisure.api import services
            tz = ps.p.tz
            await db_call(lambda s: services.update_profile(s, services.get_profile(s, ps.p.user_id), {"tz": tz}, auto_onboarded=False))
        self.collect("first")
        if ps.status == "active" and ps.p.refine:
            self.push(self.clock.now + timedelta(hours=ps.rng.uniform(0.05, 2.0)), PRIO_USER, "refine", ps)

    async def on_refine(self, ps) -> None:
        """«Уточнить под себя» из заголовка первой подборки; пересобранная подборка приходит как origin='rebuilt'."""
        if ps.status != "active":
            return
        await self.driver.refine(ps)
        self.collect("rebuilt")

    async def on_social(self, payload) -> None:
        if self.social is not None:
            await self.social.handle(payload)

    def split_guests(self) -> None:
        """Приглашённые и пришедшие по ссылке не входят в основные метрики п. 11: их наблюдения уходят в отдельные списки раздела «Рост»."""
        guests = set(self.social.guests) if self.social else set()
        gd = self.guest_data
        gd["digest_recs"] = [r for r in self.digest_recs if r.uid in guests]
        self.digest_recs = [r for r in self.digest_recs if r.uid not in guests]
        for name in ("plan_pushes", "feedback_sent", "empty_notices"):
            lst = getattr(self, name)
            gd[name] = [x for x in lst if x["u"] in guests]
            setattr(self, name, [x for x in lst if x["u"] not in guests])
        drv = self.driver
        gd["taps"] = [x for x in drv.taps if x["u"] in guests]
        drv.taps = [x for x in drv.taps if x["u"] not in guests]
        gd["commands"] = [x for x in drv.commands if x["u"] in guests]
        drv.commands = [x for x in drv.commands if x["u"] not in guests]

    async def on_nudge_probe(self, _payload) -> None:
        """Подсказка про бюджет: второй «Мимо — дорого» при бюджете «не важно» (человек без правок бюджета и без других «дорого»)."""
        for ps in self.states:
            if ps.status != "active" or ps.p.budget != 0 or ps.onb.get("budget_set") or ps.p.user_id in self.world.blocked:
                continue
            if any(d.get("reason") == "дорого" for d in ps.decisions.values()):
                continue
            rec = next((r for r in reversed(ps.digests) if len(r.cards) >= 2 and not any(c.event_id in ps.decisions for c in r.cards[:2])), None)
            if rec is None:
                continue
            await self.driver.nudge_probe(ps, rec)
            self.scenarios["nudge_probe"] = {"uid": ps.p.user_id, "week": rec.week}
            return

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
            self.driver.commands[-1]["empty"] = bool(replies) and "пока ничего" in replies[0].text
            self.collect("cmd_plan")

    async def on_cmd_mon(self, payload) -> None:
        ps, w = payload
        if ps.status != "active" or w == 0:
            return
        if ps.rng.random() < ps.p.p_cmd["profile"]:
            await self.driver.run_cmd(ps, "/profile")
        if ps.rng.random() < ps.p.p_cmd["help"]:
            await self.driver.run_cmd(ps, "/help")
        if ps.rng.random() < ps.p.p_cmd["start"]:
            await self.driver.run_cmd(ps, "/start")

    async def on_reset(self, ps) -> None:
        if ps.status != "active":
            return
        before = ps.taps
        res = await self.driver.reset_flow(ps)
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
            ps.E *= 0.96                                       # усталость: интерес к рассылке сам по себе угасает
            if w not in ps.digest_cycles and w > 0:
                ps.E *= 0.85
            if w >= 1 and ps.E < ps.p.churn_thr and ps.rng.random() < 0.5:
                ps.status = "churned"
                ps.churn_cycle = w
                if ps.p.blocks_on_churn:
                    self.world.blocked.add(ps.p.user_id)
                    self.f.add("user_blocked_bot", f"перестал пользоваться (E={ps.E:.2f}) и заблокировал бота", ps.p.user_id, self.clock.now)

    async def on_not_ready(self, _=None) -> None:
        """Брошенный онбординг: человек возвращается и пишет команды, не пройдя настройку — что ему отвечают."""
        res = []
        ab = [ps for ps in self.states if ps.status == "abandoned"][:3]
        for ps in ab:
            for cmd in ("/digest", "/plan", "/profile"):
                replies = await self.driver.run_cmd(ps, cmd)
                res.append({"u": ps.p.user_id, "cmd": cmd, "reply": (replies[0].text[:80] if replies else None)})
        self.scenarios["not_ready"] = res
        self.collect("other")

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
            n0 = len(self.world.chats[ps.p.user_id])
            res = await self.driver.tap(ps, st, btn, "(старый экран онбординга)")
            replies = [m.text for m in self.world.chats[ps.p.user_id][n0:] if not m.from_user]
            rec[bucket].append({"u": ps.p.user_id, "screen": ps.onb.get("abandoned_at"), "button": btn["text"], "handled": res["handled"],
                                "answered": res["answered"], "reply": replies[0] if replies else None})
            if bucket == "after" and (not res["handled"] or not res["answered"]):
                self.f.add("stale_button_dead", f"после перезапуска бота (MemoryStorage пуст) кнопка «{btn['text']}» старого экрана "
                           f"«{ps.onb.get('abandoned_at')}»: handled={res['handled']}, ответа на callback нет — у человека крутится индикатор загрузки",
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

    from leisure.core.catalog import default_aesthetics

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
        dd = {"checked": 0, "mismatch": 0, "earlier": 0, "later": 0, "redecided": 0, "examples": []}
        for ps in sim.states:
            for eid, d in ps.decisions.items():
                row = ddec.get((ps.p.user_id, eid))
                if row is None or d.get("status") != "иду" or not d.get("card_day") or row.day is None:
                    continue
                dd["checked"] += 1
                if row.day.isoformat() != d["card_day"]:
                    dd["mismatch"] += 1
                    dd["earlier" if row.day.isoformat() < d["card_day"] else "later"] += 1
                    dd["redecided"] += int(bool(d.get("redecided")))
                    ev = sim.events.get(eid, {})
                    story = dd.setdefault("story", None)
                    if story is None and ev_title_in_plan(sim, ps.p.user_id, eid, row.day):
                        wd_names = ["понедельник", "вторник", "среду", "четверг", "пятницу", "субботу", "воскресенье"]
                        cd = date.fromisoformat(d["card_day"])
                        dd["story"] = (f"u{ps.p.user_id}: карточка «{(sim.events.get(eid, {}).get('title') or '')[:46]}» обещала {wd_names[cd.weekday()]} {cd.strftime('%d.%m')}; "
                                       f"напоминание «План на сегодня» пришло на {wd_names[row.day.weekday()]} {row.day.strftime('%d.%m')}")
                    if len(dd["examples"]) < 4:
                        dd["examples"].append(f"«{(ev.get('title') or '')[:46]}»: на карточке {d['card_day']}, в БД Decision.day={row.day.isoformat()}, "
                                              f"даты события {ev.get('dates')[:4] if ev.get('dates') else '—'}")
        out["decision_day"] = dd
        # 3. что лежит в Digest.items против отправленного
        delivered: dict = {}
        for rec in sim.digest_recs:
            if rec.origin in ("first", "weekly", "reset", "rebuilt") and rec.week is not None:
                delivered.setdefault((rec.uid, rec.week), []).append([c.event_id for c in rec.cards])
        dg = {"rows_sent": 0, "items_differ": 0, "opened_true": 0, "decisions_count_nonzero": 0, "sent_not_delivered": 0, "examples": []}
        for row in digs:
            if row.sent_at is None:
                continue
            dg["rows_sent"] += 1
            dg["opened_true"] += int(bool(row.opened))
            dg["decisions_count_nonzero"] += int(bool(row.decisions_count))
            dg["decisions_count_sum"] = dg.get("decisions_count_sum", 0) + int(row.decisions_count or 0)
            week = (row.weekend_start - FRI0).days // 7
            if row.user_id == sim.resend.get("uid") and week == sim.resend.get("week"):
                continue                              # пробе специально не доставили карточку: items и сообщение расходятся по замыслу
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
        # пересобранные по «Пересобрать подборку» подборки: попали ли показанные карточки в журнал digests
        digest_users = {r.user_id for r in digs}
        by_row = {(r.user_id, (r.weekend_start - FRI0).days // 7): {str(it.get("event_id")) for it in (r.items or [])} for r in digs if r.sent_at}
        rb = {"digests": 0, "cards": 0, "not_logged": 0, "new_events": 0, "example": None}
        shown_first: dict = {}
        for rec in sim.digest_recs:
            if rec.origin in ("first", "weekly", "reset"):
                shown_first.setdefault((rec.uid, rec.week), set()).update(c.event_id for c in rec.cards)
        for rec in sim.digest_recs:
            if rec.origin != "rebuilt" or rec.uid not in digest_users:      # удалённые по /delete — строк в БД уже нет
                continue
            rb["digests"] += 1
            logged = by_row.get((rec.uid, rec.week), set())
            miss = [c for c in rec.cards if c.event_id not in logged]
            rb["cards"] += len(rec.cards)
            rb["not_logged"] += len(miss)
            rb["new_events"] += sum(1 for c in rec.cards if c.event_id not in shown_first.get((rec.uid, rec.week), set()))
            if miss and rb["example"] is None:
                rb["example"] = f"u{rec.uid}, уикенд {rec.week}: в пересобранной подборке {len(rec.cards)} карточек, в Digest.items нет {len(miss)} из них («{miss[0].title[:40]}»)"
        out["rebuilt"] = rb
        out["digest_rows"] = dg
        out["decisions_with_activity"] = len(decs)
        # 4. сохранённый профиль против намерений персоны
        mism = Counter()
        intent: dict = {}
        for ps in sim.states:
            if ps.onb.get("completed") is None or ps.status == "deleted":
                continue
            pr = profs.get(ps.p.user_id)
            if pr is None:
                continue
            p = ps.p
            prm = pr.params or {}
            ops = ps.onb.get("refine_ops") or []
            top5 = sorted(v for v, w in (pr.values or {}).items() if w == 5)
            if top5 != sorted(p.top_values):
                if ps.onb.get("step1_skipped"):
                    out["step1_skipped_profiles"] = out.get("step1_skipped_profiles", 0) + 1       # «Шаг 1» не показывали: ценности по умолчанию
                else:
                    mism["values"] += 1
            # ожидаемое в профиле: то, что человек реально ввёл в «Уточнить», иначе умолчания продукта
            exp = {"company": "с детьми" if "kids" in ops else "любая", "times": sorted(p.times) if "times" in ops else ["вечер", "день"],
                   "budget": p.budget if ps.onb.get("budget_set") else 0,
                   "aesthetics": p.aesthetics if "aesthetics" in ops else default_aesthetics(p.top_values)}
            if prm.get("company") != exp["company"]:
                mism["company"] += 1
            if sorted(prm.get("times") or []) != sorted(exp["times"]):
                mism["times"] += 1
            if prm.get("budget") != exp["budget"]:
                mism["budget"] += 1
            if bool(prm.get("aesthetics")) != exp["aesthetics"]:
                mism["aesthetics"] += 1
            # разрыв «что хотел человек» — «что в профиле»: у не открывших «Уточнить» остаются умолчания
            gap = [k for k, want, have in (("budget", p.budget, prm.get("budget")), ("aesthetics", p.aesthetics, bool(prm.get("aesthetics"))),
                                           ("times", sorted(p.times), sorted(prm.get("times") or [])),
                                           ("kids", p.company == "с детьми", prm.get("company") == "с детьми"))
                   if want != have]
            g = intent.setdefault("refined" if "refine_ops" in ps.onb else "not_refined", {"n": 0, "with_gap": 0, "fields": Counter()})
            g["n"] += 1
            g["with_gap"] += int(bool(gap))
            g["fields"].update(gap)
        out["profile_mismatch"] = dict(mism)
        out["intent_gap"] = {k: {"n": v["n"], "with_gap": v["with_gap"], "fields": dict(v["fields"])} for k, v in intent.items()}
        # 5. «Иду» → пришло ли напоминание в день события и вопрос «Как прошло?» на следующий день; по дням недели
        titles = {e["id"]: e["title"] for e in sim.events.values()}
        reminded: dict = defaultdict(set)
        for pp in sim.plan_pushes:
            reminded[(pp["u"], pp["date"])].update(pp["titles"])
        asked: dict = defaultdict(set)
        for fb in sim.feedback_sent:
            asked[(fb["u"], fb["date"])].update(fb["titles"])
        last_go: dict = {}
        for t in sorted(sim.driver.taps, key=lambda t: t["t"]):
            if t.get("kind") == "decision":
                last_go[(t["u"], t["event_id"])] = t
        last_day = FRI0 + timedelta(days=7 * sim.weeks + 3)       # последний день прогона (понедельник после последнего уикенда)
        rem = {"Пт": [0, 0, 0], "Сб": [0, 0, 0], "Вс": [0, 0, 0], "Пн–Чт": [0, 0, 0]}
        same_day = [0, 0]
        flags = [0, 0, 0]
        stale_taps = 0
        wrong_day = 0
        for d in decs:
            if d.status != "иду" or d.day is None or d.day > last_day - timedelta(days=1) or d.day < START.date():
                continue
            tap = last_go.get((d.user_id, str(d.event_id)))
            ps = sim.by_uid.get(d.user_id)
            if tap is None or ps is None:
                continue
            tz = ZoneInfo(ps.p.tz)
            tap_local = datetime.fromisoformat(tap["t"]).astimezone(tz)
            if tap["status"] != "иду" or tap_local.date() > d.day or (tap_local.date() == d.day and tap_local.hour >= 23):
                stale_taps += tap_local.date() > d.day                   # нажали, когда день события уже прошёл — напоминать поздно
                continue
            wd = d.day.weekday()
            key = {4: "Пт", 5: "Сб", 6: "Вс"}.get(wd, "Пн–Чт")
            ttl = titles.get(str(d.event_id))
            got = ttl in reminded.get((d.user_id, d.day.isoformat()), set())
            ask = ttl in asked.get((d.user_id, (d.day + timedelta(days=1)).isoformat()), set())
            rem[key][0] += 1
            rem[key][1] += int(got)
            rem[key][2] += int(ask)
            flags[0] += int(d.reminded_at is not None)
            flags[1] += int(d.feedback_asked_at is not None or d.rating is not None)
            flags[2] += 1
            wrong_day += int(not got and any(ttl in v for (u, _), v in reminded.items() if u == d.user_id))
            if tap_local.date() == d.day and tap_local.hour >= 9:
                same_day[0] += 1
                same_day[1] += int(got)
        out["plan_reminders"] = {k: {"going": v[0], "reminded": v[1], "asked_rating": v[2]} for k, v in rem.items()}
        out["plan_reminders"]["same_day_after_9"] = {"going": same_day[0], "reminded": same_day[1]}
        out["plan_reminders"]["flags"] = {"reminded_at": flags[0], "feedback_asked_at": flags[1], "total": flags[2]}
        out["plan_reminders"]["stale_taps"] = stale_taps
        out["plan_reminders"]["reminded_other_day"] = wrong_day
        # 6. заблокировавшие бота: сколько попыток отправки, что с профилем
        blocked = []
        for uid in sorted(sim.world.blocked):
            calls = [c for c in sim.world.calls if c.get("chat_id") == uid and c.get("method") == "SendMessage" and not c.get("ok")]
            blocked.append({"u": uid, "failed_sends": len(calls), "profile_active": bool(profs.get(uid) and profs[uid].active),
                            "failed_digest_attempts": sum(1 for c in calls if (c.get("text") or "").startswith("Выходные"))})
        out["blocked"] = blocked
        out["profiles_active_after_block"] = sum(1 for b in blocked if b["profile_active"] and b["failed_sends"] > 0)   # бот узнал о блокировке только при отказе отправки
    return out


def ev_title_in_plan(sim: Sim, uid: int, event_id: str, day: date) -> bool:
    title = (sim.events.get(event_id) or {}).get("title")
    return any(pp["u"] == uid and pp["date"] == day.isoformat() and title in pp["titles"] for pp in sim.plan_pushes)


def _variant(base: dict, **prm) -> dict:
    return {**base, "params": {**base["params"], **prm}}


def _digest_ids(events: list[dict], profile: dict, weekend: list[str]) -> tuple:
    from leisure.core.recommend import build_digest
    from leisure.core.scoring import score_events

    sc = score_events(events, profile, [], aff=None)
    return tuple(build_digest(events, profile, [], weekend, scores=sc).event_ids())


def sensitivity(sim: Sim) -> dict:
    """Какие ответы онбординга реально меняют подборку: пересчёт дайджеста четверга недели 0 при смене одного параметра."""
    from leisure.api import services
    from leisure.core.catalog import COMPANY_OPTIONS
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
            ref = _digest_ids(events, base, wk)
            total += 1
            prm = base["params"]
            tests = {
                "company": [_variant(base, company=c) for c in COMPANY_OPTIONS if c != prm.get("company")],
                "kids": [_variant(base, kids=not prm.get("kids"))],
                "budget (контроль)": [_variant(base, budget=b) for b in (0, 1000, 5000) if b != prm.get("budget")],
                "times (контроль)": [_variant(base, times=t) for t in (["утро"], ["ночь"])],
                "aesthetics (контроль)": [_variant(base, aesthetics=not prm.get("aesthetics"))],
            }
            for name, vs in tests.items():
                if any(_digest_ids(events, v, wk) != ref for v in vs):
                    changed[name] += 1
    return {"personas": total, "changed": dict(changed)}


# ───────────────────────── сборка результата ─────────────────────────
def build_results(sim: Sim, args: dict, db_url: str, facts: dict, sens: dict, logs: list[dict], duration: float, seed_created: int,
                  nothing: set | None = None) -> dict:
    nothing = nothing or set()
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
            "idx": p.idx, "onboard_offset_h": p.onboard_offset_h, "user_id": p.user_id, "name": p.name, "archetype": p.archetype, "tz": p.tz, "status": ps.status,
            "planned_abandon": p.abandon_step, "abandoned_at": ps.onb.get("abandoned_at"), "stuck": ps.onb.get("stuck"),
            "completed": bool(ps.onb.get("completed")), "onboarding_taps": ps.onb.get("taps_total"),
            "steps_taps": ps.onb.get("steps"), "interest_edits": ps.onb.get("interest_edits"), "redo": ps.onb.get("redo", 0),
            "misclick": ps.onb.get("misclick"), "screens_back": ps.onb.get("screens"),
            "prefill": ps.onb.get("prefill"), "interest_buttons": ps.onb.get("interest_buttons"), "interest_rows": ps.onb.get("interest_rows"),
            "weight_prompts": ps.onb.get("weight_prompts"), "refine": p.refine, "refine_ops": ps.onb.get("refine_ops"),
            "budget_on_step": p.budget_on_step, "budget_set": ps.onb.get("budget_set"), "nudge_seen": ps.onb.get("nudge_seen"),
            "refine_taps": ps.onb.get("refine_taps"), "refine_rebuilt": ps.onb.get("refine_rebuilt"), "used_all_screen": ps.onb.get("used_all_screen"),
            "reset_taps": ps.onb.get("reset_taps"), "top_values": p.top_values, "first_go_taps": ps.first_go_taps, "first_go_cycle": ps.first_go_cycle,
            "active_cycles": sorted(ps.active_cycles), "digest_cycles": sorted(ps.digest_cycles), "churn_cycle": ps.churn_cycle,
            "decisions": len(ps.decisions), "blocked": p.user_id in world.blocked, "E": round(ps.E, 3),
        })
    digests = []
    for r in sim.digest_recs:
        wk = [(FRI0 + timedelta(days=7 * (r.week or 0) + i)).isoformat() for i in range(3)]
        multi = sum(1 for c in r.cards if c.in_weekend and sum(1 for d in (sim.events.get(c.event_id, {}).get("dates") or []) if d in wk) >= 2)
        digests.append({"multi_day_cards": multi, "u": r.uid, "week": r.week, "origin": r.origin, "cycle": r.cycle, "t": r.t, "header": r.header,
                        "cards": len(r.cards), "already_started": r.already_started, "messy_time": r.messy_time, "resent_no_status": r.resent_no_status, "slot_cards": sum(1 for c in r.cards if c.in_weekend),
                        "horizon_cards": sum(1 for c in r.cards if not c.in_weekend), "opened": r.opened,
                        "decisions": r.decisions, "go": r.go, "events": [sim.events.get(c.event_id, {}).get("slug", "?") for c in r.cards],
                        "event_ids": [c.event_id for c in r.cards], "days": [c.day for c in r.cards],
                        "has_interest_button": any("Интересно" in b for c in r.cards for b in c.buttons)})
    screens: list[str] = []
    ref = next((ps for ps in sim.states if ps.onb.get("completed") and not ps.onb.get("redo") and not ps.onb.get("misclick")), None)
    if ref is not None:
        for c in world.calls:
            if c.get("chat_id") == ref.p.user_id and c["method"] in ("SendMessage", "EditMessageText") and c.get("ok") and c.get("text"):
                head = c["text"].split("\n")[0][:90]
                if not screens or screens[-1] != head:
                    screens.append(head)
                if "Профиль сохранён" in c["text"]:
                    break
    jobs = [{k: v for k, v in j.items() if k != "seconds"} for j in sim.jobs]
    job_secs = Counter()
    job_runs = Counter()
    for j in sim.jobs:
        job_secs[j["job"]] += j["seconds"]
        job_runs[j["job"]] += 1
    return {
        "meta": {**args, "db_name": re.sub(r".*/", "", db_url.split("?")[0]), "events_seeded": seed_created,
                 "sim_start": START.isoformat(), "sim_end": sim.clock.now.isoformat(), "updates_fed": sim.driver.updates,
                 "world_calls": len(world.calls), "web_base_url_original": WEB_ORIGINAL.get("url", ""), "archetypes": dict(Counter(ps.p.archetype for ps in sim.states))},
        "volatile": {"duration_s": round(duration, 1), "job_seconds": {k: round(v, 2) for k, v in job_secs.items()},
                     "job_runs": dict(job_runs)},
        "onboarding_screens": screens, "personas": pers, "digests": digests, "decisions": sim.driver.taps, "commands": sim.driver.commands, "jobs": jobs,
        "plan_pushes": sim.plan_pushes, "feedback_sent": sim.feedback_sent, "empty_notices": sim.empty_notices,
        "findings": sim.f.to_dict(), "violations": viol, "db": facts, "sensitivity": sens, "scenarios": sim.scenarios,
        "log_errors": logs, "handler_errors": sim.driver.handler_errors, "empty_sends": [[u, w] for u, w in sorted(nothing)],
    }


def run_simulation(users: int = 50, weeks: int = 5, seed: int = 20261024, db_url: str | None = None, keep_db: bool = False,
                   out_dir: Path | None = None, log_path: Path | None = None, quiet: bool = False, social: bool = True) -> dict:
    t_start = time.perf_counter()
    url = resolve_db_url(db_url)
    guard_db_name(url)
    from . import personas as persmod
    from .fakebot import FakeTelegram

    if not quiet:
        print(f"[sim] база {url.rsplit('/', 1)[-1]}: пересоздаю, миграции, seed…", flush=True)
    create_database(url)
    results: dict | None = None
    try:
        migrate(url)
        install_db_clock(url)
        with use_database(url):
            created = seed_events()
            from leisure.db.models import Event
            from leisure.db.session import session_factory
            from sqlalchemy import select

            with session_factory()() as s:
                events = {str(e.id): e.as_core() for e in s.scalars(select(Event))}
            clock = Clock()
            world = FakeTelegram(now_fn=lambda: clock.now)
            personas = persmod.generate(users, seed)
            catcher = LogCatcher()
            lg = logging.getLogger("leisure")
            old_prop, old_level = lg.propagate, lg.level
            lg.addHandler(catcher)
            lg.propagate = False
            lg.setLevel(logging.INFO)
            logging.getLogger("aiogram").setLevel(logging.WARNING)
            try:
                with patched_product(world, clock):
                    sim = Sim(personas, weeks, seed, world, clock, events)
                    sim.social_enabled = social
                    sim.catcher = catcher
                    if not quiet:
                        print(f"[sim] {len(personas)} персон, {weeks + 1} уикендов, старт {START.date()}", flush=True)
                    asyncio.run(sim.run())
                    sim.split_guests()
                    facts = db_facts(sim)
                    sens = sensitivity(sim)
            finally:
                lg.removeHandler(catcher)
                lg.propagate, lg.level = old_prop, old_level
            args = {"users": users, "weeks": weeks, "seed": seed}
            results = build_results(sim, args, url, facts, sens, catcher.records, time.perf_counter() - t_start, created, catcher.nothing)
            if sim.social is not None:
                results["growth"] = growth_results(sim)
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


def growth_results(sim: Sim) -> dict:
    """Раздел «Рост через друзей»: итоги Social.finalize и данные приглашённых, отделённые от основных метрик (Sim.split_guests)."""
    soc = sim.social
    g = dict(soc.final)
    gd = sim.guest_data
    gids = set(soc.guests)
    ratings = [t["rating"] for t in gd.get("taps", []) if t["kind"] == "rating"]
    g["guests"] = {"digests": len(gd.get("digest_recs", [])), "plan_pushes": len(gd.get("plan_pushes", [])), "feedback_requests": sum(x["n"] for x in gd.get("feedback_sent", [])),
                   "ratings_n": len(ratings), "ratings_mean": round(sum(ratings) / len(ratings), 2) if ratings else None, "users": len(gids),
                   "decisions_taps": sum(1 for t in gd.get("taps", []) if t["kind"] == "decision")}
    g["invites"] = [{**{k: r.get(k) for k in ("n", "inviter", "friend", "inside", "day", "t", "opened", "accept", "declined", "was_new",
                                            "consent_409", "notified", "profile_state")}, "event": r["event_slug"]} for r in soc.invites]
    g["ref"] = {"asks": [{k: v for k, v in x.items() if k != "url"} for x in soc.ref_asks],
                "shares": [{k: v for k, v in x.items() if k not in ("link", "code")} for x in soc.ref_shares],
                "newcomers": [{k: v for k, v in x.items() if k != "code"} for x in soc.ref_newcomers]}
    g["offers"] = soc.offers
    g["onboarding_api"] = soc.onboard_api
    return g


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Симулятор пользователей планировщика досуга")
    ap.add_argument("--users", type=int, default=50)
    ap.add_argument("--weeks", type=int, default=5, help="недель после недели онбординга (всего уикендов = weeks + 1)")
    ap.add_argument("--seed", type=int, default=20261024)
    ap.add_argument("--db-url", default=None, help="база симуляции (имя содержит «sim»); по умолчанию leisure_sim на сервере из DATABASE_URL")
    ap.add_argument("--out-dir", default=str(SIM_DIR), help="куда писать REPORT.md и report.json")
    ap.add_argument("--keep-db", action="store_true", help="не удалять базу симуляции после прогона")
    ap.add_argument("--no-social", action="store_true", help="без социального графа (приглашения друзей, рекомендации)")
    ap.add_argument("--no-log", action="store_true", help="не писать журнал вызовов out/sim_log.jsonl")
    args = ap.parse_args(argv)
    WEB_ORIGINAL["url"] = os.environ.get("WEB_BASE_URL") or "http://localhost:8000 (значение по умолчанию settings.py)"
    os.environ.setdefault("WEB_BASE_URL", DEFAULT_WEB)
    out = Path(args.out_dir)
    log_path = None if args.no_log else out / "out" / "sim_log.jsonl"
    try:
        results = run_simulation(args.users, args.weeks, args.seed, args.db_url, args.keep_db, out, log_path, social=not args.no_social)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        print(f"[sim] прогон упал: {type(e).__name__}: {e}", file=sys.stderr)
        raise
    from . import report

    (out / "out").mkdir(parents=True, exist_ok=True)
    (out / "out" / "run_data.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    metrics = report.write_reports(results, out)
    print(report.console_summary(metrics, results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
