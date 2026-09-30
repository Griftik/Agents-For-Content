"""Async-движок SQLAlchemy. SQLite по умолчанию, Postgres — через DATABASE_URL."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def init_engine(url: str) -> AsyncEngine:
    global _engine, _sessionmaker
    _engine = create_async_engine(url, future=True)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def session() -> AsyncSession:
    if _sessionmaker is None:
        raise RuntimeError("init_engine() не вызван")
    return _sessionmaker()


