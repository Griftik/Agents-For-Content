"""Движок и сессии SQLAlchemy. URL — из leisure/settings.py (переменная DATABASE_URL)."""
from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from leisure import settings


@lru_cache(maxsize=1)
def engine() -> Engine:
    return create_engine(settings.DATABASE_URL, pool_pre_ping=True)


@lru_cache(maxsize=1)
def session_factory() -> sessionmaker[Session]:
    return sessionmaker(engine(), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """Зависимость FastAPI: одна сессия на запрос."""
    with session_factory()() as s:
        yield s
