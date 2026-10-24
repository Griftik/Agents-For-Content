"""Доступ к синхронному сервисному слою из async-обработчиков бота: одна сессия на вызов, в отдельном потоке."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from leisure.db.session import session_factory


async def run_db(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    def _call():
        with session_factory()() as session:
            return fn(session, *args, **kwargs)

    return await asyncio.to_thread(_call)
