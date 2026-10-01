"""Проверка initData мини-приложения (core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app).

Telegram подписывает данные о пользователе токеном бота; без верной подписи API не отвечает,
поэтому подделать чужой Telegram ID нельзя.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl


class InitDataError(ValueError):
    pass


@dataclass
class WebAppUser:
    id: int
    first_name: str | None
    username: str | None
    start_param: str | None


def _secret(bot_token: str) -> bytes:
    return hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()


def sign(fields: dict[str, str], bot_token: str) -> str:
    """Собрать initData с подписью (для тестов и локальной отладки)."""
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    h = hmac.new(_secret(bot_token), check.encode(), hashlib.sha256).hexdigest()
    from urllib.parse import urlencode

    return urlencode({**fields, "hash": h})


def validate(init_data: str, bot_token: str, max_age_sec: int, now: float | None = None) -> WebAppUser:
    if not init_data:
        raise InitDataError("нет initData")
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received = pairs.pop("hash", "")
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    expected = hmac.new(_secret(bot_token), check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        raise InitDataError("подпись не сходится")
    auth_date = int(pairs.get("auth_date", "0") or 0)
    if max_age_sec and (now or time.time()) - auth_date > max_age_sec:
        raise InitDataError("initData устарели")
    try:
        user = json.loads(pairs["user"])
        return WebAppUser(int(user["id"]), user.get("first_name"), user.get("username"), pairs.get("start_param"))
    except (KeyError, ValueError, TypeError) as e:
        raise InitDataError("нет пользователя") from e
