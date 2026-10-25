"""Общее для симулятора: часы, недели прогона, база симуляции (создаётся и удаляется прогоном), журнал продукта, наблюдения."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import subprocess
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

SIM_DIR = Path(__file__).resolve().parent
LEISURE_DIR = SIM_DIR.parent
REPO_DIR = LEISURE_DIR.parent
UTC = timezone.utc
START = datetime(2026, 10, 20, tzinfo=UTC)      # вторник недели, в которой сид ещё свежий
FRI0 = date(2026, 10, 23)                       # пятница первого уикенда
MSK = "Europe/Moscow"
DEFAULT_WEB = "https://leisure.example.org"      # публичный адрес веба для прогона: ссылки приглашений ведут сюда
PRIO_JOB, PRIO_USER = 0, 1


def cycle_of(t: datetime) -> int:
    """Номер недели прогона: цикл 0 = вт 20.10 … пн 26.10 (онбординг, первый уикенд), дальше по семь дней."""
    return max(0, (t.astimezone(ZoneInfo(MSK)).date() - START.date()).days // 7)


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


CLOCK_SQL = [
    "CREATE TABLE sim_clock (id int PRIMARY KEY, now timestamptz NOT NULL)",
    "INSERT INTO sim_clock VALUES (1, '2026-10-20T00:00:00+00')",
    """CREATE FUNCTION sim_stamp() RETURNS trigger AS $$
       BEGIN
         IF TG_TABLE_NAME = 'invite_accepts' THEN
           IF TG_OP = 'INSERT' THEN NEW.opened_at := (SELECT now FROM sim_clock WHERE id = 1); END IF;
         ELSIF TG_TABLE_NAME IN ('invites', 'growth_events', 'accounts') THEN
           IF TG_OP = 'INSERT' THEN NEW.created_at := (SELECT now FROM sim_clock WHERE id = 1); END IF;
         ELSE
           IF TG_OP = 'INSERT' THEN NEW.created_at := (SELECT now FROM sim_clock WHERE id = 1); END IF;
           NEW.updated_at := (SELECT now FROM sim_clock WHERE id = 1);
         END IF;
         RETURN NEW;
       END $$ LANGUAGE plpgsql""",
] + [f"CREATE TRIGGER sim_stamp_{t} BEFORE INSERT OR UPDATE ON {t} FOR EACH ROW EXECUTE FUNCTION sim_stamp()"
     for t in ("profiles", "decisions", "invites", "invite_accepts", "growth_events", "accounts")]


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



class Findings:
    """Счётчики и первые примеры наблюдений. Пример — одна строка с временем, пользователем и фактом из лога."""

    def __init__(self, keep: int = 6) -> None:
        self.keep = keep
        self.count: Counter = Counter()
        self.examples: dict[str, list[str]] = {}
        self.users: dict[str, set] = {}
        self.ignore: set[int] = set()          # приглашённые и пришедшие по ссылке: их наблюдения в основные счётчики не идут
        self.guest_count: Counter = Counter()

    def add(self, code: str, msg: str, uid: int | None = None, t: datetime | None = None, n: int = 1) -> None:
        if uid is not None and uid in self.ignore:
            self.guest_count[code] += n
            return
        self.count[code] += n
        if uid is not None:
            self.users.setdefault(code, set()).add(uid)
        ex = self.examples.setdefault(code, [])
        if len(ex) < self.keep:
            stamp = t.strftime("%d.%m %H:%MZ") if t else ""
            ex.append(" ".join(x for x in (stamp, f"u{uid}" if uid is not None else "", msg) if x))

    def to_dict(self) -> dict:
        return {c: {"count": n, "users": len(self.users.get(c, ())), "examples": self.examples.get(c, [])}
                for c, n in sorted(self.count.items())}
