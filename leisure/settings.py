"""Настройки планировщика досуга: читаются из окружения / leisure/.env.

Секреты в git не попадают (см. .gitignore в корне репозитория). Шаблон — leisure/.env.example.
Ничего не падает при импорте без .env: обязательные значения запрашиваются лениво через функции.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
load_dotenv(ROOT.parent / ".env")  # общий .env Фабрики, если переменные лежат там


def _opt(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _req(name: str) -> str:
    val = _opt(name)
    if not val or val == "REPLACE_ME":
        raise RuntimeError(
            f"Не задана переменная окружения {name}. Впиши её в leisure/.env (шаблон — leisure/.env.example)."
        )
    return val


# ─── База данных ───
DATABASE_URL = _opt("DATABASE_URL", "postgresql+psycopg://leisure:leisure@localhost:5432/leisure")
REDIS_URL = _opt("REDIS_URL", "redis://localhost:6379/0")

# ─── Продукт ───
DEFAULT_CITY = _opt("LEISURE_CITY", "Москва")
DEFAULT_TZ = _opt("LEISURE_TZ", "Europe/Moscow")
WEB_BASE_URL = _opt("WEB_BASE_URL", "http://localhost:8000")  # публичные страницы событий /e/<slug>
SCORING_CONFIG = Path(_opt("SCORING_CONFIG", str(ROOT / "core" / "scoring.yaml")))

# ─── Админка ───
ADMIN_USER = _opt("ADMIN_USER", "admin")
ADMIN_PASSWORD = _opt("ADMIN_PASSWORD", "")  # пустой пароль = админка выключена
SECRET_KEY = _opt("SECRET_KEY", "dev-only-change-me")
# Общий ключ для бота/воркера/веба к API (заголовок X-API-Key). Пустой = API открыт (только для разработки).
API_KEY = _opt("API_KEY", "")


# ─── Секреты (лениво) ───
def bot_token() -> str:
    return _req("LEISURE_BOT_TOKEN")


def openrouter_key() -> str:
    return _req("OPENROUTER_KEY")


NORMALIZE_MODEL = _opt("NORMALIZE_MODEL", "anthropic/claude-sonnet-4.5")
