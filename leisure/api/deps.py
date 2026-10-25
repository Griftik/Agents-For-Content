"""Зависимости FastAPI: сессия БД и проверка ключа API."""
from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, status

from leisure import settings
from leisure.db.session import get_session  # noqa: F401  (реэкспорт для роутеров)


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Закрытые маршруты требуют X-API-Key. Без настроенного ключа — отказ (fail closed), кроме явного
    режима разработки LEISURE_DEV_OPEN_API=1. Авторизация пользователей через Telegram initData — этап веба."""
    if not settings.API_KEY:
        if settings.DEV_OPEN_API:
            return
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "API_KEY не настроен — закрытые маршруты недоступны")
    if not x_api_key or not secrets.compare_digest(x_api_key.encode(), settings.API_KEY.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "нужен заголовок X-API-Key")


def resolve_user_id(body_uid: int | None, header_uid: str | None, query_uid: int | None = None) -> int:
    """user_id сессии веба: в теле, в query или заголовком X-User-Id (его выставляет сервер веба после проверки cookie)."""
    for v in (body_uid, query_uid):
        if v is not None:
            return v
    if header_uid and header_uid.lstrip("-").isdigit():
        return int(header_uid)
    raise HTTPException(422, "нужен user_id (в теле, в query или заголовком X-User-Id)")
