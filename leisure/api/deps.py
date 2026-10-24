"""Зависимости FastAPI: сессия БД и проверка ключа API."""
from __future__ import annotations

from fastapi import Header, HTTPException, status

from leisure import settings
from leisure.db.session import get_session  # noqa: F401  (реэкспорт для роутеров)


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Если API_KEY задан — требуем заголовок X-API-Key. Авторизация пользователей через Telegram initData — этап веба."""
    if settings.API_KEY and x_api_key != settings.API_KEY:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "нужен заголовок X-API-Key")
