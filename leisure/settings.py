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


PLACEHOLDER = "REPLACE_ME"
DEV_SECRET = "dev-only-change-me"


def _opt(name: str, default: str = "") -> str:
    """Значение переменной; пустое или плейсхолдер из .env.example считаются незаданными."""
    val = os.getenv(name, "").strip()
    return default if not val or val == PLACEHOLDER else val


def _req(name: str) -> str:
    val = _opt(name)
    if not val:
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

# ─── Админка ───
ADMIN_USER = _opt("ADMIN_USER", "admin")
ADMIN_PASSWORD = _opt("ADMIN_PASSWORD", "")  # пустой пароль = админка выключена
SECRET_KEY = _opt("SECRET_KEY", DEV_SECRET)  # с DEV_SECRET админка не поднимается
# Общий ключ для бота/воркера/веба к API (заголовок X-API-Key). Без него закрытые маршруты отвечают 401,
# если явно не включён режим разработки LEISURE_DEV_OPEN_API=1.
API_KEY = _opt("API_KEY", "")
# Сборщики событий: читать ли robots.txt источников и останавливаться при запрете. Решение владельца продукта
# от 24.10.2026: на MVP агрегаторы (KudaGo и др.) собираем бесплатно, проверяя спрос, поэтому по умолчанию 0.
# Ссылка на первоисточник в каждой карточке обязательна; технические блокировки (403) не обходим.
COLLECTORS_RESPECT_ROBOTS = _opt("COLLECTORS_RESPECT_ROBOTS", "0") == "1"
# Рубильник источников: имена коллекторов через запятую (регистр и пробелы не важны), например "afisha, mosbilet".
# Отключённый источник collect_all не запускает; по умолчанию пусто. Читается при каждом сборе (collectors_disabled).
COLLECTORS_DISABLED = _opt("COLLECTORS_DISABLED", "")
DEV_OPEN_API = _opt("LEISURE_DEV_OPEN_API", "0") == "1"


def collectors_disabled() -> frozenset[str]:
    """Имена отключённых коллекторов из COLLECTORS_DISABLED (в нижнем регистре), актуальные на момент вызова."""
    return frozenset(n.strip().lower() for n in _opt("COLLECTORS_DISABLED").split(",") if n.strip())


# ─── Секреты (лениво) ───
def bot_token() -> str:
    return _req("LEISURE_BOT_TOKEN")


def openrouter_key() -> str:
    return _req("OPENROUTER_KEY")


NORMALIZE_MODEL = _opt("NORMALIZE_MODEL", "anthropic/claude-sonnet-4.5")
